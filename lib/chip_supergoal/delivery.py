from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .events import (
    canonical_json_value_bytes,
    now_rfc3339_z_seconds,
    parse_rfc3339_z_seconds,
    strict_json_loads,
)
from .model import canonical_json, contract_from_dict
from .portable import (
    package_lock,
    package_operation_lock,
    read_regular_file_no_follow,
    write_bytes_atomic,
)
from .state import State, StateStore, assert_runtime_mutable


_SHA256 = re.compile(r"[a-f0-9]{64}")
REQUIRED_REVIEW_FILES = frozenset(
    {"THINKING.md", "LOOP_DESIGN.md", "ROADMAP.md", "LAUNCH_GOAL.md"}
)


class ReceiptValidationError(ValueError):
    pass


def delivery_receipt_required(delivery: dict[str, Any]) -> bool:
    if not isinstance(delivery, dict):
        raise ReceiptValidationError("delivery must be an object")
    review_required = delivery.get("review_pack_required", False)
    if type(review_required) is not bool:
        raise ReceiptValidationError(
            "delivery.review_pack_required must be a boolean"
        )
    policy = delivery.get("receipt_policy")
    if policy is not None and not isinstance(policy, dict):
        raise ReceiptValidationError("delivery.receipt_policy must be an object")
    required = policy.get("required", False) if policy is not None else False
    if type(required) is not bool:
        raise ReceiptValidationError(
            "delivery.receipt_policy.required must be a boolean"
        )
    required = required or review_required
    if not required:
        return False
    transport = delivery.get("transport")
    if (
        not isinstance(transport, str)
        or not transport.strip()
        or transport.strip().lower() == "none"
    ):
        raise ReceiptValidationError(
            "required delivery receipt needs an enabled non-none transport"
        )
    target = delivery.get("target")
    if not isinstance(target, str) or not target.strip():
        raise ReceiptValidationError(
            "required delivery receipt needs a nonempty target"
        )
    return True


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
    try:
        canonical_json_value_bytes(receipt)
    except (TypeError, ValueError) as exc:
        raise ReceiptValidationError("receipt must contain strict JSON values") from exc
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
    raise ReceiptValidationError(
        "canonical final archive authority is unavailable until Task 6"
    )


