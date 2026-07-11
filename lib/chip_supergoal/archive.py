from __future__ import annotations

from dataclasses import dataclass
import base64
import binascii
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Iterable
import uuid
import zipfile

from .events import canonical_json_value_bytes, strict_json_loads
from .portable import (
    MUTABLE_PATH_NAMES,
    MUTABLE_PATHS,
    RootIdentity,
    UnsafeFileError,
    capture_root_identity,
    is_reparse_point,
    iter_tree_no_follow,
    logical_mode,
    package_operation_lock,
    package_operation_lock_path,
    read_regular_file_no_follow,
    unlink_regular_file_no_follow,
    write_bytes_atomic,
)
from .state import State, assert_runtime_mutable


ARCHIVE_MANIFEST_NAME = "ARCHIVE-MANIFEST.json"
ARCHIVE_RESULT_PATH = "out/final-artifacts-manifest.json"
ARCHIVE_PUBLICATION_INTENT_PATH = "runtime/archive-publication.json"
ARCHIVE_RESULT_VERSION = "1.0"
ARCHIVE_MANIFEST_VERSION = "1.0"
MAX_SOURCE_ENTRIES = 4096
MAX_SOURCE_FILE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_AGGREGATE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_RESULT_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_SOURCE_AGGREGATE_BYTES + (16 * 1024 * 1024)
ZIP32_MAX_ENTRIES = 65_535
ZIP32_MAX_NAME_BYTES = 65_535
ZIP32_MAX_FILE_BYTES = 0xFFFFFFFF
ZIP32_MAX_OFFSET = 0xFFFFFFFF
PUBLICATION_INTENT_VERSION = "1.0"
MAX_PUBLICATION_INTENT_BYTES = 48 * 1024 * 1024
_PUBLICATION_PHASES = frozenset({"intent", "staged", "destination", "result"})
_PUBLICATION_INTENT_FIELDS = frozenset(
    {
        "backup",
        "contract_revision",
        "contract_sha256",
        "destination_path",
        "destination_root_identity",
        "generation",
        "goal_id",
        "intent_version",
        "new_result",
        "package_fingerprint",
        "package_path",
        "package_root_identity",
        "phase",
        "prior_result",
        "result_path",
        "stage",
    }
)
EXCLUDED_SOURCE_PATHS = frozenset(
    {
        "runtime/state.lock",
        "runtime/operation.lock",
        ARCHIVE_PUBLICATION_INTENT_PATH,
        "runtime/review-delivery-reservation.json",
        "runtime/final-delivery-reservation.json",
        "runtime/review-delivery-reservation.pending.json",
        "runtime/final-delivery-reservation.pending.json",
        "out/review-md-files-delivery-receipt.json",
        "out/final-artifacts-delivery-receipt.json",
        "out/review-md-files-delivery-receipt.pending.json",
        "out/final-artifacts-delivery-receipt.pending.json",
        ARCHIVE_RESULT_PATH,
    }
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{32,}"),
    re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)
_SHA256 = re.compile(r"[a-f0-9]{64}")
_RESULT_FIELDS = frozenset(
    {
        "archive_bytes",
        "archive_identity",
        "archive_manifest_sha256",
        "archive_result_version",
        "archive_sha256",
        "contract_revision",
        "contract_sha256",
        "delivery_items",
        "goal_id",
        "package_fingerprint",
        "snapshot_files",
        "source_manifest_sha256",
    }
)
_RECORD_FIELDS = frozenset({"bytes", "mode", "path", "sha256"})
_SOURCE_MANIFEST_FIELDS = frozenset(
    {
        "artifacts",
        "contract_sha256",
        "manifest_version",
        "mutable_paths",
        "package_fingerprint",
        "source_contract_sha256",
    }
)
_WINDOWS_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
    | {f"com{number}" for number in ("¹", "²", "³")}
    | {f"lpt{number}" for number in ("¹", "²", "³")}
)


class ArchiveSecurityError(ValueError):
    pass


@dataclass(frozen=True)
class CapturedFile:
    path: str
    data: bytes
    mode: str
    stat_signature: tuple[int, int, int, int]

    def record(self) -> dict[str, Any]:
        return {
            "bytes": len(self.data),
            "mode": self.mode,
            "path": self.path,
            "sha256": sha256_bytes(self.data),
        }


@dataclass(frozen=True)
class SnapshotAuthority:
    contract_raw: bytes
    contract: dict[str, Any]
    manifest_raw: bytes
    manifest: dict[str, Any]
    sealed_records: dict[str, dict[str, Any]]
    sealed_bytes: dict[str, bytes]


class _Utf8ZipInfo(zipfile.ZipInfo):
    """Keep the UTF-8 flag deterministic even for ASCII-only member names."""

    def _encodeFilenameFlags(self) -> tuple[bytes, int]:  # noqa: N802 - zipfile hook
        return self.filename.encode("utf-8"), self.flag_bits | 0x800


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
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


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(_absolute(path))))


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([_path_key(path), _path_key(root)]) == _path_key(root)
    except ValueError:
        return False


def _is_portable_archive_path(path: object) -> bool:
    """Return whether *path* has one unambiguous meaning on POSIX and Windows."""

    if not isinstance(path, str) or not path or "\x00" in path:
        return False
    if any(0xD800 <= ord(character) <= 0xDFFF for character in path):
        return False
    if path.startswith("/") or path.endswith("/") or "\\" in path or "//" in path:
        return False
    components = path.split("/")
    for component in components:
        has_forbidden_character = any(
            ord(character) < 32
            or ord(character) == 0x7F
            or character in '<>"|?*'
            for character in component
        )
        if (
            not component
            or component in {".", ".."}
            or ":" in component
            or component.endswith((".", " "))
            or has_forbidden_character
        ):
            return False
        stem = component.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED_STEMS:
            return False
    return True


def _require_portable_archive_path(path: object) -> str:
    if not _is_portable_archive_path(path):
        raise ArchiveSecurityError(
            f"SGV-PACKAGE-ZIP-TRAVERSAL: nonportable archive path {path!r}"
        )
    return path


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(getattr(value, "st_dev", 0)),
        int(getattr(value, "st_ino", 0)),
        int(value.st_size),
        int(getattr(value, "st_mtime_ns", int(value.st_mtime * 1_000_000_000))),
    )


def _classify_unsafe(exc: BaseException) -> str:
    if isinstance(exc, UnsafeFileError):
        if exc.kind == "symlink":
            return "SGV-PACKAGE-SYMLINK"
        if exc.kind == "limit":
            return "SGV-PACKAGE-ARCHIVE-LIMIT"
        if exc.kind == "escape":
            return "SGV-PACKAGE-PATH-ESCAPE"
    return "SGV-PACKAGE-SPECIAL-FILE"


def _assert_regular_root(root: Path) -> None:
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise ArchiveSecurityError("SGV-PACKAGE-PATH-ESCAPE: package root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_ISLNK(root_stat.st_mode)
        or is_reparse_point(root_stat)
    ):
        raise ArchiveSecurityError("SGV-PACKAGE-SYMLINK: package root is an alias")


def _assert_no_alias_chain(path: Path, *, include_leaf: bool) -> None:
    current = path if include_leaf else path.parent
    while True:
        if os.path.lexists(current):
            try:
                current_stat = current.lstat()
            except OSError as exc:
                raise ArchiveSecurityError(
                    f"SGV-PACKAGE-PATH-ESCAPE: cannot inspect {current}"
                ) from exc
            if stat.S_ISLNK(current_stat.st_mode) or is_reparse_point(current_stat):
                raise ArchiveSecurityError(
                    f"SGV-PACKAGE-SYMLINK: reparse or symlink alias {current}"
                )
        parent = current.parent
        if parent == current:
            break
        current = parent


def _prepare_paths(
    root: str | Path, archive: str | Path, result: str | Path
) -> tuple[Path, Path, Path]:
    package_root = _absolute(root)
    destination = _absolute(archive)
    result_path = _absolute(result)
    _assert_regular_root(package_root)
    expected_result = package_root / ARCHIVE_RESULT_PATH
    if _path_key(result_path) != _path_key(expected_result):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-PATH-ESCAPE: archive result must be "
            f"{ARCHIVE_RESULT_PATH}"
        )
    if _is_within(destination, package_root):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT: archive destination must be external"
        )
    reserved_sibling = package_operation_lock_path(package_root)
    if _path_key(destination) == _path_key(reserved_sibling):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT: archive destination is a reserved package control path"
        )
    # Resolving existing aliases catches case/junction/symlink paths that are
    # lexically external but physically enter the package.
    try:
        if _is_within(destination.resolve(strict=False), package_root.resolve(strict=True)):
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT: archive destination aliases package root"
            )
    except OSError as exc:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-PATH-ESCAPE: archive destination cannot be resolved"
        ) from exc
    if _path_key(destination) == _path_key(result_path):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT: archive and result paths alias"
        )
    _assert_no_alias_chain(destination, include_leaf=True)
    _assert_no_alias_chain(result_path, include_leaf=True)
    if os.path.lexists(destination):
        current = destination.lstat()
        if not stat.S_ISREG(current.st_mode):
            raise ArchiveSecurityError(
                "SGV-PACKAGE-SPECIAL-FILE: archive destination is not a regular file"
            )
    if os.path.lexists(result_path):
        current = result_path.lstat()
        if not stat.S_ISREG(current.st_mode):
            raise ArchiveSecurityError(
                "SGV-PACKAGE-SPECIAL-FILE: archive result is not a regular file"
            )
    return package_root, destination, result_path


def _bounded_snapshot_inventory(
    root: Path,
    *,
    root_identity: RootIdentity | None = None,
) -> list[tuple[Path, os.stat_result]]:
    """Stat the complete tree within fixed bounds before reading any content."""

    if root_identity is None:
        root_identity = capture_root_identity(root)
    elif capture_root_identity(root) != root_identity:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-PATH-ESCAPE: package root identity changed before enumeration"
        )
    entries: list[tuple[Path, os.stat_result]] = []
    aggregate = 0
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for path, stat_result in iter_tree_no_follow(
            root, max_entries=MAX_SOURCE_ENTRIES
        ):
            entries.append((path, stat_result))
            if len(entries) > MAX_SOURCE_ENTRIES:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ARCHIVE-LIMIT: source entry count exceeds 4096"
                )
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(stat_result.st_mode) or is_reparse_point(stat_result):
                raise ArchiveSecurityError(f"SGV-PACKAGE-SYMLINK: {relative}")
            if stat.S_ISDIR(stat_result.st_mode):
                continue
            if not stat.S_ISREG(stat_result.st_mode):
                raise ArchiveSecurityError(f"SGV-PACKAGE-SPECIAL-FILE: {relative}")
            if relative in EXCLUDED_SOURCE_PATHS:
                continue
            _require_portable_archive_path(relative)
            folded = relative.casefold()
            if folded in seen or folded == ARCHIVE_MANIFEST_NAME.casefold():
                raise ArchiveSecurityError(
                    f"SGV-PACKAGE-CASE-COLLISION: {relative}"
                )
            seen.add(folded)
            size = int(stat_result.st_size)
            if size < 0 or size > MAX_SOURCE_FILE_BYTES:
                raise ArchiveSecurityError(
                    f"SGV-PACKAGE-ARCHIVE-LIMIT: source file exceeds 16 MiB: {relative}"
                )
            aggregate += size
            if aggregate > MAX_SOURCE_AGGREGATE_BYTES:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ARCHIVE-LIMIT: source aggregate exceeds 64 MiB"
                )
            records.append(
                {
                    "bytes": size,
                    "mode": logical_mode(relative),
                    "path": relative,
                    "sha256": "0" * 64,
                }
            )
    except ArchiveSecurityError:
        raise
    except (OSError, UnsafeFileError) as exc:
        raise ArchiveSecurityError(
            f"{_classify_unsafe(exc)}: package enumeration failed"
        ) from exc
    records.sort(key=lambda item: item["path"])
    placeholder_manifest = _canonical_json_bytes(
        {
            "archive_manifest_version": ARCHIVE_MANIFEST_VERSION,
            "files": records,
            "secret_scan": "passed",
        }
    )
    _assert_zip32_member_projection(
        [(item["path"], item["bytes"]) for item in records],
        len(placeholder_manifest),
    )
    if capture_root_identity(root) != root_identity:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-PATH-ESCAPE: package root identity changed during enumeration"
        )
    return entries


