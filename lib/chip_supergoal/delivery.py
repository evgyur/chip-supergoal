from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading
from typing import Any
import uuid

from .events import (
    canonical_json_value_bytes,
    now_rfc3339_z_seconds,
    parse_rfc3339_z_seconds,
    strict_json_loads,
)
from .archive import (
    ArchiveSecurityError,
    capture_validated_package_snapshot,
    require_archive_result,
    require_archive_result_with_bytes,
)
from .model import canonical_json, contract_from_dict
from .portable import (
    DELIVERY_RESERVATION_KINDS,
    assert_no_pending_delivery_reservations,
    capture_root_identity,
    delivery_receipt_pending_path,
    delivery_reservation_pending_path,
    delivery_reservation_path,
    is_reparse_point,
    open_stable_transport_file,
    package_lock,
    package_operation_lock,
    read_regular_file_no_follow,
    unlink_regular_file_no_follow,
    write_bytes_atomic,
)
from .state import State, StateStore, assert_runtime_mutable, state_sha256


_SHA256 = re.compile(r"[a-f0-9]{64}")
REQUIRED_REVIEW_FILES = frozenset(
    {"THINKING.md", "LOOP_DESIGN.md", "ROADMAP.md", "LAUNCH_GOAL.md"}
)
MAX_DELIVERY_RECEIPT_BYTES = 1024 * 1024
DELIVERY_AUTHORIZATION_VERSION = "1.0"
DELIVERY_RESERVATION_VERSION = "1.1"
DELIVERY_STAGE_VERSION = "1.0"
MAX_DELIVERY_RESERVATION_BYTES = 2 * 1024 * 1024
MAX_DELIVERY_MESSAGE_ID_BYTES = 4096
_STAGE_MARKER = ".supergoal-delivery-stage.json"


class ReceiptValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DeliveryCheck:
    receipt: dict[str, Any] | None
    authorization: dict[str, Any] | None

    def __post_init__(self) -> None:
        if (self.receipt is None) == (self.authorization is None):
            raise ValueError(
                "delivery check must contain exactly one receipt or authorization"
            )


def _valid_message_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and "\r" not in value
        and "\n" not in value
        and "\x00" not in value
        and len(value.encode("utf-8")) <= MAX_DELIVERY_MESSAGE_ID_BYTES
    )


def _valid_progress_entry(value: object) -> bool:
    if (
        not isinstance(value, dict)
        or set(value) != {"message_id", "sent_at"}
        or not _valid_message_id(value.get("message_id"))
    ):
        return False
    try:
        parse_rfc3339_z_seconds(value.get("sent_at"))
    except (TypeError, ValueError):
        return False
    return True


def _transport_timeout_seconds() -> float:
    raw = os.environ.get("SUPERGOAL_TRANSPORT_TIMEOUT_SECONDS", "300")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: transport timeout is invalid"
        ) from exc
    if not 1 <= value <= 3600:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: transport timeout must be 1..3600 seconds"
        )
    return value


def _run_transport_file(
    path: Path,
    stage_root: Path,
    *,
    target: str,
    logical_name: str,
    reservation_id: str,
    expected_bytes: int,
    expected_sha256: str,
) -> str:
    command = os.environ.get("SUPERGOAL_TRANSPORT_SEND_FILE_CMD", "")
    if not command.strip():
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: no real transport command is configured"
        )
    # Validate every fallible process option before the transport is started.
    # Once Popen succeeds the remote side may have accepted the bytes, so no
    # local configuration error may escape without durable send progress.
    timeout_seconds = _transport_timeout_seconds()
    identity = capture_root_identity(stage_root)
    with ExitStack() as stack:
        stream, advertised_path, pass_fds = stack.enter_context(
            open_stable_transport_file(
                path, stage_root, root_identity=identity
            )
        )
        immutable = (
            stack.enter_context(tempfile.TemporaryFile())
            if os.name != "nt"
            else None
        )
        digest = hashlib.sha256()
        observed = 0
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > expected_bytes:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-SEND-PENDING: transport file exceeds authorization"
                )
            digest.update(chunk)
            if immutable is not None:
                immutable.write(chunk)
        if observed != expected_bytes or digest.hexdigest() != expected_sha256:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: transport file bytes differ from authorization"
            )
        if immutable is None:
            stream.seek(0)
        else:
            immutable.flush()
            os.fsync(immutable.fileno())
            descriptor_root = Path(advertised_path).parent
            read_fd = os.open(
                descriptor_root / str(immutable.fileno()), os.O_RDONLY
            )
            transport_stream = stack.enter_context(
                os.fdopen(read_fd, "rb", buffering=0)
            )
            advertised_path = str(
                descriptor_root / str(transport_stream.fileno())
            )
            pass_fds = (transport_stream.fileno(),)
        environment = os.environ.copy()
        environment.update(
            {
                "SUPERGOAL_SEND_FILE": advertised_path,
                "SUPERGOAL_SEND_IDEMPOTENCY_KEY": (
                    f"{reservation_id}:{logical_name}"
                ),
                "SUPERGOAL_SEND_NAME": logical_name,
                "SUPERGOAL_SEND_TARGET": target,
            }
        )
        arguments: str | list[str]
        options: dict[str, Any] = {
            "env": environment,
            "stderr": None,
            "stdout": subprocess.PIPE,
        }
        if os.name == "nt":
            arguments = command
            options["shell"] = True
        else:
            arguments = ["bash", "-lc", command]
            options["pass_fds"] = pass_fds
        try:
            process = subprocess.Popen(arguments, **options)
        except OSError as exc:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: transport process could not start"
            ) from exc
        assert process.stdout is not None
        stack.callback(process.stdout.close)
        output = bytearray()
        overflow = threading.Event()

        def read_stdout() -> None:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    return
                remaining = MAX_DELIVERY_MESSAGE_ID_BYTES + 3 - len(output)
                if remaining > 0:
                    output.extend(chunk[:remaining])
                if len(chunk) > remaining or len(output) > MAX_DELIVERY_MESSAGE_ID_BYTES + 2:
                    overflow.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: transport timed out"
            ) from exc
        finally:
            reader.join(5)
        if reader.is_alive():
            process.kill()
            process.wait()
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: transport output did not close"
            )
        if overflow.is_set():
            raise ReceiptValidationError(
                "SGV-DELIVERY-MESSAGE-ID-MISMATCH: transport output exceeds the bounded id limit"
            )
        if return_code != 0:
            raise ReceiptValidationError(
                f"SGV-DELIVERY-SEND-PENDING: transport exited with {return_code}"
            )
        raw = bytes(output)
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]
        try:
            message_id = raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ReceiptValidationError(
                "SGV-DELIVERY-MESSAGE-ID-MISMATCH: transport id is not UTF-8"
            ) from exc
        if not _valid_message_id(message_id):
            raise ReceiptValidationError(
                "SGV-DELIVERY-MESSAGE-ID-MISMATCH: transport id is invalid"
            )
        return message_id


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
        "reservation_id",
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
        or not all(_valid_message_id(item) for item in message_ids)
    ):
        raise ReceiptValidationError("receipt message_ids invalid")
    if not isinstance(receipt.get("reservation_id"), str) or not re.fullmatch(
        r"[a-f0-9]{32}", receipt["reservation_id"]
    ):
        raise ReceiptValidationError("receipt reservation_id invalid")
    if "extensions" in receipt and not isinstance(receipt["extensions"], dict):
        raise ReceiptValidationError("receipt extensions must be an object")