def _canonical_receipt_bytes(receipt: dict[str, Any]) -> bytes:
    canonical_json_value_bytes(receipt)
    return (
        json.dumps(
            receipt,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _load_delivery_authority(root: Path) -> tuple[Any, State, StateStore]:
    store = StateStore(root)
    events = store._validated_events()
    state = State.from_dict(events[-1]["state"])
    store._assert_projections_current(state)
    raw = read_regular_file_no_follow(root / "CONTRACT.json", root)
    try:
        loaded = json.loads(raw)
        contract = contract_from_dict(loaded, strict=True)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-CONTRACT-MISMATCH: contract is malformed"
        ) from exc
    if raw != canonical_json(contract).encode("utf-8"):
        raise ReceiptValidationError(
            "SGV-DELIVERY-CONTRACT-MISMATCH: contract is not canonical"
        )
    digest = hashlib.sha256(raw).hexdigest()
    if (
        state.goal_id != contract.goal.id
        or state.contract_sha256 != digest
        or state.contract_revision != contract.contract_revision
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-CONTRACT-MISMATCH: runtime identity differs from contract"
        )
    return contract, state, store


def _review_material(
    root: Path, contract: Any, target: str
) -> tuple[list[str], dict[str, str]]:
    delivery = contract.delivery.data
    if not delivery_receipt_required(delivery):
        raise ReceiptValidationError(
            "SGV-DELIVERY-NOT-REQUIRED: review receipt policy is not required"
        )
    if delivery.get("review_pack_required") is not True:
        raise ReceiptValidationError(
            "SGV-DELIVERY-NOT-REQUIRED: review pack is not required"
        )
    if delivery.get("target") != target:
        raise ReceiptValidationError(
            "SGV-DELIVERY-TARGET-MISMATCH: target differs from contract"
        )
    declared = delivery.get("files")
    if (
        not isinstance(declared, list)
        or not all(
            isinstance(item, str)
            and item
            and item == Path(item).name
            and "\r" not in item
            and "\n" not in item
            for item in declared
        )
        or len(declared) != len(set(declared))
        or not REQUIRED_REVIEW_FILES.issubset(declared)
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-FILE-SET-MISMATCH: delivery.files is invalid"
        )
    files = sorted(
        item
        for item in declared
        if item != "RESEARCH.md" or os.path.lexists(root / item)
    )
    hashes: dict[str, str] = {}
    for item in files:
        try:
            data = read_regular_file_no_follow(root / item, root)
        except OSError as exc:
            raise ReceiptValidationError(
                f"SGV-DELIVERY-FILE-SET-MISMATCH: missing review file {item}"
            ) from exc
        if not data:
            raise ReceiptValidationError(
                f"SGV-DELIVERY-FILE-SET-MISMATCH: empty review file {item}"
            )
        hashes[item] = hashlib.sha256(data).hexdigest()
    return files, hashes


def check_review_delivery(
    root: str | Path, *, target: str
) -> dict[str, Any] | None:
    package_root = Path(root)
    with package_operation_lock(package_root):
        contract, state, store = _load_delivery_authority(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            files, hashes = _review_material(package_root, contract, target)
            path = package_root / "out/review-md-files-delivery-receipt.json"
            if not os.path.lexists(path):
                return None
            try:
                receipt = read_receipt(path, package_root)
                validate_review_receipt(
                    receipt,
                    state=state,
                    target=target,
                    hashes=hashes,
                )
            except (OSError, ValueError) as exc:
                raise ReceiptValidationError(
                    f"SGV-DELIVERY-RECEIPT-INVALID: {exc}"
                ) from exc
            if receipt["files"] != files:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-RECEIPT-INVALID: receipt file order is not canonical"
                )
            return receipt


def record_review_delivery(
    root: str | Path,
    *,
    target: str,
    message_ids: list[str],
    force: bool = False,
) -> dict[str, Any]:
    package_root = Path(root)
    with package_operation_lock(package_root):
        contract, state, store = _load_delivery_authority(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            assert_runtime_mutable(package_root)
            files, hashes = _review_material(package_root, contract, target)
            path = package_root / "out/review-md-files-delivery-receipt.json"
            if os.path.lexists(path) and not force:
                try:
                    existing = read_receipt(path, package_root)
                    validate_review_receipt(
                        existing,
                        state=state,
                        target=target,
                        hashes=hashes,
                    )
                except (OSError, ValueError) as exc:
                    raise ReceiptValidationError(
                        f"SGV-DELIVERY-RECEIPT-INVALID: {exc}"
                    ) from exc
                if existing["files"] != files:
                    raise ReceiptValidationError(
                        "SGV-DELIVERY-RECEIPT-INVALID: receipt file order is not canonical"
                    )
                return existing
            if (
                not isinstance(message_ids, list)
                or len(message_ids) != len(files)
                or not all(
                    isinstance(message_id, str) and message_id.strip()
                    for message_id in message_ids
                )
            ):
                raise ReceiptValidationError(
                    "SGV-DELIVERY-MESSAGE-ID-MISMATCH: one message id is required per review file"
                )
            receipt = {
                "contract_revision": state.contract_revision,
                "contract_sha256": state.contract_sha256,
                "files": files,
                "goal_id": state.goal_id,
                "hashes": hashes,
                "kind": "review-md-files",
                "message_ids": list(message_ids),
                "ok": True,
                "pack_version": "review_pack_v2",
                "sent": True,
                "sent_at": now_rfc3339_z_seconds(),
                "target": target,
            }
            validate_review_receipt(
                receipt, state=state, target=target, hashes=hashes
            )
            write_bytes_atomic(
                path,
                _canonical_receipt_bytes(receipt),
                root=package_root,
            )
            return receipt


def require_final_delivery_authority(
    root: str | Path, *, target: str, archive: str | Path
) -> None:
    package_root = Path(root)
    with package_operation_lock(package_root):
        contract, _, store = _load_delivery_authority(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            delivery = contract.delivery.data
            if not delivery_receipt_required(delivery) or not delivery.get("items"):
                raise ReceiptValidationError(
                    "SGV-DELIVERY-NOT-REQUIRED: final receipt policy is not required"
                )
            if delivery.get("target") != target:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-TARGET-MISMATCH: target differs from contract"
                )
            archive_path = Path(archive)
            if not archive_path.is_absolute():
                archive_path = package_root / archive_path
            if not archive_path.is_file():
                raise ReceiptValidationError(
                    "SGV-DELIVERY-ARCHIVE-MISSING: final archive does not exist"
                )
            raise ReceiptValidationError(
                "SGV-DELIVERY-ARCHIVE-AUTHORITY-UNAVAILABLE: "
                "Task 6 canonical result validation is not available"
            )


def read_receipt(path: Path, root: Path) -> dict[str, Any]:
    raw = read_regular_file_no_follow(path, root)
    try:
        value = strict_json_loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReceiptValidationError("receipt JSON is malformed") from exc
    if not isinstance(value, dict):
        raise ReceiptValidationError("receipt must be an object")
    canonical = _canonical_receipt_bytes(value)
    if raw != canonical:
        raise ReceiptValidationError("receipt JSON is not canonical")
    return value