def _capture_snapshot(
    root: Path, *, root_identity: RootIdentity | None = None
) -> tuple[list[CapturedFile], dict[str, os.stat_result]]:
    if root_identity is None:
        root_identity = capture_root_identity(root)
    captures: list[CapturedFile] = []
    seen: set[str] = set()
    observed: dict[str, os.stat_result] = {}
    captured_aggregate = 0
    entries = _bounded_snapshot_inventory(root, root_identity=root_identity)
    for path, stat_result in entries:
        relative = path.relative_to(root).as_posix()
        if stat.S_ISDIR(stat_result.st_mode):
            continue
        if relative in EXCLUDED_SOURCE_PATHS:
            continue
        _require_portable_archive_path(relative)
        folded = relative.casefold()
        if folded in seen or folded == ARCHIVE_MANIFEST_NAME.casefold():
            raise ArchiveSecurityError(f"SGV-PACKAGE-CASE-COLLISION: {relative}")
        seen.add(folded)
        try:
            current_stat = path.lstat()
            if (
                not stat.S_ISREG(current_stat.st_mode)
                or stat.S_ISLNK(current_stat.st_mode)
                or is_reparse_point(current_stat)
                or int(current_stat.st_size) > MAX_SOURCE_FILE_BYTES
                or _stat_signature(current_stat)[2:]
                != _stat_signature(stat_result)[2:]
            ):
                raise ArchiveSecurityError(
                    f"SGV-PACKAGE-ZIP-HASH-MISMATCH: source changed before read: {relative}"
                )
            data = read_regular_file_no_follow(
                path,
                root,
                max_bytes=MAX_SOURCE_FILE_BYTES,
                root_identity=root_identity,
            )
        except ArchiveSecurityError:
            raise
        except (OSError, UnsafeFileError) as exc:
            raise ArchiveSecurityError(
                f"{_classify_unsafe(exc)}: verified read rejected {relative}"
            ) from exc
        if len(data) != int(stat_result.st_size):
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-ZIP-HASH-MISMATCH: source size changed during read: {relative}"
            )
        captured_aggregate += len(data)
        if captured_aggregate > MAX_SOURCE_AGGREGATE_BYTES:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ARCHIVE-LIMIT: captured aggregate exceeds 64 MiB"
            )
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise ArchiveSecurityError(f"SGV-PACKAGE-SECRET: {relative}")
        captures.append(
            CapturedFile(
                path=relative,
                data=data,
                mode=logical_mode(relative),
                stat_signature=_stat_signature(current_stat),
            )
        )
        observed[relative] = current_stat
    captures.sort(key=lambda item: item.path)
    if not captures or not any(item.path == "MANIFEST.json" for item in captures):
        raise ArchiveSecurityError("SGV-PACKAGE-MISSING-MANIFEST: source manifest is missing")
    if sum(item.path == "MANIFEST.json" for item in captures) != 1:
        raise ArchiveSecurityError("SGV-PACKAGE-CASE-COLLISION: duplicate source manifest")
    _assert_snapshot_unchanged(root, captures, root_identity=root_identity)
    return captures, observed


def _assert_snapshot_unchanged(
    root: Path,
    captures: Iterable[CapturedFile],
    *,
    root_identity: RootIdentity | None = None,
) -> None:
    if root_identity is None:
        root_identity = capture_root_identity(root)
    elif capture_root_identity(root) != root_identity:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-PATH-ESCAPE: package root identity changed during snapshot"
        )
    expected = {item.path: item.stat_signature for item in captures}
    current: dict[str, tuple[int, int, int, int]] = {}
    try:
        for path, stat_result in iter_tree_no_follow(
            root, max_entries=MAX_SOURCE_ENTRIES
        ):
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(stat_result.st_mode) or is_reparse_point(stat_result):
                raise ArchiveSecurityError(f"SGV-PACKAGE-SYMLINK: {relative}")
            if stat.S_ISDIR(stat_result.st_mode):
                continue
            if not stat.S_ISREG(stat_result.st_mode):
                raise ArchiveSecurityError(f"SGV-PACKAGE-SPECIAL-FILE: {relative}")
            if relative not in EXCLUDED_SOURCE_PATHS:
                current[relative] = _stat_signature(path.lstat())
    except ArchiveSecurityError:
        raise
    except OSError as exc:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-SPECIAL-FILE: package changed during snapshot"
        ) from exc
    if current != expected:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: package changed during snapshot"
        )
    if capture_root_identity(root) != root_identity:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-PATH-ESCAPE: package root identity changed after snapshot"
        )


def _captured_json_object(
    captures: dict[str, CapturedFile], relative: str, *, compact: bool = False
) -> tuple[bytes, dict[str, Any]]:
    captured = captures.get(relative)
    if captured is None:
        raise ArchiveSecurityError(
            f"SGV-PACKAGE-MANIFEST-HASH: captured {relative} is missing"
        )
    try:
        value = strict_json_loads(captured.data)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ArchiveSecurityError(
            f"SGV-PACKAGE-MANIFEST-HASH: captured {relative} is malformed"
        ) from exc
    expected = (
        canonical_json_value_bytes(value) + b"\n"
        if compact
        else _canonical_json_bytes(value)
    )
    if not isinstance(value, dict) or captured.data != expected:
        raise ArchiveSecurityError(
            f"SGV-PACKAGE-MANIFEST-HASH: captured {relative} is not canonical"
        )
    return captured.data, value


def _snapshot_authority(
    captures: Iterable[CapturedFile], *, validate_mutable: bool
) -> SnapshotAuthority:
    """Validate authority from captured bytes, never from mutable source paths."""

    ordered = list(captures)
    by_path = {item.path: item for item in ordered}
    if len(by_path) != len(ordered):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: captured inventory contains duplicates"
        )
    for item in ordered:
        _require_portable_archive_path(item.path)

    manifest_raw, manifest = _captured_json_object(by_path, "MANIFEST.json")
    contract_raw, contract = _captured_json_object(
        by_path, "CONTRACT.json", compact=True
    )
    if (
        set(manifest) != _SOURCE_MANIFEST_FIELDS
        or manifest.get("manifest_version") != "1.1"
        or manifest.get("mutable_paths") != [dict(item) for item in MUTABLE_PATHS]
        or not isinstance(manifest.get("artifacts"), list)
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: captured source manifest shape is invalid"
        )
    for field in (
        "source_contract_sha256",
        "contract_sha256",
        "package_fingerprint",
    ):
        if not isinstance(manifest.get(field), str) or not _SHA256.fullmatch(
            manifest[field]
        ):
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-MANIFEST-HASH: captured manifest {field} is invalid"
            )

    sealed_records: dict[str, dict[str, Any]] = {}
    ordered_paths: list[str] = []
    for record in manifest["artifacts"]:
        if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-MANIFEST-HASH: captured sealed record shape is invalid"
            )
        path = _require_portable_archive_path(record.get("path"))
        if path in sealed_records or path in MUTABLE_PATH_NAMES or path == "MANIFEST.json":
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-MANIFEST-HASH: invalid sealed path {path}"
            )
        if (
            type(record.get("bytes")) is not int
            or record["bytes"] < 0
            or record.get("mode") != logical_mode(path)
            or not isinstance(record.get("sha256"), str)
            or not _SHA256.fullmatch(record["sha256"])
        ):
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-MANIFEST-HASH: invalid sealed record {path}"
            )
        sealed_records[path] = record
        ordered_paths.append(path)
    if ordered_paths != sorted(ordered_paths):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: sealed records are not ordered"
        )

    captured_sealed = {
        path
        for path in by_path
        if path != "MANIFEST.json" and path not in MUTABLE_PATH_NAMES
    }
    if set(sealed_records) != captured_sealed:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: captured sealed inventory differs from MANIFEST.json"
        )
    captured_mutable = set(by_path) - captured_sealed - {"MANIFEST.json"}
    if not captured_mutable <= MUTABLE_PATH_NAMES:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: captured mutable inventory is not registered"
        )
    for path, record in sealed_records.items():
        if by_path[path].record() != record:
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-MANIFEST-HASH: captured sealed bytes mismatch {path}"
            )
    if manifest["contract_sha256"] != sha256_bytes(contract_raw):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: captured contract identity mismatch"
        )
    joined = "\n".join(
        f"{item['path']} {item['sha256']} {item['bytes']} {item['mode']}"
        for item in manifest["artifacts"]
    )
    if manifest["package_fingerprint"] != sha256_bytes(joined.encode()):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: captured package fingerprint mismatch"
        )

    authority = SnapshotAuthority(
        contract_raw=contract_raw,
        contract=contract,
        manifest_raw=manifest_raw,
        manifest=manifest,
        sealed_records=sealed_records,
        sealed_bytes={path: by_path[path].data for path in sealed_records},
    )
    if validate_mutable:
        _validate_captured_package(ordered)
    return authority


def capture_validated_package_snapshot(
    root: str | Path,
    *,
    root_identity: RootIdentity | None = None,
    validate_mutable: bool = True,
) -> tuple[tuple[CapturedFile, ...], SnapshotAuthority]:
    """Capture once and validate the exact bytes returned to the caller.

    Callers that combine this authority with another transaction must hold the
    package operation lock for the duration of that transaction.  The helper
    deliberately never re-reads live package paths after validation.
    """

    package_root = _absolute(root)
    identity = root_identity or capture_root_identity(package_root)
    captures, _ = _capture_snapshot(package_root, root_identity=identity)
    authority = _snapshot_authority(captures, validate_mutable=validate_mutable)
    if not validate_mutable:
        _validate_captured_package(captures, include_mutable=False)
    return tuple(captures), authority


def _validate_captured_package(
    captures: Iterable[CapturedFile], *, include_mutable: bool = True
) -> None:
    """Run package semantics over an exact, alias-free captured materialization."""

    from . import portable as portable_runtime
    from .validate import _validate_package_mode

    try:
        with tempfile.TemporaryDirectory(prefix="chip-supergoal-capture-") as temporary:
            snapshot_root = Path(temporary)
            for item in captures:
                portable_runtime.write_bytes_atomic(
                    snapshot_root / item.path,
                    item.data,
                    root=snapshot_root,
                )
            diagnostics = _validate_package_mode(
                snapshot_root, include_mutable=include_mutable
            )
    except ArchiveSecurityError:
        raise
    except Exception as exc:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: captured package revalidation failed"
        ) from exc
    if diagnostics:
        codes = ", ".join(sorted({item.code for item in diagnostics}))
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: captured package semantics failed: "
            f"{codes}"
        )


