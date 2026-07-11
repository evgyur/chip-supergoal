from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .events import parse_rfc3339_z_seconds
from .portable import read_regular_file_no_follow
from .state import State


_SHA256 = re.compile(r"[a-f0-9]{64}")
REQUIRED_REVIEW_FILES = frozenset(
    {"THINKING.md", "LOOP_DESIGN.md", "ROADMAP.md", "LAUNCH_GOAL.md"}
)


class ReceiptValidationError(ValueError):
    pass


def sha256_file(path: str | Path, *, root: str | Path | None = None) -> str:
    file_path = Path(path)
    data = (
        read_regular_file_no_follow(file_path, Path(root))
        if root is not None
        else file_path.read_bytes()
    )
    return hashlib.sha256(data).hexdigest()


def _require_exact_fields(
    receipt: dict[str, Any], required: set[str], optional: set[str]
) -> None:
    if not isinstance(receipt, dict):
        raise ReceiptValidationError("receipt must be an object")
    missing = sorted(required - set(receipt))
    unknown = sorted(set(receipt) - required - optional)
    if missing:
        raise ReceiptValidationError(f"missing receipt fields: {', '.join(missing)}")
    if unknown:
        raise ReceiptValidationError(f"unknown receipt fields: {', '.join(unknown)}")


def _validate_identity(receipt: dict[str, Any], state: State) -> None:
    if (
        receipt.get("goal_id") != state.goal_id
        or receipt.get("contract_sha256") != state.contract_sha256
        or receipt.get("contract_revision") != state.contract_revision
    ):
        raise ReceiptValidationError("receipt contract identity mismatch")
    parse_rfc3339_z_seconds(receipt.get("sent_at"))


def validate_review_receipt(
    receipt: dict[str, Any],
    *,
    state: State,
    target: str,
    hashes: dict[str, str],
) -> None:
    required = {
        "ok",
        "sent",
        "kind",
        "pack_version",
        "goal_id",
        "contract_sha256",
        "contract_revision",
        "target",
        "files",
        "hashes",
        "message_ids",
        "sent_at",
    }
    _require_exact_fields(receipt, required, {"extensions"})
    _validate_identity(receipt, state)
    if receipt.get("ok") is not True or receipt.get("sent") is not True:
        raise ReceiptValidationError("receipt not ok/sent")
    if (
        receipt.get("kind") != "review-md-files"
        or receipt.get("pack_version") != "review_pack_v2"
    ):
        raise ReceiptValidationError("receipt kind/version mismatch")
    if receipt.get("target") != target or receipt.get("hashes") != hashes:
        raise ReceiptValidationError("receipt target/hash mismatch")
    files = receipt.get("files")
    if (
        not isinstance(files, list)
        or not all(isinstance(item, str) for item in files)
        or len(files) != len(set(files))
        or sorted(files) != sorted(hashes)
        or not REQUIRED_REVIEW_FILES.issubset(files)
    ):
        raise ReceiptValidationError("receipt file set mismatch")
    message_ids = receipt.get("message_ids")
    if (
        not isinstance(message_ids, list)
        or len(message_ids) != len(files)
        or not all(isinstance(item, str) and item.strip() for item in message_ids)
    ):
        raise ReceiptValidationError("receipt message_ids invalid")
    if "extensions" in receipt and not isinstance(receipt["extensions"], dict):
        raise ReceiptValidationError("receipt extensions must be an object")


def validate_final_receipt(
    receipt: dict[str, Any],
    *,
    state: State,
    target: str,
) -> None:
    required = {
        "ok",
        "sent",
        "kind",
        "goal_id",
        "contract_sha256",
        "contract_revision",
        "target",
        "archive",
        "hash",
        "message_id",
        "sent_at",
    }
    _require_exact_fields(receipt, required, {"extensions"})
    _validate_identity(receipt, state)
    if receipt.get("ok") is not True or receipt.get("sent") is not True:
        raise ReceiptValidationError("receipt not ok/sent")
    if receipt.get("kind") != "final-artifacts":
        raise ReceiptValidationError("receipt kind mismatch")
    if receipt.get("target") != target:
        raise ReceiptValidationError("receipt target mismatch")
    if not isinstance(receipt.get("archive"), str) or not receipt["archive"]:
        raise ReceiptValidationError("receipt archive invalid")
    if not isinstance(receipt.get("hash"), str) or not _SHA256.fullmatch(
        receipt["hash"]
    ):
        raise ReceiptValidationError("receipt archive hash invalid")
    if not isinstance(receipt.get("message_id"), str) or not receipt[
        "message_id"
    ].strip():
        raise ReceiptValidationError("receipt message_id invalid")
    if "extensions" in receipt and not isinstance(receipt["extensions"], dict):
        raise ReceiptValidationError("receipt extensions must be an object")


def read_receipt(path: Path, root: Path) -> dict[str, Any]:
    raw = read_regular_file_no_follow(path, root)
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptValidationError("receipt JSON is malformed") from exc
    if not isinstance(value, dict):
        raise ReceiptValidationError("receipt must be an object")
    canonical = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if raw != canonical:
        raise ReceiptValidationError("receipt JSON is not canonical")
    return value