def validate_final_receipt(
    receipt: dict[str, Any],
    *,
    state: State,
    target: str,
    root: str | Path | None = None,
    archive_result: dict[str, Any] | None = None,
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
        "reservation_id",
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
    if not _valid_message_id(receipt.get("message_id")):
        raise ReceiptValidationError("receipt message_id invalid")
    if not isinstance(receipt.get("reservation_id"), str) or not re.fullmatch(
        r"[a-f0-9]{32}", receipt["reservation_id"]
    ):
        raise ReceiptValidationError("receipt reservation_id invalid")
    if "extensions" in receipt and not isinstance(receipt["extensions"], dict):
        raise ReceiptValidationError("receipt extensions must be an object")
    if archive_result is None:
        if root is None:
            raise ReceiptValidationError(
                "archive authority is required for final receipt validation"
            )
        try:
            archive_result = require_archive_result(root, receipt["archive"])
        except ValueError as exc:
            raise ReceiptValidationError(str(exc)) from exc
    identity = archive_result.get("archive_identity")
    if (
        not isinstance(identity, dict)
        or receipt["archive"] != identity.get("absolute_path")
        or receipt["hash"] != archive_result.get("archive_sha256")
    ):
        raise ReceiptValidationError("receipt archive authority mismatch")


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


def _assert_replaceable_receipt_leaf(path: Path, root: Path) -> None:
    if not os.path.lexists(path):
        return
    try:
        read_regular_file_no_follow(
            path,
            root,
            max_bytes=MAX_DELIVERY_RECEIPT_BYTES,
        )
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: receipt destination must be "
            "an absent or bounded regular no-follow file"
        ) from exc


def _authorization_base(
    root: Path,
    state: State,
    *,
    kind: str,
    target: str,
    force: bool,
    reservation_id: str,
    authorized_at: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{32}", reservation_id):
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: reservation identity is invalid"
        )
    parse_rfc3339_z_seconds(authorized_at)
    identity = capture_root_identity(root)
    return {
        "authorization_version": DELIVERY_AUTHORIZATION_VERSION,
        "authorized_at": authorized_at,
        "contract_revision": state.contract_revision,
        "contract_sha256": state.contract_sha256,
        "force": force,
        "goal_id": state.goal_id,
        "kind": kind,
        "package_root_identity": {
            "file_index_or_inode": identity.file_index_or_inode,
            "platform": identity.platform,
            "volume_or_device": identity.volume_or_device,
        },
        "reservation_id": reservation_id,
        "state_revision": state.state_revision,
        "state_sha256": state_sha256(state),
        "target": target,
    }


def _review_authorization(
    root: Path,
    state: State,
    *,
    target: str,
    force: bool,
    reservation_id: str,
    authorized_at: str,
    files: list[str],
    hashes: dict[str, str],
    stage: dict[str, Any],
) -> dict[str, Any]:
    value = _authorization_base(
        root,
        state,
        kind="review-md-files",
        target=target,
        force=force,
        reservation_id=reservation_id,
        authorized_at=authorized_at,
    )
    value.update(
        {
            "files": list(files),
            "hashes": dict(hashes),
            "stage": dict(stage),
        }
    )
    canonical_json_value_bytes(value)
    return value


def _final_authorization(
    root: Path,
    state: State,
    *,
    target: str,
    force: bool,
    reservation_id: str,
    authorized_at: str,
    archive_result: dict[str, Any],
    stage: dict[str, Any],
) -> dict[str, Any]:
    value = _authorization_base(
        root,
        state,
        kind="final-artifacts",
        target=target,
        force=force,
        reservation_id=reservation_id,
        authorized_at=authorized_at,
    )
    value.update(
        {
            "archive_bytes": archive_result.get("archive_bytes"),
            "archive_identity": archive_result.get("archive_identity"),
            "archive_sha256": archive_result.get("archive_sha256"),
            "package_fingerprint": archive_result.get("package_fingerprint"),
            "source_manifest_sha256": archive_result.get(
                "source_manifest_sha256"
            ),
            "stage": dict(stage),
        }
    )
    canonical_json_value_bytes(value)
    return value


def _require_current_authorization(
    provided: dict[str, Any], expected: dict[str, Any]
) -> None:
    try:
        provided_bytes = canonical_json_value_bytes(provided)
    except (TypeError, ValueError) as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: delivery authorization is malformed"
        ) from exc
    if provided_bytes != canonical_json_value_bytes(expected):
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: delivery authorization is stale or mismatched"
        )


def _reservation_bytes(value: dict[str, Any]) -> bytes:
    canonical_json_value_bytes(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _validate_review_stage_description(
    root: Path, authorization: dict[str, Any]
) -> None:
    stage = authorization.get("stage")
    files = authorization.get("files")
    hashes = authorization.get("hashes")
    reservation_id = authorization.get("reservation_id")
    if (
        not isinstance(stage, dict)
        or set(stage) != {"absolute_path", "files", "stage_version"}
        or stage.get("stage_version") != DELIVERY_STAGE_VERSION
        or not isinstance(stage.get("absolute_path"), str)
        or not stage["absolute_path"]
        or "\x00" in stage["absolute_path"]
        or not isinstance(stage.get("files"), list)
        or not isinstance(files, list)
        or not isinstance(hashes, dict)
        or not isinstance(reservation_id, str)
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage authority is invalid"
        )
    stage_path = Path(stage["absolute_path"])
    if (
        not stage_path.is_absolute()
        or stage_path.resolve(strict=False) != stage_path
        or stage_path.parent != root.resolve(strict=False).parent
        or not stage_path.name.endswith(f".review-delivery-{reservation_id}")
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage path is invalid"
        )
    records = stage["files"]
    if len(records) != len(files):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage inventory is invalid"
        )
    for name, record in zip(files, records, strict=True):
        if (
            not isinstance(record, dict)
            or set(record) != {"bytes", "name", "sha256"}
            or record.get("name") != name
            or type(record.get("bytes")) is not int
            or not 0 < record["bytes"] <= 16 * 1024 * 1024
            or record.get("sha256") != hashes.get(name)
        ):
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: review stage inventory is invalid"
            )


def _validate_final_stage_description(
    root: Path, authorization: dict[str, Any]
) -> None:
    stage = authorization.get("stage")
    reservation_id = authorization.get("reservation_id")
    if (
        not isinstance(stage, dict)
        or set(stage) != {"absolute_path", "files", "stage_version"}
        or stage.get("stage_version") != DELIVERY_STAGE_VERSION
        or not isinstance(stage.get("absolute_path"), str)
        or not stage["absolute_path"]
        or "\x00" in stage["absolute_path"]
        or not isinstance(stage.get("files"), list)
        or len(stage["files"]) != 1
        or not isinstance(reservation_id, str)
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: final stage authority is invalid"
        )
    stage_path = Path(stage["absolute_path"])
    record = stage["files"][0]
    if (
        not stage_path.is_absolute()
        or stage_path.resolve(strict=False) != stage_path
        or stage_path.parent != root.resolve(strict=False).parent
        or not stage_path.name.endswith(f".final-delivery-{reservation_id}")
        or not isinstance(record, dict)
        or set(record) != {"bytes", "name", "sha256"}
        or record.get("name") != "final-artifacts.zip"
        or record.get("bytes") != authorization.get("archive_bytes")
        or record.get("sha256") != authorization.get("archive_sha256")
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: final stage inventory is invalid"
        )