def _manifest_for(captures: Iterable[CapturedFile]) -> dict[str, Any]:
    return {
        "archive_manifest_version": ARCHIVE_MANIFEST_VERSION,
        "files": [item.record() for item in captures],
        "secret_scan": "passed",
    }


def _assert_zipfile_compatibility() -> None:
    """Fail closed if CPython's private filename hook contract changes."""

    hook = zipfile.ZipInfo._encodeFilenameFlags
    try:
        parameters = list(inspect.signature(hook).parameters)
        ascii_probe = zipfile.ZipInfo("a.txt")
        unicode_probe = zipfile.ZipInfo("ü.txt")
        ascii_encoded, ascii_flags = hook(ascii_probe)
        unicode_encoded, unicode_flags = hook(unicode_probe)
        probe_stream = io.BytesIO()
        with zipfile.ZipFile(
            probe_stream,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=False,
        ) as probe_zip:
            probe_zip.writestr(_Utf8ZipInfo("probe.txt"), b"")
        probe_bytes = probe_stream.getvalue()
        central = probe_bytes.find(b"PK\x01\x02")
        local_flags = int.from_bytes(probe_bytes[6:8], "little")
        central_flags = (
            int.from_bytes(probe_bytes[central + 8 : central + 10], "little")
            if central >= 0
            else -1
        )
    except Exception as exc:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: unsupported zipfile filename hook"
        ) from exc
    if (
        sys.version_info[:2] < (3, 11)
        or parameters != ["self"]
        or ascii_encoded != b"a.txt"
        or ascii_flags != 0
        or unicode_encoded != "ü.txt".encode("utf-8")
        or unicode_flags != 0x800
        or local_flags != 0x800
        or central_flags != 0x800
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: incompatible zipfile filename hook"
        )


def _assert_zip32_member_projection(
    source_members: list[tuple[str, int]], manifest_size: int
) -> int:
    if (
        len(source_members) > MAX_SOURCE_ENTRIES
        or len(source_members) + 1 > ZIP32_MAX_ENTRIES
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: ZIP32 entry count exceeded"
        )
    aggregate = sum(size for _, size in source_members)
    if aggregate > MAX_SOURCE_AGGREGATE_BYTES:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: source aggregate exceeds 64 MiB"
        )
    members = list(source_members)
    members.append((ARCHIVE_MANIFEST_NAME, manifest_size))
    local_offset = 0
    central_bytes = 0
    for path, size in members:
        name_bytes = path.encode("utf-8")
        if (
            len(name_bytes) > ZIP32_MAX_NAME_BYTES
            or size > ZIP32_MAX_FILE_BYTES
            or (
                path != ARCHIVE_MANIFEST_NAME
                and size > MAX_SOURCE_FILE_BYTES
            )
            or local_offset > ZIP32_MAX_OFFSET
        ):
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-ARCHIVE-LIMIT: ZIP32 member limit exceeded: {path}"
            )
        local_offset += 30 + len(name_bytes) + size
        central_bytes += 46 + len(name_bytes)
        if local_offset > ZIP32_MAX_OFFSET:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ARCHIVE-LIMIT: ZIP32 local offset exceeded"
            )
    projected = local_offset + central_bytes + 22
    if (
        local_offset > ZIP32_MAX_OFFSET
        or projected > ZIP32_MAX_OFFSET
        or projected > MAX_ARCHIVE_BYTES
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: ZIP32 archive/central offset exceeded"
        )
    return projected


def _assert_zip32_projection(
    captures: Iterable[CapturedFile], archive_manifest_bytes: bytes
) -> int:
    """Return the exact ZIP_STORED projection or reject every ZIP64 boundary."""

    ordered = list(captures)
    return _assert_zip32_member_projection(
        [(item.path, len(item.data)) for item in ordered],
        len(archive_manifest_bytes),
    )


def _zip_info(path: str, mode: str) -> _Utf8ZipInfo:
    info = _Utf8ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.flag_bits = 0x800
    info.external_attr = (stat.S_IFREG | int(mode, 8)) << 16
    info.internal_attr = 0
    info.extra = b""
    info.comment = b""
    return info


def _write_archive(
    stream: io.BufferedRandom,
    captures: list[CapturedFile],
    archive_manifest_bytes: bytes,
) -> None:
    _assert_zipfile_compatibility()
    projected = _assert_zip32_projection(captures, archive_manifest_bytes)
    try:
        with zipfile.ZipFile(
            stream,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=False,
            strict_timestamps=True,
        ) as zipped:
            zipped.comment = b""
            for item in captures:
                zipped.writestr(_zip_info(item.path, item.mode), item.data)
            zipped.writestr(
                _zip_info(ARCHIVE_MANIFEST_NAME, "0644"), archive_manifest_bytes
            )
    except zipfile.LargeZipFile as exc:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: ZIP64 output is forbidden"
        ) from exc
    try:
        actual = stream.tell()
    except (AttributeError, OSError):
        actual = projected
    if actual != projected:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: ZIP32 byte projection mismatch"
        )


def _safe_external_bytes(
    path: Path,
    *,
    expected_bytes: int | None = None,
    root_identity: RootIdentity | None = None,
) -> bytes:
    if root_identity is not None:
        _assert_root_identity(path.parent, root_identity)
    _assert_no_alias_chain(path, include_leaf=True)
    if not os.path.lexists(path):
        raise ArchiveSecurityError(f"SGV-DELIVERY-ARCHIVE-MISSING: {path}")
    try:
        current = path.lstat()
        if not stat.S_ISREG(current.st_mode) or is_reparse_point(current):
            raise UnsafeFileError(path, "external archive is not a regular file")
        size = int(current.st_size)
        if (
            size < 0
            or size > MAX_ARCHIVE_BYTES
        ):
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ARCHIVE-LIMIT: external archive size is invalid"
            )
        if expected_bytes is not None and size != expected_bytes:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ZIP-HASH-MISMATCH: external archive size differs from authority"
            )
        data = read_regular_file_no_follow(
            path,
            path.parent,
            max_bytes=MAX_ARCHIVE_BYTES,
            root_identity=root_identity,
        )
        if len(data) != size:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ZIP-HASH-MISMATCH: external archive changed during read"
            )
        return data
    except ArchiveSecurityError:
        raise
    except (OSError, UnsafeFileError) as exc:
        raise ArchiveSecurityError(
            f"{_classify_unsafe(exc)}: archive is not a verified regular file"
        ) from exc


def _verify_archive_bytes(
    archive_bytes: bytes,
    records: list[dict[str, Any]],
    archive_manifest_bytes: bytes,
) -> dict[str, bytes]:
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: archive readback exceeds fixed cap"
        )
    if len(records) > MAX_SOURCE_ENTRIES:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: archive record count exceeds fixed cap"
        )
    projected = _assert_zip32_member_projection(
        [(item["path"], item["bytes"]) for item in records],
        len(archive_manifest_bytes),
    )
    if len(archive_bytes) != projected:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive size differs from ZIP32 projection"
        )
    expected_names = [item["path"] for item in records] + [ARCHIVE_MANIFEST_NAME]
    expected_data = {item["path"]: item for item in records}
    expected_data[ARCHIVE_MANIFEST_NAME] = {
        "bytes": len(archive_manifest_bytes),
        "mode": "0644",
        "path": ARCHIVE_MANIFEST_NAME,
        "sha256": sha256_bytes(archive_manifest_bytes),
    }
    member_data: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r", allowZip64=False) as zipped:
            infos = zipped.infolist()
            if len(infos) > ZIP32_MAX_ENTRIES:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ARCHIVE-LIMIT: ZIP32 entry count exceeded"
                )
            names = [info.filename for info in infos]
            if names != expected_names or len(names) != len(set(names)):
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ZIP-TRAVERSAL: archive inventory/order mismatch"
                )
            if zipped.comment != b"":
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive comment is not empty"
                )
            for info in infos:
                if (
                    len(info.filename.encode("utf-8")) > ZIP32_MAX_NAME_BYTES
                    or info.header_offset > ZIP32_MAX_OFFSET
                ):
                    raise ArchiveSecurityError(
                        "SGV-PACKAGE-ARCHIVE-LIMIT: ZIP32 name/offset exceeded"
                    )
                if not _is_portable_archive_path(info.filename) or info.is_dir():
                    raise ArchiveSecurityError(
                        f"SGV-PACKAGE-ZIP-TRAVERSAL: {info.filename}"
                    )
                record = expected_data[info.filename]
                if (
                    info.file_size > MAX_SOURCE_FILE_BYTES
                    or info.compress_size > MAX_SOURCE_FILE_BYTES
                ):
                    raise ArchiveSecurityError(
                        f"SGV-PACKAGE-ARCHIVE-LIMIT: archived member too large {info.filename}"
                    )
                expected_mode = stat.S_IFREG | int(record["mode"], 8)
                if (
                    info.compress_type != zipfile.ZIP_STORED
                    or info.date_time != (1980, 1, 1, 0, 0, 0)
                    or info.create_system != 3
                    or info.create_version != 20
                    or info.extract_version != 20
                    or info.flag_bits != 0x800
                    or info.external_attr >> 16 != expected_mode
                    or info.internal_attr != 0
                    or info.extra != b""
                    or info.comment != b""
                ):
                    raise ArchiveSecurityError(
                        f"SGV-PACKAGE-ZIP-HASH-MISMATCH: metadata mismatch {info.filename}"
                    )
                data = zipped.read(info)
                if (
                    info.filename != ARCHIVE_MANIFEST_NAME
                    and any(pattern.search(data) for pattern in SECRET_PATTERNS)
                ):
                    raise ArchiveSecurityError(
                        f"SGV-PACKAGE-SECRET: archived source member {info.filename}"
                    )
                member_data[info.filename] = data
                if (
                    info.file_size != record["bytes"]
                    or info.compress_size != record["bytes"]
                    or info.CRC != (binascii.crc32(data) & 0xFFFFFFFF)
                    or len(data) != record["bytes"]
                    or sha256_bytes(data) != record["sha256"]
                ):
                    raise ArchiveSecurityError(
                        f"SGV-PACKAGE-ZIP-HASH-MISMATCH: content mismatch {info.filename}"
                    )
            if zipped.read(ARCHIVE_MANIFEST_NAME) != archive_manifest_bytes:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive manifest mismatch"
                )
    except ArchiveSecurityError:
        raise
    except (OSError, EOFError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive readback failed"
        ) from exc

    canonical_captures = [
        CapturedFile(
            path=record["path"],
            data=member_data[record["path"]],
            mode=record["mode"],
            stat_signature=(0, 0, record["bytes"], 0),
        )
        for record in records
    ]
    canonical_stream = io.BytesIO()
    _write_archive(canonical_stream, canonical_captures, archive_manifest_bytes)
    if canonical_stream.getvalue() != archive_bytes:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive bytes are not canonical"
        )
    return member_data


def _verify_archive(
    path: Path,
    records: list[dict[str, Any]],
    archive_manifest_bytes: bytes,
    *,
    expected_bytes: int | None = None,
    root_identity: RootIdentity | None = None,
) -> bytes:
    data = _safe_external_bytes(
        path,
        expected_bytes=expected_bytes,
        root_identity=root_identity,
    )
    _verify_archive_bytes(data, records, archive_manifest_bytes)
    return data


