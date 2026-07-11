from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import BinaryIO, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


EXECUTABLE_WRAPPERS = frozenset(
    {
        "scripts/detect-stack.sh",
        "scripts/repo-state.sh",
        "scripts/summarize-repo.sh",
        "scripts/validate-loop-design.sh",
        "scripts/validate-phase.sh",
    }
)

RUNTIME_MODULES = (
    "__init__.py",
    "compile.py",
    "diagnostics.py",
    "events.py",
    "graph.py",
    "migrate.py",
    "model.py",
    "normalize.py",
    "pipeline.py",
    "policy.py",
    "portable.py",
    "profiles.py",
    "render.py",
    "research.py",
    "state.py",
    "validate.py",
)
RUNTIME_SCRIPTS = (
    "sgctl.py",
    "validate-phase.sh",
    "validate-loop-design.sh",
    "repo-state.sh",
    "detect-stack.sh",
    "summarize-repo.sh",
)
RUNTIME_TEMPLATES = (
    "LAUNCH_GOAL.md",
    "LOOP_DESIGN.md",
    "phase-goal.txt",
    "PROTOCOL.md",
    "RESEARCH.md",
    "ROADMAP.md",
    "STATE.md",
)
RUNTIME_SPEC_FILES = (
    "risk-policy.json",
    "diagnostic-catalog.json",
    "contract.schema.json",
    "diagnostic.schema.json",
    "event.schema.json",
    "evidence.schema.json",
    "state.schema.json",
)
RUNTIME_PROFILES = ("base.json", "public-clean.json", "chip-private.json")
SEALED_RUNTIME_PATHS = frozenset(
    [f"scripts/{name}" for name in RUNTIME_SCRIPTS]
    + [f"lib/chip_supergoal/{name}" for name in RUNTIME_MODULES]
    + [f"templates/{name}" for name in RUNTIME_TEMPLATES]
    + [f"spec/{name}" for name in RUNTIME_SPEC_FILES]
    + [f"profiles/{name}" for name in RUNTIME_PROFILES]
)


MUTABLE_PATHS = (
    {"path": "STATE.md", "required": True, "validation": "state_projection"},
    {"path": "runtime/STATE.json", "required": True, "validation": "state_schema_identity"},
    {"path": "runtime/events.jsonl", "required": True, "validation": "event_chain_identity_revision"},
    {"path": "runtime/evidence.json", "required": True, "validation": "evidence_json_array"},
    {"path": "runtime/state.lock", "required": False, "validation": "one_byte_lock"},
    {"path": "reports/final-audit.json", "required": False, "validation": "final_audit_json"},
    {"path": "reports/final-audit.md", "required": False, "validation": "final_audit_projection"},
    {"path": "reports/terminal-record.txt", "required": False, "validation": "terminal_record"},
    {"path": "out/review-md-files-delivery-receipt.json", "required": False, "validation": "review_delivery_receipt"},
    {"path": "out/final-artifacts-delivery-receipt.json", "required": False, "validation": "final_delivery_receipt"},
    {"path": "out/final-artifacts-manifest.json", "required": False, "validation": "archive_result"},
)
MUTABLE_PATH_NAMES = frozenset(item["path"] for item in MUTABLE_PATHS)
REQUIRED_MUTABLE_PATHS = frozenset(
    item["path"] for item in MUTABLE_PATHS if item["required"]
)


def is_reparse_point(stat_result: os.stat_result) -> bool:
    attributes = getattr(stat_result, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def iter_tree_no_follow(root: str | Path) -> Iterator[tuple[Path, os.stat_result]]:
    package_root = Path(root)
    pending = [package_root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            stat_result = entry.stat(follow_symlinks=False)
            yield path, stat_result
            if stat.S_ISDIR(stat_result.st_mode) and not (
                stat.S_ISLNK(stat_result.st_mode)
                or is_reparse_point(stat_result)
            ):
                child_directories.append(path)
        pending.extend(reversed(child_directories))


class StateLockTimeout(TimeoutError):
    pass


def canonical_text_bytes(content: str) -> bytes:
    return content.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def write_bytes_atomic(path: str | Path, content: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_utf8_lf(path: str | Path, content: str) -> None:
    write_bytes_atomic(path, canonical_text_bytes(content))


def logical_mode(relative_path: str | Path) -> str:
    normalized = str(relative_path).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return "0755" if normalized in EXECUTABLE_WRAPPERS else "0644"


def _open_lock_file(path: Path) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        before = path.lstat()
    except FileNotFoundError:
        before = None
    if before is not None and (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or is_reparse_point(before)
    ):
        raise OSError(f"lock path is not a regular file: {path}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or is_reparse_point(current)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise OSError(f"lock path changed while opening: {path}")
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        descriptor = -1
        if opened.st_size == 0:
            stream.seek(0)
            stream.write(b"\0")
            stream.flush()
            os.fsync(stream.fileno())
        elif opened.st_size != 1:
            raise OSError(f"lock file must contain exactly one byte: {path}")
        return stream
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        else:
            stream.close()
        raise


def package_operation_lock_path(root: str | Path) -> Path:
    package_root = Path(root).resolve(strict=False)
    return package_root.parent / f".{package_root.name}.operation.lock"


@contextmanager
def package_operation_lock(
    root: str | Path,
    *,
    timeout: float = 10.0,
    retry_interval: float = 0.05,
) -> Iterator[None]:
    with package_lock(
        package_operation_lock_path(root),
        timeout=timeout,
        retry_interval=retry_interval,
    ):
        yield


def _acquire_nonblocking(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def package_lock(
    path: str | Path,
    *,
    timeout: float = 10.0,
    retry_interval: float = 0.05,
) -> Iterator[None]:
    lock_path = Path(path)
    stream = _open_lock_file(lock_path)
    acquired = False
    deadline = time.monotonic() + max(timeout, 0.0)
    busy_errors = {errno.EACCES, errno.EAGAIN}
    if hasattr(errno, "EDEADLK"):
        busy_errors.add(errno.EDEADLK)
    try:
        while True:
            try:
                _acquire_nonblocking(stream)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in busy_errors:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StateLockTimeout(
                        f"SGV-STATE-LOCK-TIMEOUT: timed out acquiring {lock_path}"
                    ) from exc
                time.sleep(min(max(retry_interval, 0.0), remaining))
        yield
    finally:
        try:
            if acquired:
                _release(stream)
        finally:
            stream.close()