def _validate_authorization_shape(
    root: Path, kind: str, authorization: dict[str, Any]
) -> None:
    base = {
        "authorization_version",
        "authorized_at",
        "contract_revision",
        "contract_sha256",
        "force",
        "goal_id",
        "kind",
        "package_root_identity",
        "reservation_id",
        "state_revision",
        "state_sha256",
        "target",
    }
    extras = (
        {"files", "hashes", "stage"}
        if kind == "review-md-files"
        else {
            "archive_bytes",
            "archive_identity",
            "archive_sha256",
            "package_fingerprint",
            "source_manifest_sha256",
            "stage",
        }
    )
    if (
        not isinstance(authorization, dict)
        or set(authorization) != base | extras
        or authorization.get("authorization_version")
        != DELIVERY_AUTHORIZATION_VERSION
        or authorization.get("kind") != kind
        or type(authorization.get("force")) is not bool
        or not isinstance(authorization.get("reservation_id"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", authorization["reservation_id"])
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery authorization is invalid"
        )
    try:
        parse_rfc3339_z_seconds(authorization.get("authorized_at"))
        canonical_json_value_bytes(authorization)
    except (TypeError, ValueError) as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery authorization is invalid"
        ) from exc
    if kind == "review-md-files":
        _validate_review_stage_description(root, authorization)
    else:
        _validate_final_stage_description(root, authorization)


def _load_delivery_reservation(
    root: Path, kind: str
) -> tuple[dict[str, Any], bytes] | None:
    path = delivery_reservation_path(root, kind)
    if not os.path.lexists(path):
        return None
    try:
        raw = read_regular_file_no_follow(
            path,
            root,
            max_bytes=MAX_DELIVERY_RESERVATION_BYTES,
        )
        value = strict_json_loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery reservation is malformed"
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "authorization",
            "kind",
            "progress",
            "receipt",
            "reservation_id",
            "reservation_version",
        }
        or value.get("reservation_version") != DELIVERY_RESERVATION_VERSION
        or value.get("kind") != kind
        or not isinstance(value.get("reservation_id"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", value["reservation_id"])
        or not isinstance(value.get("authorization"), dict)
        or value["authorization"].get("reservation_id")
        != value["reservation_id"]
        or not isinstance(value.get("progress"), dict)
        or not all(
            isinstance(name, str) and _valid_progress_entry(progress)
            for name, progress in value["progress"].items()
        )
        or (
            value.get("receipt") is not None
            and (
                not isinstance(value["receipt"], dict)
                or value["receipt"].get("reservation_id")
                != value["reservation_id"]
                or value["receipt"].get("kind") != kind
            )
        )
        or raw != _reservation_bytes(value)
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery reservation is invalid"
        )
    _validate_authorization_shape(root, kind, value["authorization"])
    allowed_progress = (
        set(value["authorization"]["files"])
        if kind == "review-md-files"
        else {"archive"}
    )
    if not set(value["progress"]) <= allowed_progress:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery progress is invalid"
        )
    return value, raw


def _remove_reserved_transaction_leaf(root: Path, path: Path) -> None:
    if not os.path.lexists(path):
        return
    try:
        removed = unlink_regular_file_no_follow(path, root)
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: reserved delivery transaction path is unsafe"
        ) from exc
    if not removed:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: reserved delivery transaction path vanished"
        )


def _discard_unissued_transaction_temps(root: Path, kind: str) -> None:
    if _load_delivery_reservation(root, kind) is not None:
        return
    _remove_reserved_transaction_leaf(
        root, delivery_reservation_pending_path(root, kind)
    )
    _remove_reserved_transaction_leaf(root, delivery_receipt_pending_path(root, kind))


def _replace_delivery_reservation(
    root: Path,
    kind: str,
    expected_raw: bytes,
    value: dict[str, Any],
) -> bytes:
    loaded = _load_delivery_reservation(root, kind)
    if loaded is None or loaded[1] != expected_raw:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery reservation changed"
        )
    raw = _reservation_bytes(value)
    if len(raw) > MAX_DELIVERY_RESERVATION_BYTES:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: delivery reservation exceeds bounded limit"
        )
    pending = delivery_reservation_pending_path(root, kind)
    _remove_reserved_transaction_leaf(root, pending)
    try:
        write_bytes_atomic(
            delivery_reservation_path(root, kind),
            raw,
            root=root,
            root_identity=capture_root_identity(root),
            temporary_path=pending,
        )
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery reservation could not be updated"
        ) from exc
    persisted = _load_delivery_reservation(root, kind)
    if persisted is None or persisted[1] != raw:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: updated delivery reservation differs"
        )
    return raw


def _write_delivery_reservation(
    root: Path, kind: str, authorization: dict[str, Any]
) -> bytes:
    for candidate in sorted(DELIVERY_RESERVATION_KINDS):
        _discard_unissued_transaction_temps(root, candidate)
    if any(
        _load_delivery_reservation(root, candidate) is not None
        for candidate in DELIVERY_RESERVATION_KINDS
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: another delivery reservation is active"
        )
    reservation_id = authorization["reservation_id"]
    value = {
        "authorization": authorization,
        "kind": kind,
        "progress": {},
        "receipt": None,
        "reservation_id": reservation_id,
        "reservation_version": DELIVERY_RESERVATION_VERSION,
    }
    raw = _reservation_bytes(value)
    if len(raw) > MAX_DELIVERY_RESERVATION_BYTES:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: delivery reservation exceeds bounded limit"
        )
    path = delivery_reservation_path(root, kind)
    pending = delivery_reservation_pending_path(root, kind)
    root_identity = capture_root_identity(root)
    try:
        write_bytes_atomic(
            path,
            raw,
            root=root,
            root_identity=root_identity,
            temporary_path=pending,
        )
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery reservation could not be persisted"
        ) from exc
    persisted = _load_delivery_reservation(root, kind)
    if persisted is None or persisted[1] != raw:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: persisted delivery reservation differs"
        )
    return raw


def _remove_delivery_reservation(
    root: Path, kind: str, expected_raw: bytes
) -> None:
    loaded = _load_delivery_reservation(root, kind)
    if loaded is None or loaded[1] != expected_raw:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery reservation changed"
        )
    try:
        removed = unlink_regular_file_no_follow(
            delivery_reservation_path(root, kind), root
        )
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery reservation could not be consumed"
        ) from exc
    if not removed:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery reservation vanished"
        )
    _remove_reserved_transaction_leaf(
        root, delivery_reservation_pending_path(root, kind)
    )


def _require_delivery_reservation(
    root: Path, kind: str, authorization: dict[str, Any]
) -> tuple[dict[str, Any], bytes]:
    assert_no_pending_delivery_reservations(root, allow_kind=kind)
    loaded = _load_delivery_reservation(root, kind)
    if loaded is None:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: delivery authorization has no active reservation"
        )
    value, raw = loaded
    _require_current_authorization(authorization, value["authorization"])
    return value, raw


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
    root: Path, target: str
) -> tuple[list[str], dict[str, str], dict[str, bytes]]:
    # Capture once, validate those exact bytes, and authorize only bytes from
    # the validated capture.  No live review path is read after this point.
    try:
        _, authority = capture_validated_package_snapshot(
            root, validate_mutable=False
        )
        contract = contract_from_dict(authority.contract, strict=True)
    except (ArchiveSecurityError, TypeError, ValueError) as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-FILE-SET-MISMATCH: sealed review authority is invalid"
        ) from exc
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
        if item != "RESEARCH.md" or item in authority.sealed_bytes
    )
    hashes: dict[str, str] = {}
    contents: dict[str, bytes] = {}
    for item in files:
        data = authority.sealed_bytes.get(item)
        if data is None:
            raise ReceiptValidationError(
                f"SGV-DELIVERY-FILE-SET-MISMATCH: missing review file {item}"
            )
        if not data:
            raise ReceiptValidationError(
                f"SGV-DELIVERY-FILE-SET-MISMATCH: empty review file {item}"
            )
        hashes[item] = hashlib.sha256(data).hexdigest()
        contents[item] = data
    return files, hashes, contents


def _review_stage_description(
    root: Path,
    reservation_id: str,
    files: list[str],
    hashes: dict[str, str],
    contents: dict[str, bytes],
) -> dict[str, Any]:
    stage_path = (
        root.resolve(strict=False).parent
        / f".{root.name}.review-delivery-{reservation_id}"
    ).resolve(strict=False)
    return {
        "absolute_path": str(stage_path),
        "files": [
            {"bytes": len(contents[name]), "name": name, "sha256": hashes[name]}
            for name in files
        ],
        "stage_version": DELIVERY_STAGE_VERSION,
    }