def _load_json_authority(
    root: Path,
    relative: str,
    *,
    root_identity: RootIdentity | None = None,
) -> tuple[bytes, dict[str, Any]]:
    try:
        if root_identity is not None:
            _assert_root_identity(root, root_identity)
        path = root / relative
        current = path.lstat()
        if int(current.st_size) > MAX_SOURCE_FILE_BYTES:
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-ARCHIVE-LIMIT: JSON authority too large: {relative}"
            )
        raw = read_regular_file_no_follow(
            path,
            root,
            max_bytes=MAX_SOURCE_FILE_BYTES,
            root_identity=root_identity,
        )
        value = strict_json_loads(raw)
    except ArchiveSecurityError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ArchiveSecurityError(
            f"SGV-PACKAGE-MANIFEST-MALFORMED: invalid {relative}"
        ) from exc
    if not isinstance(value, dict):
        raise ArchiveSecurityError(
            f"SGV-PACKAGE-MANIFEST-SHAPE: {relative} must be an object"
        )
    return raw, value


def _archive_identity(path: Path) -> dict[str, str]:
    return {
        "absolute_path": str(path),
        "filename": path.name,
        "path_format": "windows" if path.drive or path.anchor.startswith("\\\\") else "posix",
    }


def _result_payload(
    destination: Path,
    archive_bytes: bytes,
    records: list[dict[str, Any]],
    archive_manifest_bytes: bytes,
    authority: SnapshotAuthority,
) -> dict[str, Any]:
    contract_raw = authority.contract_raw
    contract = authority.contract
    manifest_raw = authority.manifest_raw
    manifest = authority.manifest
    goal = contract.get("goal")
    delivery = contract.get("delivery")
    if not isinstance(goal, dict) or not isinstance(delivery, dict):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-CONTRACT-MALFORMED: goal/delivery authority is invalid"
        )
    delivery_items = delivery.get("items", [])
    canonical_json_value_bytes(delivery_items)
    return {
        "archive_bytes": len(archive_bytes),
        "archive_identity": _archive_identity(destination),
        "archive_manifest_sha256": sha256_bytes(archive_manifest_bytes),
        "archive_result_version": ARCHIVE_RESULT_VERSION,
        "archive_sha256": sha256_bytes(archive_bytes),
        "contract_revision": contract.get("contract_revision"),
        "contract_sha256": sha256_bytes(contract_raw),
        "delivery_items": delivery_items,
        "goal_id": goal.get("id"),
        "package_fingerprint": manifest.get("package_fingerprint"),
        "snapshot_files": records,
        "source_manifest_sha256": sha256_bytes(manifest_raw),
    }


def _validate_record_list(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or not records:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: snapshot file list is empty"
        )
    if len(records) > MAX_SOURCE_ENTRIES:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: snapshot file count exceeds fixed cap"
        )
    previous = ""
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    aggregate = 0
    for record in records:
        if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ZIP-HASH-MISMATCH: snapshot record shape is invalid"
            )
        path = record.get("path")
        if (
            not _is_portable_archive_path(path)
            or path in EXCLUDED_SOURCE_PATHS
            or path.casefold() == ARCHIVE_MANIFEST_NAME.casefold()
            or path <= previous
            or path.casefold() in seen
        ):
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ZIP-TRAVERSAL: snapshot path/order is invalid"
            )
        if (
            type(record.get("bytes")) is not int
            or record["bytes"] < 0
            or record["bytes"] > MAX_SOURCE_FILE_BYTES
            or record.get("mode") != logical_mode(path)
            or not isinstance(record.get("sha256"), str)
            or not _SHA256.fullmatch(record["sha256"])
        ):
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-ZIP-HASH-MISMATCH: invalid record {path}"
            )
        previous = path
        seen.add(path.casefold())
        normalized.append(record)
        aggregate += record["bytes"]
        if aggregate > MAX_SOURCE_AGGREGATE_BYTES:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ARCHIVE-LIMIT: snapshot aggregate exceeds fixed cap"
            )
    if [item["path"] for item in normalized].count("MANIFEST.json") != 1:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: source MANIFEST.json must occur once"
        )
    return normalized


def _current_sealed_authority(
    root: Path, *, root_identity: RootIdentity | None = None
) -> SnapshotAuthority:
    if root_identity is None:
        root_identity = capture_root_identity(root)
    manifest_raw, manifest = _load_json_authority(
        root, "MANIFEST.json", root_identity=root_identity
    )
    if manifest_raw != _canonical_json_bytes(manifest):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: current MANIFEST.json is not canonical"
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > MAX_SOURCE_ENTRIES:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: current sealed inventory is invalid"
        )
    captures = [
        CapturedFile(
            path="MANIFEST.json",
            data=manifest_raw,
            mode=logical_mode("MANIFEST.json"),
            stat_signature=(0, 0, len(manifest_raw), 0),
        )
    ]
    declared_aggregate = len(manifest_raw)
    try:
        for record in artifacts:
            if not isinstance(record, dict):
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-MANIFEST-HASH: current sealed record is invalid"
                )
            relative = _require_portable_archive_path(record.get("path"))
            declared_bytes = record.get("bytes")
            if (
                type(declared_bytes) is not int
                or declared_bytes < 0
                or declared_bytes > MAX_SOURCE_FILE_BYTES
            ):
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ARCHIVE-LIMIT: sealed artifact size exceeds fixed cap"
                )
            declared_aggregate += declared_bytes
            if declared_aggregate > MAX_SOURCE_AGGREGATE_BYTES:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ARCHIVE-LIMIT: sealed aggregate exceeds fixed cap"
                )
            data = read_regular_file_no_follow(
                root / relative,
                root,
                max_bytes=MAX_SOURCE_FILE_BYTES,
                root_identity=root_identity,
            )
            captures.append(
                CapturedFile(
                    path=relative,
                    data=data,
                    mode=logical_mode(relative),
                    stat_signature=(0, 0, len(data), 0),
                )
            )
    except ArchiveSecurityError:
        raise
    except (OSError, UnsafeFileError) as exc:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: current sealed artifact is unavailable"
        ) from exc
    return _snapshot_authority(captures, validate_mutable=False)


def _bind_archive_to_current_package(
    root: Path,
    records: list[dict[str, Any]],
    members: dict[str, bytes],
    *,
    root_identity: RootIdentity | None = None,
) -> SnapshotAuthority:
    archived_captures = [
        CapturedFile(
            path=record["path"],
            data=members[record["path"]],
            mode=record["mode"],
            stat_signature=(0, 0, record["bytes"], 0),
        )
        for record in records
    ]
    # Validate the archived mutable plane as it existed at capture time. The
    # current package may legitimately advance registered mutable files after
    # a pre-terminal archive, but an attacker may not forge malformed or
    # incomplete archived state/evidence and bless it with a rebuilt result.
    archived = _snapshot_authority(
        archived_captures, validate_mutable=True
    )
    current = _current_sealed_authority(root, root_identity=root_identity)
    if (
        archived.manifest_raw != current.manifest_raw
        or archived.contract_raw != current.contract_raw
        or archived.sealed_records != current.sealed_records
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: archive sealed authority differs from current package"
        )
    archived_records = {record["path"]: record for record in records}
    manifest_record = archived_records.get("MANIFEST.json")
    expected_manifest_record = {
        "bytes": len(current.manifest_raw),
        "mode": logical_mode("MANIFEST.json"),
        "path": "MANIFEST.json",
        "sha256": sha256_bytes(current.manifest_raw),
    }
    if manifest_record != expected_manifest_record:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: archive MANIFEST.json record is not trusted"
        )
    for path, sealed_record in current.sealed_records.items():
        if (
            archived_records.get(path) != sealed_record
            or members.get(path) != current.sealed_bytes[path]
        ):
            raise ArchiveSecurityError(
                f"SGV-PACKAGE-MANIFEST-HASH: archive sealed bytes/record differ for {path}"
            )
    allowed_snapshot_paths = (
        set(current.sealed_records) | {"MANIFEST.json"} | MUTABLE_PATH_NAMES
    )
    if set(archived_records) - allowed_snapshot_paths:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: archive contains unregistered mutable data"
        )
    return current


def archive_publication_intent_path(root: str | Path) -> Path:
    package_root = _absolute(root)
    return package_root / ARCHIVE_PUBLICATION_INTENT_PATH


def _archive_stage_path(destination: str | Path) -> Path:
    path = _absolute(destination)
    return path.parent / f".{path.name}.archive-stage"


def _archive_backup_path(destination: str | Path) -> Path:
    path = _absolute(destination)
    return path.parent / f".{path.name}.archive-backup"


def _publication_atomic_temp_path(
    target: str | Path, generation: str
) -> Path:
    path = _absolute(target)
    if not re.fullmatch(r"[a-f0-9]{32}", generation):
        raise _recovery_required("publication generation is invalid")
    return path.parent / f".{path.name}.txn-{generation}"


def _publication_checkpoint(name: str) -> None:
    """Internal fault-injection seam; production execution is a no-op."""

    del name


def _identity_payload(identity: RootIdentity) -> dict[str, Any]:
    return {
        "file_index_or_inode": identity.file_index_or_inode,
        "platform": identity.platform,
        "volume_or_device": identity.volume_or_device,
    }


def _identity_from_payload(value: object) -> RootIdentity:
    if (
        not isinstance(value, dict)
        or set(value)
        != {"file_index_or_inode", "platform", "volume_or_device"}
        or value.get("platform") not in {"posix", "windows"}
        or type(value.get("volume_or_device")) is not int
        or type(value.get("file_index_or_inode")) is not int
        or value["volume_or_device"] < 0
        or value["file_index_or_inode"] < 0
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED: invalid root identity"
        )
    return RootIdentity(
        value["platform"],
        value["volume_or_device"],
        value["file_index_or_inode"],
    )


def _recovery_required(reason: str) -> ArchiveSecurityError:
    return ArchiveSecurityError(
        f"SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED: {reason}"
    )


def _assert_root_identity(root: Path, expected: RootIdentity) -> None:
    try:
        current = capture_root_identity(root)
    except (OSError, UnsafeFileError) as exc:
        raise _recovery_required(f"trusted root unavailable: {root}") from exc
    if current != expected:
        raise _recovery_required(f"trusted root identity changed: {root}")


