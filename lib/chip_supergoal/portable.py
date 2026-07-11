from __future__ import annotations

from contextlib import contextmanager
import ctypes
import errno
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import BinaryIO, Iterator

if os.name == "nt":
    import msvcrt
    from ctypes import wintypes
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


class UnsafeFileError(OSError):
    def __init__(self, path: str | Path, reason: str, *, kind: str = "special"):
        self.path = Path(path)
        self.reason = reason
        self.kind = kind
        super().__init__(f"unsafe package file {self.path}: {reason}")


def _contained_relative(path: str | Path, root: str | Path) -> tuple[Path, Path, Path]:
    package_root = Path(os.path.abspath(root))
    target = Path(os.path.abspath(path))
    try:
        relative = target.relative_to(package_root)
    except ValueError as exc:
        raise UnsafeFileError(path, "path is outside the trusted root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise UnsafeFileError(path, "path is not a regular child of the trusted root")
    return target, package_root, relative


def _unsafe_open_error(path: Path, exc: BaseException) -> UnsafeFileError:
    try:
        stat_result = path.lstat()
        if stat.S_ISLNK(stat_result.st_mode) or is_reparse_point(stat_result):
            return UnsafeFileError(path, "symlink or reparse point rejected", kind="symlink")
    except OSError:
        pass
    return UnsafeFileError(path, "regular file could not be opened without following links")


def _read_regular_file_posix(target: Path, root: Path, relative: Path) -> bytes:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
        file_flags |= os.O_CLOEXEC
    directory_fds: list[int] = []
    file_fd: int | None = None
    try:
        root_fd = os.open(root, directory_flags)
        directory_fds.append(root_fd)
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            raise UnsafeFileError(root, "trusted root is not a directory")
        current_fd = root_fd
        for component in relative.parts[:-1]:
            current_fd = os.open(component, directory_flags, dir_fd=current_fd)
            directory_fds.append(current_fd)
            if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
                raise UnsafeFileError(target, "path component is not a directory")
        file_fd = os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise UnsafeFileError(target, "target is not a regular file")
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = None
            return stream.read()
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(target, exc) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for descriptor in reversed(directory_fds):
            os.close(descriptor)


if os.name == "nt":
    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_TYPE_DISK = 0x0001
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL
    _GetFileInformationByHandle = _kernel32.GetFileInformationByHandle
    _GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    _GetFileInformationByHandle.restype = wintypes.BOOL
    _GetFinalPathNameByHandleW = _kernel32.GetFinalPathNameByHandleW
    _GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _GetFileType = _kernel32.GetFileType
    _GetFileType.argtypes = [wintypes.HANDLE]
    _GetFileType.restype = wintypes.DWORD


def _windows_handle_value(handle: object) -> int:
    value = getattr(handle, "value", handle)
    return int(value)


def _windows_final_path(handle: object) -> Path:
    size = 512
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = _GetFinalPathNameByHandleW(handle, buffer, size, 0)
        if length == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        if length < size:
            value = buffer.value
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
            return Path(os.path.normpath(value))
        size = length + 1


def _windows_contained(path: Path, root: Path) -> bool:
    normalized_path = os.path.normcase(os.path.normpath(path))
    normalized_root = os.path.normcase(os.path.normpath(root))
    try:
        return os.path.commonpath((normalized_path, normalized_root)) == normalized_root
    except ValueError:
        return False


def _open_windows_verified(path: Path, *, directory: bool) -> tuple[object, Path]:
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    desired_access = 0
    share = _FILE_SHARE_READ | _FILE_SHARE_WRITE
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    else:
        desired_access = _GENERIC_READ
        share |= _FILE_SHARE_DELETE
    handle = _CreateFileW(
        str(path),
        desired_access,
        share,
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    if _windows_handle_value(handle) == _INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        information = _ByHandleFileInformation()
        if not _GetFileInformationByHandle(handle, ctypes.byref(information)):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = information.dwFileAttributes
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise UnsafeFileError(path, "symlink or reparse point rejected", kind="symlink")
        is_directory = bool(attributes & _FILE_ATTRIBUTE_DIRECTORY)
        if is_directory != directory:
            raise UnsafeFileError(path, "node type does not match the requested file type")
        if not directory and _GetFileType(handle) != _FILE_TYPE_DISK:
            raise UnsafeFileError(path, "target is not a regular disk file")
        return handle, _windows_final_path(handle)
    except BaseException:
        _CloseHandle(handle)
        raise


def _read_regular_file_windows(target: Path, root: Path, relative: Path) -> bytes:
    directory_handles: list[object] = []
    file_handle: object | None = None
    try:
        root_handle, final_root = _open_windows_verified(root, directory=True)
        directory_handles.append(root_handle)
        current = root
        for component in relative.parts[:-1]:
            current /= component
            handle, final_directory = _open_windows_verified(current, directory=True)
            if not _windows_contained(final_directory, final_root):
                _CloseHandle(handle)
                raise UnsafeFileError(current, "directory resolves outside the trusted root")
            directory_handles.append(handle)
        file_handle, final_target = _open_windows_verified(target, directory=False)
        if not _windows_contained(final_target, final_root):
            raise UnsafeFileError(target, "file resolves outside the trusted root")
        descriptor = msvcrt.open_osfhandle(
            _windows_handle_value(file_handle),
            os.O_RDONLY | os.O_BINARY,
        )
        file_handle = None
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(target, exc) from exc
    finally:
        if file_handle is not None:
            _CloseHandle(file_handle)
        for handle in reversed(directory_handles):
            _CloseHandle(handle)


def read_regular_file_no_follow(path: str | Path, root: str | Path) -> bytes:
    target, package_root, relative = _contained_relative(path, root)
    if os.name == "nt":
        return _read_regular_file_windows(target, package_root, relative)
    return _read_regular_file_posix(target, package_root, relative)


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