def _final_stage_description(
    root: Path, reservation_id: str, archive_bytes: bytes
) -> dict[str, Any]:
    stage_path = (
        root.resolve(strict=False).parent
        / f".{root.name}.final-delivery-{reservation_id}"
    ).resolve(strict=False)
    return {
        "absolute_path": str(stage_path),
        "files": [
            {
                "bytes": len(archive_bytes),
                "name": "final-artifacts.zip",
                "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            }
        ],
        "stage_version": DELIVERY_STAGE_VERSION,
    }


def _require_current_review_reservation(
    root: Path,
    reservation: dict[str, Any],
    *,
    target: str | None = None,
    force: bool | None = None,
) -> tuple[list[str], dict[str, str], dict[str, bytes]]:
    authorization = reservation["authorization"]
    _, state, _ = _load_delivery_authority(root)
    files, hashes, contents = _review_material(root, authorization["target"])
    stage = _review_stage_description(
        root, reservation["reservation_id"], files, hashes, contents
    )
    expected = _review_authorization(
        root,
        state,
        target=authorization["target"],
        force=authorization["force"],
        reservation_id=reservation["reservation_id"],
        authorized_at=authorization["authorized_at"],
        files=files,
        hashes=hashes,
        stage=stage,
    )
    _require_current_authorization(authorization, expected)
    if target is not None and authorization["target"] != target:
        raise ReceiptValidationError(
            "SGV-DELIVERY-TARGET-MISMATCH: runtime target differs from authorization"
        )
    if force is not None and authorization["force"] is not force:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: runtime force mode differs from authorization"
        )
    return files, hashes, contents


def _require_current_final_reservation(
    root: Path,
    reservation: dict[str, Any],
    *,
    target: str | None = None,
    force: bool | None = None,
) -> tuple[dict[str, Any], bytes]:
    authorization = reservation["authorization"]
    _, state, _ = _load_delivery_authority(root)
    archive_result, archive_bytes = require_archive_result_with_bytes(
        root, authorization["archive_identity"]["absolute_path"]
    )
    stage = _final_stage_description(
        root, reservation["reservation_id"], archive_bytes
    )
    expected = _final_authorization(
        root,
        state,
        target=authorization["target"],
        force=authorization["force"],
        reservation_id=reservation["reservation_id"],
        authorized_at=authorization["authorized_at"],
        archive_result=archive_result,
        stage=stage,
    )
    _require_current_authorization(authorization, expected)
    if target is not None and authorization["target"] != target:
        raise ReceiptValidationError(
            "SGV-DELIVERY-TARGET-MISMATCH: runtime target differs from authorization"
        )
    if force is not None and authorization["force"] is not force:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: runtime force mode differs from authorization"
        )
    return archive_result, archive_bytes


def _stage_marker_bytes(authorization: dict[str, Any]) -> bytes:
    return _reservation_bytes(
        {
            "package_root_identity": authorization["package_root_identity"],
            "reservation_id": authorization["reservation_id"],
            "stage_version": DELIVERY_STAGE_VERSION,
        }
    )


def _review_stage_path(authorization: dict[str, Any]) -> Path:
    return Path(authorization["stage"]["absolute_path"])


def _review_stage_pending_leaf(name: str) -> str:
    return f".{name}.pending"


def _create_review_stage(
    root: Path,
    authorization: dict[str, Any],
    contents: dict[str, bytes],
) -> None:
    _validate_review_stage_description(root, authorization)
    stage = _review_stage_path(authorization)
    try:
        os.mkdir(stage, 0o700)
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage could not be created"
        ) from exc
    identity = capture_root_identity(stage)
    marker = stage / _STAGE_MARKER
    try:
        write_bytes_atomic(
            marker,
            _stage_marker_bytes(authorization),
            root=stage,
            root_identity=identity,
            temporary_path=stage / _review_stage_pending_leaf(_STAGE_MARKER),
        )
        for record in authorization["stage"]["files"]:
            name = record["name"]
            write_bytes_atomic(
                stage / name,
                contents[name],
                root=stage,
                root_identity=identity,
                temporary_path=stage / _review_stage_pending_leaf(name),
            )
        _validate_review_stage(root, authorization)
    except Exception:
        try:
            _cleanup_review_stage(root, authorization)
        except Exception:
            pass
        raise


def _stage_entries(stage: Path) -> dict[str, os.stat_result]:
    try:
        stage_stat = stage.lstat()
        if (
            not stat.S_ISDIR(stage_stat.st_mode)
            or stat.S_ISLNK(stage_stat.st_mode)
            or is_reparse_point(stage_stat)
        ):
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: review stage is not a regular directory"
            )
        with os.scandir(stage) as iterator:
            return {
                entry.name: entry.stat(follow_symlinks=False) for entry in iterator
            }
    except ReceiptValidationError:
        raise
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage cannot be inspected"
        ) from exc


def _validate_review_stage(
    root: Path, authorization: dict[str, Any]
) -> list[Path]:
    _validate_review_stage_description(root, authorization)
    stage = _review_stage_path(authorization)
    entries = _stage_entries(stage)
    expected_names = {_STAGE_MARKER} | set(authorization["files"])
    if set(entries) != expected_names:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage inventory differs"
        )
    identity = capture_root_identity(stage)
    try:
        marker = read_regular_file_no_follow(
            stage / _STAGE_MARKER,
            stage,
            max_bytes=4096,
            root_identity=identity,
        )
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage marker is unsafe"
        ) from exc
    if marker != _stage_marker_bytes(authorization):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage marker differs"
        )
    paths: list[Path] = []
    for record in authorization["stage"]["files"]:
        path = stage / record["name"]
        try:
            data = read_regular_file_no_follow(
                path,
                stage,
                max_bytes=16 * 1024 * 1024,
                root_identity=identity,
            )
        except OSError as exc:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: staged review file is unsafe"
            ) from exc
        if (
            len(data) != record["bytes"]
            or hashlib.sha256(data).hexdigest() != record["sha256"]
        ):
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: staged review file bytes differ"
            )
        paths.append(path)
    return paths


def _cleanup_review_stage(root: Path, authorization: dict[str, Any]) -> None:
    _validate_review_stage_description(root, authorization)
    stage = _review_stage_path(authorization)
    if not os.path.lexists(stage):
        return
    entries = _stage_entries(stage)
    expected = {_STAGE_MARKER} | set(authorization["files"])
    pending = {_review_stage_pending_leaf(name) for name in expected}
    if not set(entries) <= expected | pending:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: foreign files occupy the review stage"
        )
    identity = capture_root_identity(stage)
    marker_path = stage / _STAGE_MARKER
    marker_exists = os.path.lexists(marker_path)
    if marker_exists:
        try:
            marker = read_regular_file_no_follow(
                marker_path,
                stage,
                max_bytes=4096,
                root_identity=identity,
            )
        except OSError as exc:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: review stage marker is unsafe"
            ) from exc
        if marker != _stage_marker_bytes(authorization):
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: foreign review stage marker"
            )
    elif any(name in entries for name in authorization["files"]):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: unmarked review stage contains files"
        )
    cleanup_order = sorted(name for name in entries if name != _STAGE_MARKER)
    if _STAGE_MARKER in entries:
        cleanup_order.append(_STAGE_MARKER)
    for name in cleanup_order:
        try:
            removed = unlink_regular_file_no_follow(
                stage / name, stage, root_identity=identity
            )
        except OSError as exc:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: review stage cleanup is unsafe"
            ) from exc
        if not removed:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: review stage entry vanished"
            )
    if capture_root_identity(stage) != identity:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage identity changed"
        )
    try:
        os.rmdir(stage)
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: review stage could not be removed"
        ) from exc