def _rooted_optional_bytes(
    path: Path,
    root: Path,
    root_identity: RootIdentity,
    *,
    max_bytes: int,
) -> bytes | None:
    _assert_root_identity(root, root_identity)
    if not os.path.lexists(path):
        _assert_root_identity(root, root_identity)
        return None
    try:
        current = path.lstat()
        if (
            not stat.S_ISREG(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or is_reparse_point(current)
        ):
            raise _recovery_required(f"non-regular transaction material: {path}")
        if int(current.st_size) < 0 or int(current.st_size) > max_bytes:
            raise _recovery_required(f"oversized transaction material: {path}")
        data = read_regular_file_no_follow(
            path,
            root,
            max_bytes=max_bytes,
            root_identity=root_identity,
        )
    except ArchiveSecurityError:
        raise
    except (OSError, UnsafeFileError) as exc:
        raise _recovery_required(f"cannot read transaction material: {path}") from exc
    if len(data) != int(current.st_size):
        raise _recovery_required(f"transaction material changed during read: {path}")
    return data


def _write_verified_rooted(
    path: Path,
    content: bytes,
    root: Path,
    root_identity: RootIdentity,
    *,
    max_bytes: int,
    generation: str,
) -> None:
    try:
        write_bytes_atomic(
            path,
            content,
            root=root,
            root_identity=root_identity,
            temporary_path=_publication_atomic_temp_path(path, generation),
        )
    except UnsafeFileError:
        raise
    except (OSError, ValueError) as exc:
        raise _recovery_required(f"cannot publish transaction material: {path}") from exc
    persisted = _rooted_optional_bytes(
        path, root, root_identity, max_bytes=max_bytes
    )
    if persisted != content:
        raise _recovery_required(f"published transaction bytes differ: {path}")


def _unlink_exact_rooted(
    path: Path,
    expected: bytes,
    root: Path,
    root_identity: RootIdentity,
    *,
    max_bytes: int,
) -> None:
    current = _rooted_optional_bytes(
        path, root, root_identity, max_bytes=max_bytes
    )
    if current is None:
        return
    if current != expected:
        raise _recovery_required(f"foreign bytes replaced transaction material: {path}")
    try:
        unlink_regular_file_no_follow(
            path, root, root_identity=root_identity
        )
    except (OSError, UnsafeFileError) as exc:
        raise _recovery_required(f"cannot remove transaction material: {path}") from exc


def _unlink_owned_atomic_temp(
    target: Path,
    generation: str,
    root: Path,
    root_identity: RootIdentity,
    *,
    expected_identities: set[tuple[int, str]],
    max_bytes: int,
) -> None:
    temporary = _publication_atomic_temp_path(target, generation)
    current = _rooted_optional_bytes(
        temporary,
        root,
        root_identity,
        max_bytes=max_bytes,
    )
    if current is None:
        return
    identity = (len(current), sha256_bytes(current))
    if identity not in expected_identities:
        raise _recovery_required(
            f"foreign bytes occupy generation-owned atomic temporary: {temporary}"
        )
    _unlink_exact_rooted(
        temporary,
        current,
        root,
        root_identity,
        max_bytes=max_bytes,
    )


def _byte_identity(data: bytes) -> tuple[int, str]:
    return len(data), sha256_bytes(data)


def _intent_temp_identities(intent: dict[str, Any]) -> set[tuple[int, str]]:
    phases = ("intent", "staged", "destination", "result")
    current = intent.get("phase")
    if current not in phases:
        raise _recovery_required("publication intent phase is invalid")
    index = phases.index(current)
    candidates = [current]
    if index + 1 < len(phases):
        candidates.append(phases[index + 1])
    identities: set[tuple[int, str]] = set()
    for phase in candidates:
        candidate = dict(intent)
        candidate["phase"] = phase
        identities.add(_byte_identity(_canonical_json_bytes(candidate)))
    return identities


def _intent_atomic_temp_candidates(package_root: Path) -> list[Path]:
    intent_path = archive_publication_intent_path(package_root)
    prefix = f".{intent_path.name}.txn-"
    try:
        return sorted(
            (
                child
                for child in intent_path.parent.iterdir()
                if child.name.startswith(prefix)
            ),
            key=lambda child: child.name,
        )
    except OSError as exc:
        raise _recovery_required(
            "cannot inspect publication-intent atomic temporaries"
        ) from exc


def _cleanup_publication_atomic_temps(
    package_root: Path,
    package_identity: RootIdentity,
    destination: Path,
    destination_identity: RootIdentity,
    intent: dict[str, Any],
    new_result_bytes: bytes,
    old_result_bytes: bytes | None,
) -> None:
    generation = intent["generation"]
    new_archive_identity = {
        (intent["stage"]["bytes"], intent["stage"]["sha256"])
    }
    old_archive_identity: set[tuple[int, str]] = set()
    if intent["backup"]["exists"]:
        old_archive_identity.add(
            (intent["backup"]["bytes"], intent["backup"]["sha256"])
        )
    result_identities = {_byte_identity(new_result_bytes)}
    if old_result_bytes is not None:
        result_identities.add(_byte_identity(old_result_bytes))
    for target, root, identity, expected, limit in (
        (
            archive_publication_intent_path(package_root),
            package_root,
            package_identity,
            _intent_temp_identities(intent),
            MAX_PUBLICATION_INTENT_BYTES,
        ),
        (
            package_root / ARCHIVE_RESULT_PATH,
            package_root,
            package_identity,
            result_identities,
            MAX_ARCHIVE_RESULT_BYTES,
        ),
        (
            destination,
            destination.parent,
            destination_identity,
            new_archive_identity | old_archive_identity,
            MAX_ARCHIVE_BYTES,
        ),
        (
            _archive_stage_path(destination),
            destination.parent,
            destination_identity,
            new_archive_identity,
            MAX_ARCHIVE_BYTES,
        ),
        (
            _archive_backup_path(destination),
            destination.parent,
            destination_identity,
            old_archive_identity,
            MAX_ARCHIVE_BYTES,
        ),
    ):
        _unlink_owned_atomic_temp(
            target,
            generation,
            root,
            identity,
            expected_identities=expected,
            max_bytes=limit,
        )


def _material_record(
    path: Path, data: bytes | None, *, include_data: bool
) -> dict[str, Any]:
    exists = data is not None
    record: dict[str, Any] = {
        "bytes": len(data) if data is not None else 0,
        "exists": exists,
        "sha256": sha256_bytes(data) if data is not None else None,
    }
    if include_data:
        record["data_base64"] = (
            base64.b64encode(data).decode("ascii") if data is not None else None
        )
    else:
        record["path"] = str(path)
    return record


def _new_material_record(path: Path, data: bytes) -> dict[str, Any]:
    return {
        "bytes": len(data),
        "path": str(path),
        "sha256": sha256_bytes(data),
    }


def _new_result_record(payload: dict[str, Any], data: bytes) -> dict[str, Any]:
    return {
        "bytes": len(data),
        "payload": payload,
        "sha256": sha256_bytes(data),
    }


def _build_publication_intent(
    package_root: Path,
    destination: Path,
    result_path: Path,
    package_identity: RootIdentity,
    destination_identity: RootIdentity,
    authority: SnapshotAuthority,
    archive_bytes: bytes,
    result: dict[str, Any],
    result_bytes: bytes,
    prior_archive: bytes | None,
    prior_result: bytes | None,
) -> dict[str, Any]:
    goal = authority.contract.get("goal")
    if not isinstance(goal, dict) or not isinstance(goal.get("id"), str):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-CONTRACT-MALFORMED: goal identity is unavailable"
        )
    return {
        "backup": _material_record(
            _archive_backup_path(destination), prior_archive, include_data=False
        ),
        "contract_revision": authority.contract.get("contract_revision"),
        "contract_sha256": sha256_bytes(authority.contract_raw),
        "destination_path": str(destination),
        "destination_root_identity": _identity_payload(destination_identity),
        "generation": uuid.uuid4().hex,
        "goal_id": goal["id"],
        "intent_version": PUBLICATION_INTENT_VERSION,
        "new_result": _new_result_record(result, result_bytes),
        "package_fingerprint": authority.manifest.get("package_fingerprint"),
        "package_path": str(package_root),
        "package_root_identity": _identity_payload(package_identity),
        "phase": "intent",
        "prior_result": _material_record(
            result_path, prior_result, include_data=True
        ),
        "result_path": str(result_path),
        "stage": _new_material_record(
            _archive_stage_path(destination), archive_bytes
        ),
    }


def _decode_prior_result(record: dict[str, Any]) -> bytes | None:
    encoded = record.get("data_base64")
    if not record.get("exists"):
        if (
            record.get("bytes") != 0
            or record.get("sha256") is not None
            or encoded is not None
        ):
            raise _recovery_required("absent prior result record is inconsistent")
        return None
    if not isinstance(encoded, str):
        raise _recovery_required("prior result bytes are unavailable")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise _recovery_required("prior result encoding is invalid") from exc
    if (
        type(record.get("bytes")) is not int
        or record["bytes"] != len(data)
        or record["bytes"] > MAX_ARCHIVE_RESULT_BYTES
        or not isinstance(record.get("sha256"), str)
        or record["sha256"] != sha256_bytes(data)
    ):
        raise _recovery_required("prior result identity is invalid")
    return data


