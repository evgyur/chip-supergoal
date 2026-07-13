#!/usr/bin/env python3
"""Verify immutable foundation capability and provenance receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_records(
    capabilities: dict[str, Any],
    provenance: dict[str, Any],
    *,
    required_capability: str,
    windows_versions: list[str],
    require_linux_parity: bool,
) -> dict[str, Any]:
    selected = capabilities.get("selected_foundation_sha")
    rollback = capabilities.get("rollback_sha")
    if selected == rollback:
        raise ValueError("plain main is forbidden as the selected foundation")
    if selected != provenance.get("selected_foundation_sha") or rollback != provenance.get("rollback_sha"):
        raise ValueError("capability/provenance SHA binding mismatch")
    if capabilities.get("status") != "pass":
        raise ValueError("foundation capabilities are not green")
    if required_capability != "native_windows_v1":
        raise ValueError(f"unsupported required capability: {required_capability}")
    native = capabilities.get("native_windows_v1", {})
    if native.get("status") != "pass":
        raise ValueError("native_windows_v1 is not green")
    actual_versions = native.get("python_versions", [])
    for requested in windows_versions:
        if not any(str(actual).startswith(f"{requested}.") or str(actual) == requested for actual in actual_versions):
            raise ValueError(f"missing native Windows Python {requested} receipt")
    if require_linux_parity and capabilities.get("linux_parity", {}).get("status") != "pass":
        raise ValueError("Linux parity is not green")
    return {
        "selected_foundation_sha": selected,
        "rollback_sha": rollback,
        "native_windows_v1": "pass",
        "windows_versions": actual_versions,
        "linux_parity": "pass" if require_linux_parity else "not_required",
    }


def verify_receipt_files(repo: Path, capabilities: dict[str, Any]) -> None:
    receipts = list(capabilities["native_windows_v1"].get("receipts", []))
    receipts.append(capabilities["linux_parity"]["receipt"])
    for receipt in receipts:
        path = repo / receipt["path"]
        if not path.is_file() or sha256(path) != receipt["sha256"]:
            raise ValueError(f"receipt hash mismatch: {receipt['path']}")
        value = load_json(path)
        if value.get("status") != receipt["status"]:
            raise ValueError(f"receipt status mismatch: {receipt['path']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--capabilities", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--require", required=True)
    parser.add_argument("--windows", action="append", default=[])
    parser.add_argument("--linux-parity", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = Path(args.repo).resolve()
    capabilities = load_json((repo / args.capabilities).resolve())
    provenance = load_json((repo / args.provenance).resolve())
    result = verify_records(
        capabilities,
        provenance,
        required_capability=args.require,
        windows_versions=args.windows,
        require_linux_parity=args.linux_parity,
    )
    verify_receipt_files(repo, capabilities)
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