def _create_final_stage(
    root: Path, authorization: dict[str, Any], archive_bytes: bytes
) -> None:
    _validate_final_stage_description(root, authorization)
    stage = Path(authorization["stage"]["absolute_path"])
    try:
        os.mkdir(stage, 0o700)
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: final stage could not be created"
        ) from exc
    identity = capture_root_identity(stage)
    try:
        write_bytes_atomic(
            stage / _STAGE_MARKER,
            _stage_marker_bytes(authorization),
            root=stage,
            root_identity=identity,
            temporary_path=stage / _review_stage_pending_leaf(_STAGE_MARKER),
        )
        write_bytes_atomic(
            stage / "final-artifacts.zip",
            archive_bytes,
            root=stage,
            root_identity=identity,
            temporary_path=stage
            / _review_stage_pending_leaf("final-artifacts.zip"),
        )
        _validate_final_stage(root, authorization)
    except Exception:
        try:
            _cleanup_final_stage(root, authorization)
        except Exception:
            pass
        raise


def _validate_final_stage(root: Path, authorization: dict[str, Any]) -> Path:
    _validate_final_stage_description(root, authorization)
    stage = Path(authorization["stage"]["absolute_path"])
    entries = _stage_entries(stage)
    if set(entries) != {_STAGE_MARKER, "final-artifacts.zip"}:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: final stage inventory differs"
        )
    identity = capture_root_identity(stage)
    try:
        marker = read_regular_file_no_follow(
            stage / _STAGE_MARKER,
            stage,
            max_bytes=4096,
            root_identity=identity,
        )
        archive_bytes = read_regular_file_no_follow(
            stage / "final-artifacts.zip",
            stage,
            max_bytes=96 * 1024 * 1024,
            root_identity=identity,
        )
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: final stage is unsafe"
        ) from exc
    record = authorization["stage"]["files"][0]
    if (
        marker != _stage_marker_bytes(authorization)
        or len(archive_bytes) != record["bytes"]
        or hashlib.sha256(archive_bytes).hexdigest() != record["sha256"]
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: final stage bytes differ"
        )
    return stage / "final-artifacts.zip"


def _cleanup_final_stage(root: Path, authorization: dict[str, Any]) -> None:
    _validate_final_stage_description(root, authorization)
    stage = Path(authorization["stage"]["absolute_path"])
    if not os.path.lexists(stage):
        return
    entries = _stage_entries(stage)
    expected = {_STAGE_MARKER, "final-artifacts.zip"}
    pending = {_review_stage_pending_leaf(name) for name in expected}
    if not set(entries) <= expected | pending:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: foreign files occupy the final stage"
        )
    identity = capture_root_identity(stage)
    marker_path = stage / _STAGE_MARKER
    if os.path.lexists(marker_path):
        try:
            marker = read_regular_file_no_follow(
                marker_path,
                stage,
                max_bytes=4096,
                root_identity=identity,
            )
        except OSError as exc:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: final stage marker is unsafe"
            ) from exc
        if marker != _stage_marker_bytes(authorization):
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: foreign final stage marker"
            )
    elif "final-artifacts.zip" in entries:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: unmarked final stage contains an archive"
        )
    cleanup_order = sorted(name for name in entries if name != _STAGE_MARKER)
    if _STAGE_MARKER in entries:
        cleanup_order.append(_STAGE_MARKER)
    for name in cleanup_order:
        try:
            removed = unlink_regular_file_no_follow(
                stage / name, stage, root_identity=identity
            )
        except OSError as exc:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: final stage cleanup is unsafe"
            ) from exc
        if not removed:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: final stage entry vanished"
            )
    if capture_root_identity(stage) != identity:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: final stage identity changed"
        )
    try:
        os.rmdir(stage)
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: final stage could not be removed"
        ) from exc


def final_delivery_file(
    root: str | Path,
    *,
    target: str,
    authorization: dict[str, Any],
    force: bool = False,
) -> str:
    package_root = Path(root)
    with package_operation_lock(package_root):
        reservation, _ = _require_delivery_reservation(
            package_root, "final-artifacts", authorization
        )
        _require_current_final_reservation(
            package_root, reservation, target=target, force=force
        )
        if reservation["receipt"] is not None or reservation["progress"]:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: final transport is already recorded"
            )
        _validate_final_stage(package_root, authorization)
        # Do not expose the mutable transport pathname as an egress API.  The
        # actual send boundary is send_final_delivery(), which keeps verified
        # bytes authoritative until the child transport consumes them.
        return "final-artifacts.zip"


def review_delivery_files(
    root: str | Path,
    *,
    target: str,
    authorization: dict[str, Any],
    force: bool = False,
) -> list[str]:
    package_root = Path(root)
    with package_operation_lock(package_root):
        reservation, _ = _require_delivery_reservation(
            package_root, "review-md-files", authorization
        )
        _require_current_review_reservation(
            package_root, reservation, target=target, force=force
        )
        if reservation["receipt"] is not None:
            return []
        _validate_review_stage(package_root, authorization)
        return [
            name
            for name in authorization["files"]
            if name not in reservation["progress"]
        ]


def _persist_delivery_progress(
    root: Path,
    kind: str,
    reservation: dict[str, Any],
    reservation_raw: bytes,
    *,
    item: str,
    message_id: str,
) -> tuple[dict[str, Any], bytes]:
    current = reservation["progress"].get(item)
    if current is not None:
        if current["message_id"] != message_id:
            raise ReceiptValidationError(
                "SGV-DELIVERY-MESSAGE-ID-MISMATCH: item already has a different message id"
            )
        return reservation, reservation_raw
    updated = dict(reservation)
    updated["progress"] = dict(reservation["progress"])
    updated["progress"][item] = {
        "message_id": message_id,
        "sent_at": now_rfc3339_z_seconds(),
    }
    raw = _replace_delivery_reservation(
        root, kind, reservation_raw, updated
    )
    return updated, raw