def _validate_publication_intent(
    package_root: Path,
    intent: object,
    raw: bytes,
) -> tuple[dict[str, Any], bytes, bytes | None]:
    if (
        not isinstance(intent, dict)
        or set(intent) != _PUBLICATION_INTENT_FIELDS
        or intent.get("intent_version") != PUBLICATION_INTENT_VERSION
        or intent.get("phase") not in _PUBLICATION_PHASES
        or not isinstance(intent.get("generation"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", intent["generation"])
        or raw != _canonical_json_bytes(intent)
    ):
        raise _recovery_required("publication intent shape/canonical bytes are invalid")
    recorded_package_value = intent.get("package_path")
    recorded_result_value = intent.get("result_path")
    if (
        not isinstance(recorded_package_value, str)
        or not isinstance(recorded_result_value, str)
        or not isinstance(intent.get("destination_path"), str)
    ):
        raise _recovery_required("publication intent paths are malformed")
    recorded_package = _absolute(recorded_package_value)
    if (
        str(recorded_package) != recorded_package_value
        or recorded_result_value
        != str(recorded_package / ARCHIVE_RESULT_PATH)
    ):
        raise _recovery_required("publication intent historical paths are inconsistent")
    destination = _absolute(intent["destination_path"])
    if str(destination) != intent["destination_path"] or _is_within(
        destination, package_root
    ):
        raise _recovery_required("publication destination is not canonical/external")
    package_identity = _identity_from_payload(intent.get("package_root_identity"))
    if capture_root_identity(package_root) != package_identity:
        raise _recovery_required("package root identity changed")
    destination_identity = _identity_from_payload(
        intent.get("destination_root_identity")
    )
    if capture_root_identity(destination.parent) != destination_identity:
        raise _recovery_required("destination parent identity changed")

    stage = intent.get("stage")
    backup = intent.get("backup")
    new_result = intent.get("new_result")
    prior_result = intent.get("prior_result")
    if (
        not isinstance(stage, dict)
        or set(stage) != {"bytes", "path", "sha256"}
        or stage.get("path") != str(_archive_stage_path(destination))
        or type(stage.get("bytes")) is not int
        or not 0 <= stage["bytes"] <= MAX_ARCHIVE_BYTES
        or not isinstance(stage.get("sha256"), str)
        or not _SHA256.fullmatch(stage["sha256"])
        or not isinstance(backup, dict)
        or set(backup) != {"bytes", "exists", "path", "sha256"}
        or backup.get("path") != str(_archive_backup_path(destination))
        or type(backup.get("exists")) is not bool
        or type(backup.get("bytes")) is not int
        or not 0 <= backup["bytes"] <= MAX_ARCHIVE_BYTES
        or not isinstance(new_result, dict)
        or set(new_result) != {"bytes", "payload", "sha256"}
        or type(new_result.get("bytes")) is not int
        or not 0 <= new_result["bytes"] <= MAX_ARCHIVE_RESULT_BYTES
        or not isinstance(new_result.get("payload"), dict)
        or not isinstance(new_result.get("sha256"), str)
        or not _SHA256.fullmatch(new_result["sha256"])
        or not isinstance(prior_result, dict)
        or set(prior_result)
        != {"bytes", "data_base64", "exists", "sha256"}
        or type(prior_result.get("exists")) is not bool
    ):
        raise _recovery_required("publication material records are invalid")
    if backup["exists"]:
        if (
            not 0 <= backup["bytes"] <= MAX_ARCHIVE_BYTES
            or not isinstance(backup.get("sha256"), str)
            or not _SHA256.fullmatch(backup["sha256"])
        ):
            raise _recovery_required("prior archive record is invalid")
    elif backup["bytes"] != 0 or backup.get("sha256") is not None:
        raise _recovery_required("absent prior archive record is inconsistent")
    result_bytes = _canonical_json_bytes(new_result["payload"])
    if (
        len(result_bytes) != new_result["bytes"]
        or sha256_bytes(result_bytes) != new_result["sha256"]
    ):
        raise _recovery_required("new result payload identity is invalid")
    old_result = _decode_prior_result(prior_result)

    authority = _current_sealed_authority(
        package_root, root_identity=package_identity
    )
    goal = authority.contract.get("goal")
    expected = {
        "contract_revision": authority.contract.get("contract_revision"),
        "contract_sha256": sha256_bytes(authority.contract_raw),
        "goal_id": goal.get("id") if isinstance(goal, dict) else None,
        "package_fingerprint": authority.manifest.get("package_fingerprint"),
    }
    if any(intent.get(key) != value for key, value in expected.items()):
        raise _recovery_required("publication intent package binding is stale")
    if (
        new_result["payload"].get("archive_identity")
        != _archive_identity(destination)
        or new_result["payload"].get("archive_sha256") != stage["sha256"]
        or new_result["payload"].get("archive_bytes") != stage["bytes"]
    ):
        raise _recovery_required("publication intent archive/result binding is invalid")
    return intent, result_bytes, old_result


def _read_publication_intent(
    package_root: Path,
    package_identity: RootIdentity,
) -> tuple[dict[str, Any], bytes, bytes, bytes | None] | None:
    path = archive_publication_intent_path(package_root)
    raw = _rooted_optional_bytes(
        path,
        package_root,
        package_identity,
        max_bytes=MAX_PUBLICATION_INTENT_BYTES,
    )
    if raw is None:
        if _intent_atomic_temp_candidates(package_root):
            raise _recovery_required(
                "orphan publication-intent atomic temporary requires manual recovery"
            )
        return None
    try:
        value = strict_json_loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise _recovery_required("publication intent is malformed") from exc
    intent, new_result, old_result = _validate_publication_intent(
        package_root, value, raw
    )
    _unlink_owned_atomic_temp(
        path,
        intent["generation"],
        package_root,
        package_identity,
        expected_identities=_intent_temp_identities(intent),
        max_bytes=MAX_PUBLICATION_INTENT_BYTES,
    )
    return intent, raw, new_result, old_result


def _write_publication_intent(
    package_root: Path,
    package_identity: RootIdentity,
    intent: dict[str, Any],
) -> bytes:
    raw = _canonical_json_bytes(intent)
    if len(raw) > MAX_PUBLICATION_INTENT_BYTES:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: publication intent exceeds fixed cap"
        )
    _write_verified_rooted(
        archive_publication_intent_path(package_root),
        raw,
        package_root,
        package_identity,
        max_bytes=MAX_PUBLICATION_INTENT_BYTES,
        generation=intent["generation"],
    )
    return raw


def _material_class(
    data: bytes | None,
    *,
    new_hash: str | None,
    old_hash: str | None,
) -> str:
    if data is None:
        return "missing"
    digest = sha256_bytes(data)
    if new_hash is not None and digest == new_hash:
        return "new"
    if old_hash is not None and digest == old_hash:
        return "old"
    return "foreign"


def _cleanup_publication_material(
    package_root: Path,
    package_identity: RootIdentity,
    destination: Path,
    destination_identity: RootIdentity,
    intent: dict[str, Any],
    intent_raw: bytes,
    stage_bytes: bytes | None,
    backup_bytes: bytes | None,
) -> None:
    new_result_bytes = _canonical_json_bytes(intent["new_result"]["payload"])
    old_result_bytes = _decode_prior_result(intent["prior_result"])
    _cleanup_publication_atomic_temps(
        package_root,
        package_identity,
        destination,
        destination_identity,
        intent,
        new_result_bytes,
        old_result_bytes,
    )
    if stage_bytes is not None:
        _unlink_exact_rooted(
            _archive_stage_path(destination),
            stage_bytes,
            destination.parent,
            destination_identity,
            max_bytes=MAX_ARCHIVE_BYTES,
        )
    if backup_bytes is not None:
        _unlink_exact_rooted(
            _archive_backup_path(destination),
            backup_bytes,
            destination.parent,
            destination_identity,
            max_bytes=MAX_ARCHIVE_BYTES,
        )
    # The intent is removed last, after every referenced recovery material.
    _unlink_exact_rooted(
        archive_publication_intent_path(package_root),
        intent_raw,
        package_root,
        package_identity,
        max_bytes=MAX_PUBLICATION_INTENT_BYTES,
    )
    _assert_root_identity(package_root, package_identity)


def _recover_publication_locked(
    package_root: Path,
    *,
    requested_destination: Path | None = None,
    prefer_rollback: bool = False,
) -> dict[str, Any] | None:
    package_identity = capture_root_identity(package_root)
    loaded = _read_publication_intent(package_root, package_identity)
    if loaded is None:
        return None
    intent, intent_raw, new_result_bytes, old_result_bytes = loaded
    destination = _absolute(intent["destination_path"])
    if (
        requested_destination is not None
        and _path_key(destination) != _path_key(requested_destination)
    ):
        raise _recovery_required(
            "pending publication belongs to a different destination"
        )
    destination_identity = _identity_from_payload(
        intent["destination_root_identity"]
    )
    _cleanup_publication_atomic_temps(
        package_root,
        package_identity,
        destination,
        destination_identity,
        intent,
        new_result_bytes,
        old_result_bytes,
    )
    stage_path = _archive_stage_path(destination)
    backup_path = _archive_backup_path(destination)
    result_path = package_root / ARCHIVE_RESULT_PATH
    stage = _rooted_optional_bytes(
        stage_path,
        destination.parent,
        destination_identity,
        max_bytes=MAX_ARCHIVE_BYTES,
    )
    backup = _rooted_optional_bytes(
        backup_path,
        destination.parent,
        destination_identity,
        max_bytes=MAX_ARCHIVE_BYTES,
    )
    current_archive = _rooted_optional_bytes(
        destination,
        destination.parent,
        destination_identity,
        max_bytes=MAX_ARCHIVE_BYTES,
    )
    current_result = _rooted_optional_bytes(
        result_path,
        package_root,
        package_identity,
        max_bytes=MAX_ARCHIVE_RESULT_BYTES,
    )
    if intent["phase"] == "intent":
        # The durable intent is the first publication artifact. While it is in
        # this phase destination/result have not been touched; any stage/backup
        # is merely partial preparation and must be safely abandoned.
        if stage is not None and (
            len(stage) != intent["stage"]["bytes"]
            or sha256_bytes(stage) != intent["stage"]["sha256"]
        ):
            raise _recovery_required(
                "foreign partial stage bytes detected; recovery evidence preserved"
            )
        if intent["backup"]["exists"]:
            if backup is not None and (
                len(backup) != intent["backup"]["bytes"]
                or sha256_bytes(backup) != intent["backup"]["sha256"]
            ):
                raise _recovery_required(
                    "foreign partial backup bytes detected; recovery evidence preserved"
                )
            prior_archive_matches = (
                current_archive is not None
                and len(current_archive) == intent["backup"]["bytes"]
                and sha256_bytes(current_archive) == intent["backup"]["sha256"]
            )
            if not prior_archive_matches:
                if current_archive is not None:
                    raise _recovery_required(
                        "destination changed before staged publication"
                    )
                if backup is None:
                    raise _recovery_required(
                        "prior archive is unavailable before staged publication"
                    )
                _write_verified_rooted(
                    destination,
                    backup,
                    destination.parent,
                    destination_identity,
                    max_bytes=MAX_ARCHIVE_BYTES,
                    generation=intent["generation"],
                )
        else:
            if backup is not None:
                raise _recovery_required(
                    "unexpected partial backup bytes; recovery evidence preserved"
                )
            if current_archive is not None:
                raise _recovery_required(
                    "destination appeared before staged publication"
                )

        if old_result_bytes is not None:
            if current_result is None:
                _write_verified_rooted(
                    result_path,
                    old_result_bytes,
                    package_root,
                    package_identity,
                    max_bytes=MAX_ARCHIVE_RESULT_BYTES,
                    generation=intent["generation"],
                )
            elif current_result != old_result_bytes:
                raise _recovery_required(
                    "archive result changed before staged publication"
                )
        elif current_result is not None:
            raise _recovery_required(
                "archive result appeared before staged publication"
            )

        _cleanup_publication_material(
            package_root,
            package_identity,
            destination,
            destination_identity,
            intent,
            intent_raw,
            stage,
            backup,
        )
        return None

    new_archive_hash = intent["stage"]["sha256"]
    old_archive_hash = intent["backup"]["sha256"]
    new_result_hash = intent["new_result"]["sha256"]
    old_result_hash = intent["prior_result"]["sha256"]
    classes = {
        "archive": _material_class(
            current_archive,
            new_hash=new_archive_hash,
            old_hash=old_archive_hash,
        ),
        "backup": _material_class(
            backup, new_hash=None, old_hash=old_archive_hash
        ),
        "result": _material_class(
            current_result,
            new_hash=new_result_hash,
            old_hash=old_result_hash,
        ),
        "stage": _material_class(
            stage, new_hash=new_archive_hash, old_hash=None
        ),
    }
    if "foreign" in classes.values():
        raise _recovery_required(
            "foreign transaction bytes detected; recovery evidence preserved"
        )
    if stage is not None and len(stage) != intent["stage"]["bytes"]:
        raise _recovery_required("stage byte count differs from intent")
    if backup is not None and len(backup) != intent["backup"]["bytes"]:
        raise _recovery_required("backup byte count differs from intent")
    if intent["phase"] == "staged":
        if classes["stage"] != "new":
            raise _recovery_required("durable staged intent is missing its stage")
        if intent["backup"]["exists"]:
            if classes["backup"] != "old":
                raise _recovery_required(
                    "durable staged intent is missing its prior backup"
                )
        elif classes["backup"] != "missing":
            raise _recovery_required(
                "durable staged intent has an unexpected backup"
            )

    roll_forward = (
        not prefer_rollback
        and (classes["stage"] == "new" or classes["archive"] == "new")
    )
    if roll_forward:
        new_archive = current_archive if classes["archive"] == "new" else stage
        if new_archive is None:
            raise _recovery_required("new archive material is unavailable")
        if classes["archive"] != "new":
            _write_verified_rooted(
                destination,
                new_archive,
                destination.parent,
                destination_identity,
                max_bytes=MAX_ARCHIVE_BYTES,
                generation=intent["generation"],
            )
        if classes["result"] != "new":
            _write_verified_rooted(
                result_path,
                new_result_bytes,
                package_root,
                package_identity,
                max_bytes=MAX_ARCHIVE_RESULT_BYTES,
                generation=intent["generation"],
            )
        persisted = load_archive_result(
            package_root,
            _allow_pending=True,
            _root_identity=package_identity,
        )
        expected_result = intent["new_result"]["payload"]
        if persisted != expected_result:
            raise _recovery_required("rolled-forward pair failed canonical validation")
    else:
        if intent["backup"]["exists"]:
            old_archive = (
                current_archive if classes["archive"] == "old" else backup
            )
            if old_archive is None:
                raise _recovery_required("prior archive material is unavailable")
            if classes["archive"] != "old":
                _write_verified_rooted(
                    destination,
                    old_archive,
                    destination.parent,
                    destination_identity,
                    max_bytes=MAX_ARCHIVE_BYTES,
                    generation=intent["generation"],
                )
        elif current_archive is not None:
            _unlink_exact_rooted(
                destination,
                current_archive,
                destination.parent,
                destination_identity,
                max_bytes=MAX_ARCHIVE_BYTES,
            )
        if old_result_bytes is not None:
            if classes["result"] != "old":
                _write_verified_rooted(
                    result_path,
                    old_result_bytes,
                    package_root,
                    package_identity,
                    max_bytes=MAX_ARCHIVE_RESULT_BYTES,
                    generation=intent["generation"],
                )
        elif current_result is not None:
            _unlink_exact_rooted(
                result_path,
                current_result,
                package_root,
                package_identity,
                max_bytes=MAX_ARCHIVE_RESULT_BYTES,
            )
        persisted = None

    latest_intent = _read_publication_intent(package_root, package_identity)
    if latest_intent is None:
        raise _recovery_required("publication intent vanished during recovery")
    latest_value, latest_raw, _, _ = latest_intent
    _cleanup_publication_material(
        package_root,
        package_identity,
        destination,
        destination_identity,
        latest_value,
        latest_raw,
        stage,
        backup,
    )
    return persisted


def quarantine_archive_transaction_temps(
    root: str | Path, *, confirm_aborted: bool
) -> dict[str, Any]:
    """Preserve recognized orphan/partial atomic temps outside active paths."""

    if confirm_aborted is not True:
        raise _recovery_required(
            "quarantine requires explicit confirmation that archive publication is not running"
        )
    package_root = _absolute(root)
    with package_operation_lock(package_root):
        package_identity = capture_root_identity(package_root)
        intent_path = archive_publication_intent_path(package_root)
        intent_raw = _rooted_optional_bytes(
            intent_path,
            package_root,
            package_identity,
            max_bytes=MAX_PUBLICATION_INTENT_BYTES,
        )
        candidates: list[tuple[str, Path, Path, RootIdentity, int]] = []
        generation = uuid.uuid4().hex
        has_intent = intent_raw is not None
        if intent_raw is None:
            for index, path in enumerate(
                _intent_atomic_temp_candidates(package_root), start=1
            ):
                candidates.append(
                    (
                        f"intent-{index}",
                        path,
                        package_root,
                        package_identity,
                        MAX_PUBLICATION_INTENT_BYTES,
                    )
                )
        else:
            try:
                value = strict_json_loads(intent_raw)
            except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise _recovery_required(
                    "canonical publication intent is malformed; temp quarantine is unsafe"
                ) from exc
            intent, _, _ = _validate_publication_intent(
                package_root, value, intent_raw
            )
            generation = intent["generation"]
            destination = _absolute(intent["destination_path"])
            destination_identity = capture_root_identity(destination.parent)
            targets = (
                (
                    "intent",
                    intent_path,
                    package_root,
                    package_identity,
                    MAX_PUBLICATION_INTENT_BYTES,
                ),
                (
                    "result",
                    package_root / ARCHIVE_RESULT_PATH,
                    package_root,
                    package_identity,
                    MAX_ARCHIVE_RESULT_BYTES,
                ),
                (
                    "destination",
                    destination,
                    destination.parent,
                    destination_identity,
                    MAX_ARCHIVE_BYTES,
                ),
                (
                    "stage",
                    _archive_stage_path(destination),
                    destination.parent,
                    destination_identity,
                    MAX_ARCHIVE_BYTES,
                ),
                (
                    "backup",
                    _archive_backup_path(destination),
                    destination.parent,
                    destination_identity,
                    MAX_ARCHIVE_BYTES,
                ),
            )
            for label, target, source_root, source_identity, max_bytes in targets:
                temporary = _publication_atomic_temp_path(target, generation)
                if os.path.lexists(temporary):
                    candidates.append(
                        (
                            label,
                            temporary,
                            source_root,
                            source_identity,
                            max_bytes,
                        )
                    )

        if not candidates:
            return {
                "generation": generation if has_intent else None,
                "quarantined": [],
                "status": "clean",
            }

        quarantine_roots: dict[str, tuple[Path, RootIdentity]] = {}
        quarantined: list[str] = []
        for label, source, source_root, source_identity, max_bytes in candidates:
            data = _rooted_optional_bytes(
                source,
                source_root,
                source_identity,
                max_bytes=max_bytes,
            )
            if data is None:
                continue
            quarantine_parent = (
                package_root.parent
                if _is_within(source, package_root)
                else source.parent
            )
            parent_key = _path_key(quarantine_parent)
            if parent_key not in quarantine_roots:
                quarantine_dir = quarantine_parent / (
                    f".{package_root.name}.archive-quarantine-{generation}"
                )
                if os.path.lexists(quarantine_dir):
                    current = quarantine_dir.lstat()
                    if (
                        not stat.S_ISDIR(current.st_mode)
                        or stat.S_ISLNK(current.st_mode)
                        or is_reparse_point(current)
                    ):
                        raise _recovery_required(
                            f"unsafe archive quarantine directory: {quarantine_dir}"
                        )
                else:
                    try:
                        os.mkdir(quarantine_dir, 0o700)
                    except OSError as exc:
                        raise _recovery_required(
                            f"cannot create archive quarantine directory: {quarantine_dir}"
                        ) from exc
                quarantine_roots[parent_key] = (
                    quarantine_dir,
                    capture_root_identity(quarantine_dir),
                )
            quarantine_dir, quarantine_identity = quarantine_roots[parent_key]
            destination = quarantine_dir / f"{label}-{source.name}"
            existing = _rooted_optional_bytes(
                destination,
                quarantine_dir,
                quarantine_identity,
                max_bytes=max_bytes,
            )
            if existing is not None and existing != data:
                raise _recovery_required(
                    f"archive quarantine destination contains different bytes: {destination}"
                )
            if existing is None:
                write_bytes_atomic(
                    destination,
                    data,
                    root=quarantine_dir,
                    root_identity=quarantine_identity,
                )
                persisted = _rooted_optional_bytes(
                    destination,
                    quarantine_dir,
                    quarantine_identity,
                    max_bytes=max_bytes,
                )
                if persisted != data:
                    raise _recovery_required(
                        f"archive quarantine copy differs: {destination}"
                    )
            _unlink_exact_rooted(
                source,
                data,
                source_root,
                source_identity,
                max_bytes=max_bytes,
            )
            quarantined.append(str(destination))
        return {
            "generation": generation if has_intent else None,
            "next": "archive-recover" if has_intent else "archive",
            "quarantined": sorted(quarantined),
            "status": "quarantined",
        }


def recover_archive_publication(root: str | Path) -> dict[str, Any]:
    package_root = _absolute(root)
    with package_operation_lock(package_root):
        result = _recover_publication_locked(package_root)
    return {"status": "clean"} if result is None else {"status": "recovered", "result": result}


def assert_no_archive_recovery_required(root: str | Path) -> None:
    package_root = _absolute(root)
    if (
        os.path.lexists(archive_publication_intent_path(package_root))
        or _intent_atomic_temp_candidates(package_root)
    ):
        raise _recovery_required(
            "pending publication intent or atomic temporary must be recovered before continuing"
        )


def load_archive_result(
    root: str | Path,
    *,
    _allow_pending: bool = False,
    _root_identity: RootIdentity | None = None,
    _include_archive_bytes: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], bytes]:
    package_root = _absolute(root)
    _assert_regular_root(package_root)
    if not _allow_pending:
        assert_no_archive_recovery_required(package_root)
    package_identity = _root_identity or capture_root_identity(package_root)
    result_path = package_root / ARCHIVE_RESULT_PATH
    try:
        result_stat = result_path.lstat()
        if int(result_stat.st_size) > MAX_ARCHIVE_RESULT_BYTES:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ARCHIVE-LIMIT: archive result exceeds fixed cap"
            )
        raw = read_regular_file_no_follow(
            result_path,
            package_root,
            max_bytes=MAX_ARCHIVE_RESULT_BYTES,
            root_identity=package_identity,
        )
        result = strict_json_loads(raw)
    except ArchiveSecurityError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive result is malformed"
        ) from exc
    if (
        not isinstance(result, dict)
        or set(result) != _RESULT_FIELDS
        or raw != _canonical_json_bytes(result)
        or result.get("archive_result_version") != ARCHIVE_RESULT_VERSION
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive result shape/canonical bytes are invalid"
        )
    records = _validate_record_list(result.get("snapshot_files"))
    identity = result.get("archive_identity")
    if (
        not isinstance(identity, dict)
        or set(identity) != {"absolute_path", "filename", "path_format"}
        or identity.get("path_format") not in {"posix", "windows"}
        or not isinstance(identity.get("absolute_path"), str)
        or not Path(identity["absolute_path"]).is_absolute()
        or identity.get("filename") != Path(identity["absolute_path"]).name
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive identity is invalid"
        )
    archive_path = _absolute(identity["absolute_path"])
    if identity != _archive_identity(archive_path):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive identity is not canonical"
        )
    if _is_within(archive_path, package_root):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT: recorded archive is inside package root"
        )
    claimed_archive_bytes = result.get("archive_bytes")
    if (
        type(claimed_archive_bytes) is not int
        or claimed_archive_bytes < 0
        or claimed_archive_bytes > MAX_ARCHIVE_BYTES
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ARCHIVE-LIMIT: claimed archive size exceeds fixed cap"
        )
    contract_raw, contract = _load_json_authority(
        package_root, "CONTRACT.json", root_identity=package_identity
    )
    manifest_raw, manifest = _load_json_authority(
        package_root, "MANIFEST.json", root_identity=package_identity
    )
    goal = contract.get("goal")
    delivery = contract.get("delivery")
    if not isinstance(goal, dict) or not isinstance(delivery, dict):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-CONTRACT-MALFORMED: contract authority is invalid"
        )
    expected_scalars = {
        "contract_revision": contract.get("contract_revision"),
        "contract_sha256": sha256_bytes(contract_raw),
        "delivery_items": delivery.get("items", []),
        "goal_id": goal.get("id"),
        "package_fingerprint": manifest.get("package_fingerprint"),
        "source_manifest_sha256": sha256_bytes(manifest_raw),
    }
    if any(result.get(key) != value for key, value in expected_scalars.items()):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive result authority identity mismatch"
        )
    archive_manifest = {
        "archive_manifest_version": ARCHIVE_MANIFEST_VERSION,
        "files": records,
        "secret_scan": "passed",
    }
    archive_manifest_bytes = _canonical_json_bytes(archive_manifest)
    if result.get("archive_manifest_sha256") != sha256_bytes(archive_manifest_bytes):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive manifest identity mismatch"
        )
    try:
        archive_parent_identity = capture_root_identity(archive_path.parent)
    except UnsafeFileError as exc:
        raise ArchiveSecurityError(
            f"{_classify_unsafe(exc)}: archive parent is unsafe"
        ) from exc
    archive_bytes = _safe_external_bytes(
        archive_path,
        expected_bytes=claimed_archive_bytes,
        root_identity=archive_parent_identity,
    )
    if (
        type(result.get("archive_bytes")) is not int
        or result["archive_bytes"] != len(archive_bytes)
        or not isinstance(result.get("archive_sha256"), str)
        or result["archive_sha256"] != sha256_bytes(archive_bytes)
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: external archive identity mismatch"
        )
    members = _verify_archive_bytes(
        archive_bytes, records, archive_manifest_bytes
    )
    trusted = _bind_archive_to_current_package(
        package_root,
        records,
        members,
        root_identity=package_identity,
    )
    if (
        trusted.contract_raw != contract_raw
        or trusted.manifest_raw != manifest_raw
    ):
        raise ArchiveSecurityError(
            "SGV-PACKAGE-MANIFEST-HASH: result identity is not trusted"
        )
    if _include_archive_bytes:
        return result, archive_bytes
    return result


