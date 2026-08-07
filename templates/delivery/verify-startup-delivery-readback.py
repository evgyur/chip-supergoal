#!/usr/bin/env python3
"""Fail-closed verifier for Telegram startup-pack destination readback."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


FILES = ["THINKING.md", "ROADMAP.md", "LAUNCH_GOAL.md"]


def load_regular(path: Path) -> tuple[dict, str]:
    path = path.resolve(strict=True)
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError(f"unsafe receipt file: {path}")
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def parse_target(target: str) -> tuple[str, str]:
    parts = target.split(":")
    if len(parts) != 3 or parts[0] != "telegram" or not parts[1] or not parts[2]:
        raise ValueError("sealed target must be telegram:<chat_id>:<thread_id>")
    return parts[1], parts[2]


def atomic_write(path: Path, payload: dict) -> None:
    path = path.resolve(strict=False)
    root_out = path.parents[0]
    root_out.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ValueError("output receipt must not be a symlink")
    fd, tmp = tempfile.mkstemp(prefix=".readback-", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--transport-receipt", required=True)
    ap.add_argument("--readback-receipt", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    contract_path = Path(args.contract).resolve(strict=True)
    root = contract_path.parent
    contract, contract_sha = load_regular(contract_path)
    delivery = contract.get("delivery", {})
    target = delivery.get("telegram_thread")
    if delivery.get("files") != FILES:
        raise SystemExit("contract startup inventory/order mismatch")
    chat_id, thread_id = parse_target(target)

    transport, transport_sha = load_regular(Path(args.transport_receipt))
    readback, readback_sha = load_regular(Path(args.readback_receipt))
    if transport.get("kind") != "startup-files-transport" or transport.get("pack_version") != "startup_pack_v4":
        raise SystemExit("invalid transport receipt kind/version")
    if transport.get("target") != target or transport.get("files") != FILES:
        raise SystemExit("transport receipt target/files differ from sealed contract")
    message_ids = [str(x) for x in transport.get("message_ids", [])]
    if len(message_ids) != 3 or any(not x for x in message_ids):
        raise SystemExit("transport receipt must contain exactly three message ids")
    expected_hashes = transport.get("hashes")
    if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(FILES):
        raise SystemExit("transport receipt hashes are incomplete")

    if readback.get("schema") != "chip-supergoal.telegram-readback.v1" or readback.get("target") != target:
        raise SystemExit("readback schema/target mismatch")
    sender = readback.get("sender")
    if not isinstance(sender, dict) or not str(sender.get("id") or sender.get("username") or "").strip():
        raise SystemExit("readback sender identity is missing")
    items = readback.get("items")
    if not isinstance(items, list) or len(items) != 3:
        raise SystemExit("readback must contain exactly three items")

    verified = []
    for index, (label, message_id) in enumerate(zip(FILES, message_ids)):
        item = items[index]
        required = {"order", "message_id", "filename", "sha256", "bytes", "has_media", "media_type", "chat_id", "thread_id"}
        if not isinstance(item, dict) or required - set(item):
            raise SystemExit(f"readback item {index} missing required fields")
        if item["order"] != index or str(item["message_id"]) != message_id:
            raise SystemExit(f"readback item {index} order/message mismatch")
        if item["filename"] != label or item["sha256"] != expected_hashes[label]:
            raise SystemExit(f"readback item {index} filename/hash mismatch")
        if not isinstance(item["bytes"], int) or item["bytes"] <= 0:
            raise SystemExit(f"readback item {index} has invalid attachment size")
        if item["has_media"] is not True or "document" not in str(item["media_type"]).lower():
            raise SystemExit(f"readback item {index} is not a document attachment")
        if str(item["chat_id"]) != chat_id or str(item["thread_id"]) != thread_id:
            raise SystemExit(f"readback item {index} destination/thread mismatch")
        verified.append({**item, "readback_verified": True})

    out = Path(args.out).resolve(strict=False)
    out_root = (root / "out").resolve(strict=False)
    if not out.is_relative_to(out_root):
        raise SystemExit("final delivery receipt must stay under package out/")
    receipt = {
        "schema": "chip-supergoal.startup-delivery.v2",
        "ok": True,
        "sent": True,
        "readback_verified": True,
        "kind": "startup-files",
        "pack_version": "startup_pack_v4",
        "target": target,
        "files": FILES,
        "hashes": expected_hashes,
        "message_ids": message_ids,
        "file_message_ids": dict(zip(FILES, message_ids)),
        "launch_file": "LAUNCH_GOAL.md",
        "launch_message_id": message_ids[-1],
        "sent_at": transport.get("sent_at"),
        "sender": sender,
        "readback_items": verified,
        "contract_sha256": contract_sha,
        "transport_receipt_sha256": transport_sha,
        "readback_receipt_sha256": readback_sha,
        "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    atomic_write(out, receipt)
    print(json.dumps({"ok": True, "receipt": str(out), "launch_message_id": message_ids[-1]}, sort_keys=True))


if __name__ == "__main__":
    main()