def send_review_delivery(
    root: str | Path,
    *,
    target: str,
    authorization: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    package_root = Path(root)
    kind = "review-md-files"
    with package_operation_lock(package_root):
        reservation, raw = _require_delivery_reservation(
            package_root, kind, authorization
        )
        _require_current_review_reservation(
            package_root, reservation, target=target, force=force
        )
        if reservation["receipt"] is not None:
            return {
                "progress": reservation["progress"],
                "reservation_id": reservation["reservation_id"],
                "status": "record_required",
            }
        _validate_review_stage(package_root, authorization)
        stage = Path(authorization["stage"]["absolute_path"])
        records = {
            record["name"]: record for record in authorization["stage"]["files"]
        }
        for name in authorization["files"]:
            if name in reservation["progress"]:
                continue
            record = records[name]
            message_id = _run_transport_file(
                stage / name,
                stage,
                target=target,
                logical_name=name,
                reservation_id=reservation["reservation_id"],
                expected_bytes=record["bytes"],
                expected_sha256=record["sha256"],
            )
            reservation, raw = _persist_delivery_progress(
                package_root,
                kind,
                reservation,
                raw,
                item=name,
                message_id=message_id,
            )
        return {
            "progress": reservation["progress"],
            "reservation_id": reservation["reservation_id"],
            "status": "record_required",
        }


def send_final_delivery(
    root: str | Path,
    *,
    target: str,
    authorization: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    package_root = Path(root)
    kind = "final-artifacts"
    with package_operation_lock(package_root):
        reservation, raw = _require_delivery_reservation(
            package_root, kind, authorization
        )
        _require_current_final_reservation(
            package_root, reservation, target=target, force=force
        )
        if reservation["receipt"] is not None or "archive" in reservation["progress"]:
            return {
                "progress": reservation["progress"],
                "reservation_id": reservation["reservation_id"],
                "status": "record_required",
            }
        stage_file = _validate_final_stage(package_root, authorization)
        record = authorization["stage"]["files"][0]
        message_id = _run_transport_file(
            stage_file,
            stage_file.parent,
            target=target,
            logical_name="final-artifacts.zip",
            reservation_id=reservation["reservation_id"],
            expected_bytes=record["bytes"],
            expected_sha256=record["sha256"],
        )
        reservation, _ = _persist_delivery_progress(
            package_root,
            kind,
            reservation,
            raw,
            item="archive",
            message_id=message_id,
        )
        return {
            "progress": reservation["progress"],
            "reservation_id": reservation["reservation_id"],
            "status": "record_required",
        }


def record_review_delivery_progress(
    root: str | Path,
    *,
    file: str,
    message_id: str,
    authorization: dict[str, Any],
) -> dict[str, Any]:
    if not _valid_message_id(message_id):
        raise ReceiptValidationError(
            "SGV-DELIVERY-MESSAGE-ID-MISMATCH: review message id is invalid"
        )
    package_root = Path(root)
    with package_operation_lock(package_root):
        reservation, raw = _require_delivery_reservation(
            package_root, "review-md-files", authorization
        )
        _require_current_review_reservation(package_root, reservation)
        if reservation["receipt"] is not None:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: receipt publication already started"
            )
        if file not in authorization["files"]:
            raise ReceiptValidationError(
                "SGV-DELIVERY-FILE-SET-MISMATCH: progress file is not authorized"
            )
        _validate_review_stage(package_root, authorization)
        reservation, _ = _persist_delivery_progress(
            package_root,
            "review-md-files",
            reservation,
            raw,
            item=file,
            message_id=message_id,
        )
        return {
            "file": file,
            "message_id": message_id,
            "reservation_id": reservation["reservation_id"],
            "recorded": True,
        }


def show_delivery_reservation(root: str | Path, *, kind: str) -> dict[str, Any]:
    package_root = Path(root)
    with package_operation_lock(package_root):
        loaded = _load_delivery_reservation(package_root, kind)
        if loaded is None:
            _discard_unissued_transaction_temps(package_root, kind)
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: no active delivery reservation"
            )
        reservation, _ = loaded
        if kind == "review-md-files":
            _require_current_review_reservation(package_root, reservation)
        else:
            _require_current_final_reservation(package_root, reservation)
        transport_complete = (
            set(reservation["progress"])
            == set(reservation["authorization"]["files"])
            if kind == "review-md-files"
            else "archive" in reservation["progress"]
        )
        result = {
            "authorization": reservation["authorization"],
            "progress": reservation["progress"],
            "status": (
                "record_required"
                if reservation["receipt"] is not None or transport_complete
                else "send_pending"
            ),
        }
        if reservation["receipt"] is not None:
            result["receipt"] = reservation["receipt"]
        return result


def cancel_delivery_reservation(
    root: str | Path,
    *,
    kind: str,
    authorization: dict[str, Any],
    confirm_not_sent: bool,
) -> dict[str, Any]:
    if confirm_not_sent is not True:
        raise ReceiptValidationError(
            "SGV-DELIVERY-SEND-PENDING: cancellation requires explicit confirmation that no send occurred"
        )
    package_root = Path(root)
    with package_operation_lock(package_root):
        reservation, raw = _require_delivery_reservation(
            package_root, kind, authorization
        )
        if reservation["receipt"] is not None:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: transport is already recorded and cannot be cancelled"
            )
        if reservation["progress"]:
            raise ReceiptValidationError(
                "SGV-DELIVERY-SEND-PENDING: durable transport progress exists and cannot be cancelled"
            )
        if kind == "review-md-files":
            _cleanup_review_stage(package_root, authorization)
        else:
            _cleanup_final_stage(package_root, authorization)
        _remove_reserved_transaction_leaf(
            package_root, delivery_receipt_pending_path(package_root, kind)
        )
        _remove_delivery_reservation(package_root, kind, raw)
        return {
            "cancelled": True,
            "kind": kind,
            "reservation_id": reservation["reservation_id"],
        }


def check_review_delivery(
    root: str | Path, *, target: str, force: bool = False
) -> DeliveryCheck:
    package_root = Path(root)
    with package_operation_lock(package_root):
        contract, state, store = _load_delivery_authority(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            kind = "review-md-files"
            assert_no_pending_delivery_reservations(
                package_root, allow_kind=kind
            )
            path = package_root / "out/review-md-files-delivery-receipt.json"
            if force:
                assert_runtime_mutable(
                    package_root, allow_delivery_reservation=kind
                )
                _assert_replaceable_receipt_leaf(path, package_root)
            files, hashes, contents = _review_material(package_root, target)
            reservation = _load_delivery_reservation(package_root, kind)
            if not force and os.path.lexists(path):
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
                if reservation is not None:
                    value, raw = reservation
                    stored = value["authorization"]
                    if receipt["reservation_id"] != value["reservation_id"]:
                        raise ReceiptValidationError(
                            "SGV-DELIVERY-SEND-PENDING: a newer review send is reserved"
                        )
                    _require_current_authorization(
                        stored,
                        _review_authorization(
                            package_root,
                            state,
                            target=target,
                            force=stored.get("force"),
                            reservation_id=value["reservation_id"],
                            authorized_at=stored.get("authorized_at"),
                            files=files,
                            hashes=hashes,
                            stage=_review_stage_description(
                                package_root,
                                value["reservation_id"],
                                files,
                                hashes,
                                contents,
                            ),
                        ),
                    )
                    _cleanup_review_stage(package_root, stored)
                    _remove_reserved_transaction_leaf(
                        package_root,
                        delivery_receipt_pending_path(package_root, kind),
                    )
                    _remove_delivery_reservation(package_root, kind, raw)
                return DeliveryCheck(receipt=receipt, authorization=None)
            if reservation is not None:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-SEND-PENDING: review transport is already reserved"
                )
            assert_runtime_mutable(package_root)
            reservation_id = uuid.uuid4().hex
            authorized_at = now_rfc3339_z_seconds()
            stage = _review_stage_description(
                package_root, reservation_id, files, hashes, contents
            )
            authorization = _review_authorization(
                package_root,
                state,
                target=target,
                force=force,
                reservation_id=reservation_id,
                authorized_at=authorized_at,
                files=files,
                hashes=hashes,
                stage=stage,
            )
            reservation_raw = _write_delivery_reservation(
                package_root, kind, authorization
            )
            try:
                _create_review_stage(package_root, authorization, contents)
            except Exception:
                try:
                    _remove_delivery_reservation(
                        package_root, kind, reservation_raw
                    )
                except Exception:
                    pass
                raise
            return DeliveryCheck(receipt=None, authorization=authorization)


def _publish_reserved_receipt(
    root: Path,
    kind: str,
    path: Path,
    receipt: dict[str, Any],
    *,
    force: bool,
) -> None:
    raw = _canonical_receipt_bytes(receipt)
    if len(raw) > MAX_DELIVERY_RECEIPT_BYTES:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: receipt exceeds the bounded receipt limit"
        )
    if os.path.lexists(path):
        try:
            current = read_receipt(path, root)
        except (OSError, ValueError) as exc:
            raise ReceiptValidationError(
                "SGV-DELIVERY-RECEIPT-INVALID: existing receipt is unsafe"
            ) from exc
        if current == receipt:
            _remove_reserved_transaction_leaf(
                root, delivery_receipt_pending_path(root, kind)
            )
            return
        if not force:
            raise ReceiptValidationError(
                "SGV-DELIVERY-RECEIPT-INVALID: a different receipt already exists"
            )
    pending = delivery_receipt_pending_path(root, kind)
    _remove_reserved_transaction_leaf(root, pending)
    try:
        write_bytes_atomic(
            path,
            raw,
            root=root,
            root_identity=capture_root_identity(root),
            temporary_path=pending,
        )
    except OSError as exc:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: receipt publication failed"
        ) from exc
    persisted = read_receipt(path, root)
    if persisted != receipt:
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: persisted receipt differs"
        )