def require_archive_result(
    root: str | Path, archive: str | Path | None = None
) -> dict[str, Any]:
    result = load_archive_result(root)
    if archive is not None:
        requested = _absolute(archive)
        recorded = _absolute(result["archive_identity"]["absolute_path"])
        if _path_key(requested) != _path_key(recorded):
            raise ArchiveSecurityError(
                "SGV-DELIVERY-ARCHIVE-MISSING: requested archive differs from canonical result"
            )
    return result


def require_archive_result_with_bytes(
    root: str | Path, archive: str | Path | None = None
) -> tuple[dict[str, Any], bytes]:
    loaded = load_archive_result(root, _include_archive_bytes=True)
    if not isinstance(loaded, tuple):  # Defensive type narrowing.
        raise ArchiveSecurityError(
            "SGV-PACKAGE-ZIP-HASH-MISMATCH: archive bytes were not captured"
        )
    result, archive_bytes = loaded
    if archive is not None:
        requested = _absolute(archive)
        recorded = _absolute(result["archive_identity"]["absolute_path"])
        if _path_key(requested) != _path_key(recorded):
            raise ArchiveSecurityError(
                "SGV-DELIVERY-ARCHIVE-MISSING: requested archive differs from canonical result"
            )
    return result, archive_bytes


def deterministic_zip(
    root: str | Path,
    archive: str | Path,
    manifest: str | Path,
    items: list[str] | None = None,
) -> dict[str, Any]:
    if items is not None:
        raise ArchiveSecurityError(
            "SGV-PACKAGE-PATH-ESCAPE: archive snapshots cannot use partial allowlists"
        )
    package_root = _absolute(root)
    destination = _absolute(archive)
    result_path = _absolute(manifest)
    _assert_regular_root(package_root)
    with package_operation_lock(package_root):
        # Resolve any prior durable intent under the same package-wide lock.
        _recover_publication_locked(
            package_root, requested_destination=destination
        )
        package_root, destination, result_path = _prepare_paths(
            package_root, destination, result_path
        )
        assert_runtime_mutable(package_root)
        package_identity = capture_root_identity(package_root)
        captures, _ = _capture_snapshot(
            package_root, root_identity=package_identity
        )
        authority = _snapshot_authority(captures, validate_mutable=True)
        records = [item.record() for item in captures]
        archive_manifest_bytes = _canonical_json_bytes(_manifest_for(captures))
        archive_stream = io.BytesIO()
        _write_archive(archive_stream, captures, archive_manifest_bytes)
        archive_bytes = archive_stream.getvalue()
        if len(archive_bytes) > MAX_ARCHIVE_BYTES:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ARCHIVE-LIMIT: generated archive exceeds fixed cap"
            )
        _verify_archive_bytes(archive_bytes, records, archive_manifest_bytes)
        result = _result_payload(
            destination,
            archive_bytes,
            records,
            archive_manifest_bytes,
            authority,
        )
        result_bytes = _canonical_json_bytes(result)
        if len(result_bytes) > MAX_ARCHIVE_RESULT_BYTES:
            raise ArchiveSecurityError(
                "SGV-PACKAGE-ARCHIVE-LIMIT: generated archive result exceeds fixed cap"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_alias_chain(destination, include_leaf=True)
        destination_identity = capture_root_identity(destination.parent)
        prior_destination = _rooted_optional_bytes(
            destination,
            destination.parent,
            destination_identity,
            max_bytes=MAX_ARCHIVE_BYTES,
        )
        prior_result = _rooted_optional_bytes(
            result_path,
            package_root,
            package_identity,
            max_bytes=MAX_ARCHIVE_RESULT_BYTES,
        )
        if prior_destination is not None:
            destination_stat = destination.lstat()
            source_identities = {
                (item.stat_signature[0], item.stat_signature[1])
                for item in captures
                if item.stat_signature[1] != 0
            }
            destination_aliases_source = (
                int(getattr(destination_stat, "st_dev", 0)),
                int(getattr(destination_stat, "st_ino", 0)),
            ) in source_identities
            if not destination_aliases_source:
                try:
                    destination_aliases_source = any(
                        os.path.samefile(destination, package_root / item.path)
                        for item in captures
                    )
                except OSError as exc:
                    raise ArchiveSecurityError(
                        "SGV-PACKAGE-PATH-ESCAPE: cannot verify destination identity"
                    ) from exc
            if destination_aliases_source:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ARCHIVE-INSIDE-ROOT: destination hard-links package authority"
                )

        # A delivered archive is immutable unless an explicit audited resend
        # flow first removes/replaces the receipt. Never silently stale it.
        receipt_path = package_root / "out/final-artifacts-delivery-receipt.json"
        receipt_raw = _rooted_optional_bytes(
            receipt_path,
            package_root,
            package_identity,
            max_bytes=MAX_ARCHIVE_RESULT_BYTES,
        )
        if receipt_raw is not None:
            try:
                receipt = strict_json_loads(receipt_raw)
                if (
                    not isinstance(receipt, dict)
                    or receipt_raw != _canonical_json_bytes(receipt)
                ):
                    raise ValueError("receipt bytes are not canonical")
                _, state_value = _load_json_authority(
                    package_root,
                    "runtime/STATE.json",
                    root_identity=package_identity,
                )
                state = State.from_dict(state_value)
                delivery = authority.contract.get("delivery")
                target = delivery.get("target") if isinstance(delivery, dict) else None
                if not isinstance(target, str) or not target:
                    raise ValueError("delivery target is unavailable")
                from .delivery import validate_final_receipt

                validate_final_receipt(
                    receipt,
                    state=state,
                    target=target,
                    archive_result=result,
                )
            except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise ArchiveSecurityError(
                    "SGV-DELIVERY-RECEIPT-INVALID: final receipt is malformed or stale"
                ) from exc

        intent = _build_publication_intent(
            package_root,
            destination,
            result_path,
            package_identity,
            destination_identity,
            authority,
            archive_bytes,
            result,
            result_bytes,
            prior_destination,
            prior_result,
        )
        intent_raw = _write_publication_intent(
            package_root, package_identity, intent
        )
        _publication_checkpoint("intent")

        stage_path = _archive_stage_path(destination)
        backup_path = _archive_backup_path(destination)
        try:
            existing_stage = _rooted_optional_bytes(
                stage_path,
                destination.parent,
                destination_identity,
                max_bytes=MAX_ARCHIVE_BYTES,
            )
            if existing_stage is None:
                _write_verified_rooted(
                    stage_path,
                    archive_bytes,
                    destination.parent,
                    destination_identity,
                    max_bytes=MAX_ARCHIVE_BYTES,
                    generation=intent["generation"],
                )
                existing_stage = archive_bytes
            elif existing_stage != archive_bytes:
                raise _recovery_required(
                    "foreign stage bytes; recovery evidence preserved"
                )
            existing_backup = _rooted_optional_bytes(
                backup_path,
                destination.parent,
                destination_identity,
                max_bytes=MAX_ARCHIVE_BYTES,
            )
            if prior_destination is None:
                if existing_backup is not None:
                    raise _recovery_required(
                        "unexpected backup bytes; recovery evidence preserved"
                    )
            elif existing_backup is None:
                _write_verified_rooted(
                    backup_path,
                    prior_destination,
                    destination.parent,
                    destination_identity,
                    max_bytes=MAX_ARCHIVE_BYTES,
                    generation=intent["generation"],
                )
                existing_backup = prior_destination
            elif existing_backup != prior_destination:
                raise _recovery_required(
                    "foreign backup bytes; recovery evidence preserved"
                )
            intent = dict(intent)
            intent["phase"] = "staged"
            intent_raw = _write_publication_intent(
                package_root, package_identity, intent
            )
            _publication_checkpoint("stage")

            _publication_checkpoint("before_destination")
            current_destination = _rooted_optional_bytes(
                destination,
                destination.parent,
                destination_identity,
                max_bytes=MAX_ARCHIVE_BYTES,
            )
            if current_destination != prior_destination:
                raise _recovery_required(
                    "destination changed concurrently before exact replacement"
                )
            _write_verified_rooted(
                destination,
                archive_bytes,
                destination.parent,
                destination_identity,
                max_bytes=MAX_ARCHIVE_BYTES,
                generation=intent["generation"],
            )
            persisted_archive = _verify_archive(
                destination,
                records,
                archive_manifest_bytes,
                expected_bytes=len(archive_bytes),
                root_identity=destination_identity,
            )
            if persisted_archive != archive_bytes:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ZIP-HASH-MISMATCH: published archive bytes changed"
                )
            intent = dict(intent)
            intent["phase"] = "destination"
            intent_raw = _write_publication_intent(
                package_root, package_identity, intent
            )
            _publication_checkpoint("destination")

            current_result = _rooted_optional_bytes(
                result_path,
                package_root,
                package_identity,
                max_bytes=MAX_ARCHIVE_RESULT_BYTES,
            )
            if current_result != prior_result:
                raise _recovery_required(
                    "archive result changed concurrently before exact replacement"
                )
            _write_verified_rooted(
                result_path,
                result_bytes,
                package_root,
                package_identity,
                max_bytes=MAX_ARCHIVE_RESULT_BYTES,
                generation=intent["generation"],
            )
            intent = dict(intent)
            intent["phase"] = "result"
            intent_raw = _write_publication_intent(
                package_root, package_identity, intent
            )
            persisted = load_archive_result(
                package_root,
                _allow_pending=True,
                _root_identity=package_identity,
            )
            if persisted != result:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ZIP-HASH-MISMATCH: persisted archive result mismatch"
                )
            _publication_checkpoint("result")
            _cleanup_publication_material(
                package_root,
                package_identity,
                destination,
                destination_identity,
                intent,
                intent_raw,
                existing_stage,
                existing_backup,
            )
            _publication_checkpoint("cleanup")
            return result
        except UnsafeFileError as original:
            # A root identity mismatch means the lexical path now targets a
            # different tree. Preserve intent/stage/backup and never touch it.
            raise ArchiveSecurityError(
                f"{_classify_unsafe(original)}: publication root changed"
            ) from original
        except Exception as original:
            try:
                _recover_publication_locked(
                    package_root,
                    requested_destination=destination,
                    prefer_rollback=True,
                )
            except ArchiveSecurityError as recovery_error:
                raise ArchiveSecurityError(
                    "SGV-PACKAGE-ARCHIVE-RECOVERY-REQUIRED: "
                    "archive publication failed and safe rollback could not complete"
                ) from recovery_error
            raise