def _persist_receipt_intent(
    root: Path,
    kind: str,
    reservation: dict[str, Any],
    reservation_raw: bytes,
    receipt: dict[str, Any],
) -> tuple[dict[str, Any], bytes]:
    existing = reservation["receipt"]
    if existing is not None:
        if _canonical_receipt_bytes(existing) != _canonical_receipt_bytes(receipt):
            raise ReceiptValidationError(
                "SGV-DELIVERY-MESSAGE-ID-MISMATCH: recorded transport identity differs"
            )
        return reservation, reservation_raw
    updated = dict(reservation)
    updated["receipt"] = receipt
    raw = _replace_delivery_reservation(
        root, kind, reservation_raw, updated
    )
    return updated, raw


def _idempotent_review_receipt(
    root: Path,
    path: Path,
    *,
    state: State,
    target: str,
    authorization: dict[str, Any],
    message_ids: list[str],
) -> dict[str, Any] | None:
    if not os.path.lexists(path):
        return None
    receipt = read_receipt(path, root)
    validate_review_receipt(
        receipt,
        state=state,
        target=target,
        hashes=authorization.get("hashes"),
    )
    if (
        receipt["reservation_id"] != authorization.get("reservation_id")
        or receipt["files"] != authorization.get("files")
        or receipt["message_ids"] != message_ids
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: completed receipt differs from authorization"
        )
    return receipt


def record_review_delivery(
    root: str | Path,
    *,
    target: str,
    message_ids: list[str] | None,
    authorization: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    package_root = Path(root)
    with package_operation_lock(package_root):
        contract, state, store = _load_delivery_authority(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            kind = "review-md-files"
            path = package_root / "out/review-md-files-delivery-receipt.json"
            loaded = _load_delivery_reservation(package_root, kind)
            if loaded is None:
                _discard_unissued_transaction_temps(package_root, kind)
                supplied = list(message_ids or [])
                completed = _idempotent_review_receipt(
                    package_root,
                    path,
                    state=state,
                    target=target,
                    authorization=authorization,
                    message_ids=supplied,
                )
                if completed is not None:
                    return completed
                raise ReceiptValidationError(
                    "SGV-DELIVERY-SEND-PENDING: delivery authorization has no active reservation"
                )
            assert_runtime_mutable(
                package_root, allow_delivery_reservation=kind
            )
            reservation, reservation_raw = _require_delivery_reservation(
                package_root, kind, authorization
            )
            files, hashes, contents = _review_material(package_root, target)
            _require_current_authorization(
                authorization,
                _review_authorization(
                    package_root,
                    state,
                    target=target,
                    force=force,
                    reservation_id=reservation["reservation_id"],
                    authorized_at=authorization.get("authorized_at"),
                    files=files,
                    hashes=hashes,
                    stage=_review_stage_description(
                        package_root,
                        reservation["reservation_id"],
                        files,
                        hashes,
                        contents,
                    ),
                ),
            )
            progress = reservation["progress"]
            supplied = list(message_ids or [])
            if reservation["receipt"] is not None:
                effective_message_ids = list(
                    reservation["receipt"].get("message_ids", [])
                )
                if supplied and supplied != effective_message_ids:
                    raise ReceiptValidationError(
                        "SGV-DELIVERY-MESSAGE-ID-MISMATCH: supplied ids differ from recorded receipt intent"
                    )
            elif supplied:
                _validate_review_stage(package_root, authorization)
                effective_message_ids = supplied
                if any(
                    name in progress
                    and progress[name]["message_id"] != message_id
                    for name, message_id in zip(
                        files, effective_message_ids, strict=False
                    )
                ):
                    raise ReceiptValidationError(
                        "SGV-DELIVERY-MESSAGE-ID-MISMATCH: supplied ids differ from durable progress"
                    )
            else:
                _validate_review_stage(package_root, authorization)
                effective_message_ids = [
                    progress[name]["message_id"]
                    for name in files
                    if name in progress
                ]
            if (
                len(effective_message_ids) != len(files)
                or not all(_valid_message_id(item) for item in effective_message_ids)
            ):
                raise ReceiptValidationError(
                    "SGV-DELIVERY-MESSAGE-ID-MISMATCH: one message id is required per review file"
                )
            receipt = dict(reservation["receipt"] or {}) or {
                "contract_revision": state.contract_revision,
                "contract_sha256": state.contract_sha256,
                "files": files,
                "goal_id": state.goal_id,
                "hashes": hashes,
                "kind": "review-md-files",
                "message_ids": effective_message_ids,
                "ok": True,
                "pack_version": "review_pack_v2",
                "reservation_id": reservation["reservation_id"],
                "sent": True,
                "sent_at": authorization["authorized_at"],
                "target": target,
            }
            validate_review_receipt(
                receipt, state=state, target=target, hashes=hashes
            )
            reservation, reservation_raw = _persist_receipt_intent(
                package_root,
                kind,
                reservation,
                reservation_raw,
                receipt,
            )
            _publish_reserved_receipt(
                package_root, kind, path, receipt, force=force
            )
            _cleanup_review_stage(package_root, authorization)
            _remove_delivery_reservation(
                package_root, kind, reservation_raw
            )
            return receipt


def require_final_delivery_authority(
    root: str | Path, *, target: str, archive: str | Path
) -> dict[str, Any]:
    package_root = Path(root)
    with package_operation_lock(package_root):
        contract, _, store = _load_delivery_authority(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            kind = "final-artifacts"
            assert_no_pending_delivery_reservations(
                package_root, allow_kind=kind
            )
            delivery = contract.delivery.data
            if not delivery_receipt_required(delivery) or not delivery.get("items"):
                raise ReceiptValidationError(
                    "SGV-DELIVERY-NOT-REQUIRED: final receipt policy is not required"
                )
            if delivery.get("target") != target:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-TARGET-MISMATCH: target differs from contract"
                )
            try:
                return require_archive_result(package_root, archive)
            except ValueError as exc:
                raise ReceiptValidationError(str(exc)) from exc


def check_final_delivery(
    root: str | Path,
    *,
    target: str,
    archive: str | Path,
    force: bool = False,
) -> DeliveryCheck:
    package_root = Path(root)
    with package_operation_lock(package_root):
        contract, state, store = _load_delivery_authority(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            kind = "final-artifacts"
            assert_no_pending_delivery_reservations(
                package_root, allow_kind=kind
            )
            delivery = contract.delivery.data
            if not delivery_receipt_required(delivery) or not delivery.get("items"):
                raise ReceiptValidationError(
                    "SGV-DELIVERY-NOT-REQUIRED: final receipt policy is not required"
                )
            if delivery.get("target") != target:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-TARGET-MISMATCH: target differs from contract"
                )
            try:
                archive_result, archive_bytes = require_archive_result_with_bytes(
                    package_root, archive
                )
            except ValueError as exc:
                raise ReceiptValidationError(str(exc)) from exc
            path = package_root / "out/final-artifacts-delivery-receipt.json"
            if force:
                # Force is an explicit resend authorization, not permission to
                # bypass target/archive validation or terminal immutability.
                assert_runtime_mutable(
                    package_root, allow_delivery_reservation=kind
                )
                _assert_replaceable_receipt_leaf(path, package_root)
            reservation = _load_delivery_reservation(package_root, kind)
            if not force and os.path.lexists(path):
                try:
                    receipt = read_receipt(path, package_root)
                    validate_final_receipt(
                        receipt,
                        state=state,
                        target=target,
                        archive_result=archive_result,
                    )
                except (OSError, ValueError) as exc:
                    raise ReceiptValidationError(
                        f"SGV-DELIVERY-RECEIPT-INVALID: {exc}"
                    ) from exc
                if reservation is not None:
                    value, raw = reservation
                    stored = value["authorization"]
                    if receipt["reservation_id"] != value["reservation_id"]:
                        raise ReceiptValidationError(
                            "SGV-DELIVERY-SEND-PENDING: a newer final send is reserved"
                        )
                    _require_current_authorization(
                        stored,
                        _final_authorization(
                            package_root,
                            state,
                            target=target,
                            force=stored.get("force"),
                            reservation_id=value["reservation_id"],
                            authorized_at=stored.get("authorized_at"),
                            archive_result=archive_result,
                            stage=_final_stage_description(
                                package_root,
                                value["reservation_id"],
                                archive_bytes,
                            ),
                        ),
                    )
                    _cleanup_final_stage(package_root, stored)
                    _remove_reserved_transaction_leaf(
                        package_root,
                        delivery_receipt_pending_path(package_root, kind),
                    )
                    _remove_delivery_reservation(package_root, kind, raw)
                return DeliveryCheck(receipt=receipt, authorization=None)
            if reservation is not None:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-SEND-PENDING: final transport is already reserved"
                )
            assert_runtime_mutable(package_root)
            reservation_id = uuid.uuid4().hex
            authorized_at = now_rfc3339_z_seconds()
            stage = _final_stage_description(
                package_root, reservation_id, archive_bytes
            )
            authorization = _final_authorization(
                package_root,
                state,
                target=target,
                force=force,
                reservation_id=reservation_id,
                authorized_at=authorized_at,
                archive_result=archive_result,
                stage=stage,
            )
            reservation_raw = _write_delivery_reservation(
                package_root, kind, authorization
            )
            try:
                _create_final_stage(package_root, authorization, archive_bytes)
            except Exception:
                try:
                    _remove_delivery_reservation(
                        package_root, kind, reservation_raw
                    )
                except Exception:
                    pass
                raise
            return DeliveryCheck(receipt=None, authorization=authorization)


def _idempotent_final_receipt(
    root: Path,
    path: Path,
    *,
    state: State,
    target: str,
    authorization: dict[str, Any],
    message_id: str,
    archive_result: dict[str, Any],
) -> dict[str, Any] | None:
    if not os.path.lexists(path):
        return None
    receipt = read_receipt(path, root)
    validate_final_receipt(
        receipt,
        state=state,
        target=target,
        archive_result=archive_result,
    )
    if (
        receipt["reservation_id"] != authorization.get("reservation_id")
        or receipt["message_id"] != message_id
    ):
        raise ReceiptValidationError(
            "SGV-DELIVERY-RECEIPT-INVALID: completed receipt differs from authorization"
        )
    return receipt


def record_final_delivery(
    root: str | Path,
    *,
    target: str,
    archive: str | Path,
    message_id: str | None,
    authorization: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    package_root = Path(root)
    with package_operation_lock(package_root):
        contract, state, store = _load_delivery_authority(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            kind = "final-artifacts"
            try:
                archive_result, archive_bytes = require_archive_result_with_bytes(
                    package_root, archive
                )
            except ValueError as exc:
                raise ReceiptValidationError(str(exc)) from exc
            path = package_root / "out/final-artifacts-delivery-receipt.json"
            loaded = _load_delivery_reservation(package_root, kind)
            if loaded is None:
                if not _valid_message_id(message_id):
                    raise ReceiptValidationError(
                        "SGV-DELIVERY-MESSAGE-ID-MISMATCH: final message id is invalid"
                    )
                _discard_unissued_transaction_temps(package_root, kind)
                completed = _idempotent_final_receipt(
                    package_root,
                    path,
                    state=state,
                    target=target,
                    authorization=authorization,
                    message_id=message_id,
                    archive_result=archive_result,
                )
                if completed is not None:
                    return completed
                raise ReceiptValidationError(
                    "SGV-DELIVERY-SEND-PENDING: delivery authorization has no active reservation"
                )
            assert_runtime_mutable(
                package_root, allow_delivery_reservation=kind
            )
            reservation, reservation_raw = _require_delivery_reservation(
                package_root, kind, authorization
            )
            effective_message_id = message_id
            durable_message_id = None
            if reservation["receipt"] is not None:
                durable_message_id = reservation["receipt"].get("message_id")
            elif "archive" in reservation["progress"]:
                durable_message_id = reservation["progress"]["archive"].get(
                    "message_id"
                )
            if effective_message_id is None:
                effective_message_id = durable_message_id
            elif (
                durable_message_id is not None
                and effective_message_id != durable_message_id
            ):
                raise ReceiptValidationError(
                    "SGV-DELIVERY-MESSAGE-ID-MISMATCH: supplied id differs from durable transport progress"
                )
            if not _valid_message_id(effective_message_id):
                raise ReceiptValidationError(
                    "SGV-DELIVERY-MESSAGE-ID-MISMATCH: final message id is invalid"
                )
            delivery = contract.delivery.data
            if not delivery_receipt_required(delivery) or not delivery.get("items"):
                raise ReceiptValidationError(
                    "SGV-DELIVERY-NOT-REQUIRED: final receipt policy is not required"
                )
            if delivery.get("target") != target:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-TARGET-MISMATCH: target differs from contract"
                )
            _require_current_authorization(
                authorization,
                _final_authorization(
                    package_root,
                    state,
                    target=target,
                    force=force,
                    reservation_id=reservation["reservation_id"],
                    authorized_at=authorization.get("authorized_at"),
                    archive_result=archive_result,
                    stage=_final_stage_description(
                        package_root,
                        reservation["reservation_id"],
                        archive_bytes,
                    ),
                ),
            )
            if reservation["receipt"] is None:
                _validate_final_stage(package_root, authorization)
            elif reservation["receipt"].get("message_id") != effective_message_id:
                raise ReceiptValidationError(
                    "SGV-DELIVERY-MESSAGE-ID-MISMATCH: supplied id differs from recorded receipt intent"
                )
            receipt = dict(reservation["receipt"] or {}) or {
                "archive": archive_result["archive_identity"]["absolute_path"],
                "contract_revision": state.contract_revision,
                "contract_sha256": state.contract_sha256,
                "goal_id": state.goal_id,
                "hash": archive_result["archive_sha256"],
                "kind": "final-artifacts",
                "message_id": effective_message_id,
                "ok": True,
                "reservation_id": reservation["reservation_id"],
                "sent": True,
                "sent_at": authorization["authorized_at"],
                "target": target,
            }
            validate_final_receipt(
                receipt,
                state=state,
                target=target,
                archive_result=archive_result,
            )
            reservation, reservation_raw = _persist_receipt_intent(
                package_root,
                kind,
                reservation,
                reservation_raw,
                receipt,
            )
            _publish_reserved_receipt(
                package_root, kind, path, receipt, force=force
            )
            _cleanup_final_stage(package_root, authorization)
            _remove_delivery_reservation(
                package_root, kind, reservation_raw
            )
            return receipt


def read_receipt(path: Path, root: Path) -> dict[str, Any]:
    try:
        raw = read_regular_file_no_follow(
            path, root, max_bytes=MAX_DELIVERY_RECEIPT_BYTES
        )
        value = strict_json_loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReceiptValidationError(
            "receipt JSON is malformed or exceeds the bounded receipt limit"
        ) from exc
    if not isinstance(value, dict):
        raise ReceiptValidationError("receipt must be an object")
    canonical = _canonical_receipt_bytes(value)
    if raw != canonical:
        raise ReceiptValidationError("receipt JSON is not canonical")
    return value
