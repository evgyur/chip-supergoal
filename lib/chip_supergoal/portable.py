from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import time
from typing import BinaryIO, Iterable, Iterator

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
        "templates/delivery/package-final-artifacts.sh",
        "templates/delivery/send-final-artifacts.sh",
        "templates/delivery/send-review-md-files.sh",
    }
)

RUNTIME_MODULES = (
    "__init__.py",
    "archive.py",
    "audit.py",
    "compile.py",
    "delivery.py",
    "diagnostics.py",
    "evidence.py",
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
    "terminal.py",
    "validate.py",
)
RUNTIME_SCRIPTS = (
    "sgctl.py",
    "check-cross-file-consistency.py",
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
    "delivery/final-artifacts-delivery-receipt.schema.json",
    "delivery/package-final-artifacts.sh",
    "delivery/review-md-files-delivery-receipt.schema.json",
    "delivery/send-final-artifacts.sh",
    "delivery/send-review-md-files.sh",
)
RUNTIME_SPEC_FILES = (
    "archive-manifest.schema.json",
    "archive-result.schema.json",
    "risk-policy.json",
    "diagnostic-catalog.json",
    "contract.schema.json",
    "diagnostic.schema.json",
    "event.schema.json",
    "evidence.schema.json",
    "final-audit.schema.json",
    "marker-contract.json",
    "state-machine.json",
    "state.schema.json",
)
RUNTIME_PROFILES = ("base.json", "public-clean.json", "chip-private.json")
DELIVERY_RESERVATION_KINDS = frozenset({"review-md-files", "final-artifacts"})
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
    {"path": "runtime/operation.lock", "required": False, "validation": "one_byte_lock"},
    {"path": "runtime/archive-publication.json", "required": False, "validation": "archive_publication_intent"},
    {"path": "runtime/review-delivery-reservation.json", "required": False, "validation": "delivery_reservation"},
    {"path": "runtime/final-delivery-reservation.json", "required": False, "validation": "delivery_reservation"},
    {"path": "runtime/review-delivery-reservation.pending.json", "required": False, "validation": "delivery_transaction"},
    {"path": "runtime/final-delivery-reservation.pending.json", "required": False, "validation": "delivery_transaction"},
    {"path": "reports/final-audit.json", "required": False, "validation": "final_audit_json"},
    {"path": "reports/final-audit.md", "required": False, "validation": "final_audit_projection"},
    {"path": "reports/terminal-record.txt", "required": False, "validation": "terminal_record"},
    {"path": "out/review-md-files-delivery-receipt.json", "required": False, "validation": "review_delivery_receipt"},
    {"path": "out/final-artifacts-delivery-receipt.json", "required": False, "validation": "final_delivery_receipt"},
    {"path": "out/review-md-files-delivery-receipt.pending.json", "required": False, "validation": "delivery_transaction"},
    {"path": "out/final-artifacts-delivery-receipt.pending.json", "required": False, "validation": "delivery_transaction"},
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


def iter_tree_no_follow(
    root: str | Path,
    *,
    max_entries: int | None = None,
    prune_directory_names: Iterable[str] = (),
) -> Iterator[tuple[Path, os.stat_result]]:
    """Yield a deterministic tree inventory without crossing filesystem links.

    Pruned directories are yielded so callers can diagnose them, but their
    contents are never enumerated.
    """

    package_root = Path(root)
    pruned_names = frozenset(prune_directory_names)
    if os.name == "nt":
        yield from _iter_tree_no_follow_windows(
            package_root,
            max_entries=max_entries,
            pruned_names=pruned_names,
        )
        return
    yield from _iter_tree_no_follow_posix(
        package_root,
        max_entries=max_entries,
        pruned_names=pruned_names,
    )


class StateLockTimeout(TimeoutError):
    pass


class UnsafeFileError(OSError):
    def __init__(self, path: str | Path, reason: str, *, kind: str = "special"):
        self.path = Path(path)
        self.reason = reason
        self.kind = kind
        super().__init__(f"unsafe package file {self.path}: {reason}")


@dataclass
class _TreeWalkFrame:
    logical_path: Path
    guard: object | None
    scan_source: int | Path
    children: tuple[
        tuple[str, Path, os.stat_result, tuple[int, int]], ...
    ] = ()
    next_child: int = 0
    scanned: bool = False


def _tree_directory(stat_result: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(stat_result.st_mode)
        and not stat.S_ISLNK(stat_result.st_mode)
        and not is_reparse_point(stat_result)
    )


def _tree_directory_identity(stat_result: os.stat_result) -> tuple[int, int]:
    return int(stat_result.st_dev), int(stat_result.st_ino)


def _scan_tree_directory(
    source: int | Path,
    package_root: Path,
    *,
    observed: int,
    max_entries: int | None,
) -> tuple[list[tuple[str, os.stat_result]], int]:
    entries: list[tuple[str, os.stat_result]] = []
    with os.scandir(source) as iterator:
        for entry in iterator:
            observed += 1
            if max_entries is not None and observed > max_entries:
                raise UnsafeFileError(
                    package_root,
                    "tree entry count exceeds bounded enumeration limit",
                    kind="limit",
                )
            entries.append((entry.name, entry.stat(follow_symlinks=False)))
    entries.sort(key=lambda item: item[0])
    return entries, observed


def _iter_tree_no_follow_posix(
    package_root: Path,
    *,
    max_entries: int | None,
    pruned_names: frozenset[str],
    root_descriptor: int | None = None,
) -> Iterator[tuple[Path, os.stat_result]]:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    if root_descriptor is None:
        try:
            owned_root_descriptor = os.open(package_root, directory_flags)
        except OSError as exc:
            raise _unsafe_open_error(package_root, exc) from exc
    else:
        owned_root_descriptor = os.dup(root_descriptor)
        if not stat.S_ISDIR(os.fstat(owned_root_descriptor).st_mode):
            os.close(owned_root_descriptor)
            raise UnsafeFileError(package_root, "tree root is not a directory")
    stack = [
        _TreeWalkFrame(
            package_root,
            owned_root_descriptor,
            owned_root_descriptor,
        )
    ]
    observed = 0
    try:
        while stack:
            frame = stack[-1]
            if not frame.scanned:
                entries, observed = _scan_tree_directory(
                    int(frame.scan_source),
                    package_root,
                    observed=observed,
                    max_entries=max_entries,
                )
                children: list[
                    tuple[str, Path, os.stat_result, tuple[int, int]]
                ] = []
                for name, stat_result in entries:
                    path = frame.logical_path / name
                    if _tree_directory(stat_result) and name not in pruned_names:
                        children.append(
                            (
                                name,
                                path,
                                stat_result,
                                _tree_directory_identity(stat_result),
                            )
                        )
                    yield path, stat_result
                frame.children = tuple(children)
                frame.scanned = True
                continue
            if frame.next_child < len(frame.children):
                name, path, _, expected_identity = frame.children[
                    frame.next_child
                ]
                frame.next_child += 1
                child_descriptor: int | None = None
                try:
                    child_descriptor = os.open(
                        name,
                        directory_flags,
                        dir_fd=int(frame.guard),
                    )
                    opened_stat = os.fstat(child_descriptor)
                    if (
                        not _tree_directory(opened_stat)
                        or _tree_directory_identity(opened_stat)
                        != expected_identity
                    ):
                        raise UnsafeFileError(
                            path,
                            "directory identity changed before traversal",
                            kind="escape",
                        )
                    stack.append(
                        _TreeWalkFrame(path, child_descriptor, child_descriptor)
                    )
                    child_descriptor = None
                except UnsafeFileError:
                    raise
                except OSError as exc:
                    raise _unsafe_open_error(path, exc) from exc
                finally:
                    if child_descriptor is not None:
                        os.close(child_descriptor)
                continue
            descriptor = int(frame.guard)
            frame.guard = None
            stack.pop()
            os.close(descriptor)
    finally:
        for frame in reversed(stack):
            if frame.guard is not None:
                os.close(int(frame.guard))
                frame.guard = None


@dataclass(frozen=True)
class RootIdentity:
    platform: str
    volume_or_device: int
    file_index_or_inode: int


def _posix_root_identity(stat_result: os.stat_result) -> RootIdentity:
    return RootIdentity("posix", int(stat_result.st_dev), int(stat_result.st_ino))


def _require_root_identity(
    actual: RootIdentity,
    expected: RootIdentity | None,
    root: Path,
) -> None:
    if expected is not None and actual != expected:
        raise UnsafeFileError(
            root, "trusted root physical identity changed", kind="escape"
        )


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


def _read_bounded_stream(
    stream: BinaryIO, path: Path, max_bytes: int | None
) -> bytes:
    if max_bytes is None:
        return stream.read()
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        chunk = stream.read(min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise UnsafeFileError(path, "regular file exceeds bounded read limit", kind="limit")
    return data


def _read_regular_file_posix(
    target: Path,
    root: Path,
    relative: Path,
    *,
    max_bytes: int | None,
    root_identity: RootIdentity | None,
) -> bytes:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
        file_flags |= os.O_CLOEXEC
    directory_fds: list[int] = []
    file_fd: int | None = None
    try:
        try:
            root_fd = os.open(root, directory_flags)
        except OSError as exc:
            if root_identity is not None:
                raise UnsafeFileError(
                    root, "trusted root could not be reopened", kind="escape"
                ) from exc
            raise
        directory_fds.append(root_fd)
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise UnsafeFileError(root, "trusted root is not a directory")
        _require_root_identity(_posix_root_identity(root_stat), root_identity, root)
        current_fd = root_fd
        for component in relative.parts[:-1]:
            current_fd = os.open(component, directory_flags, dir_fd=current_fd)
            directory_fds.append(current_fd)
            if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
                raise UnsafeFileError(target, "path component is not a directory")
        file_fd = os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
        opened_stat = os.fstat(file_fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise UnsafeFileError(target, "target is not a regular file")
        if max_bytes is not None and opened_stat.st_size > max_bytes:
            raise UnsafeFileError(
                target, "regular file exceeds bounded read limit", kind="limit"
            )
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = None
            return _read_bounded_stream(stream, target, max_bytes)
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
    _GENERIC_WRITE = 0x40000000
    _DELETE_ACCESS = 0x00010000
    _SYNCHRONIZE_ACCESS = 0x00100000
    _FILE_READ_DATA = 0x00000001
    _FILE_WRITE_DATA = 0x00000002
    _FILE_APPEND_DATA = 0x00000004
    _FILE_TRAVERSE = 0x00000020
    _FILE_READ_ATTRIBUTES = 0x00000080
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_TYPE_DISK = 0x0001
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _FILE_DISPOSITION_INFO_CLASS = 4
    _FILE_RENAME_INFORMATION_CLASS_NT = 10
    _FILE_OPEN = 1
    _FILE_CREATE = 2
    _FILE_OPEN_IF = 3
    _FILE_DIRECTORY_FILE = 0x00000001
    _FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
    _FILE_NON_DIRECTORY_FILE = 0x00000040
    _FILE_OPEN_REPARSE_POINT_NT = 0x00200000
    _OBJ_CASE_INSENSITIVE = 0x00000040

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

    class _FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", ctypes.c_ubyte),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", ctypes.c_ubyte)]

    class _UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(_UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class _IoStatusValue(ctypes.Union):
        _fields_ = [
            ("Status", ctypes.c_long),
            ("Pointer", wintypes.LPVOID),
        ]

    class _IoStatusBlock(ctypes.Structure):
        _anonymous_ = ("Value",)
        _fields_ = [
            ("Value", _IoStatusValue),
            ("Information", ctypes.c_size_t),
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
    _SetFileInformationByHandle = _kernel32.SetFileInformationByHandle
    _SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _SetFileInformationByHandle.restype = wintypes.BOOL
    _ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    _NtCreateFile = _ntdll.NtCreateFile
    _NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    ]
    _NtCreateFile.restype = ctypes.c_long
    _NtSetInformationFile = _ntdll.NtSetInformationFile
    _NtSetInformationFile.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.c_int,
    ]
    _NtSetInformationFile.restype = ctypes.c_long
    _RtlNtStatusToDosError = _ntdll.RtlNtStatusToDosError
    _RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    _RtlNtStatusToDosError.restype = wintypes.ULONG


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


def _open_windows_verified(
    path: Path,
    *,
    directory: bool,
    desired_access: int | None = None,
    share_delete: bool = True,
) -> tuple[object, Path]:
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    access = 0
    share = _FILE_SHARE_READ | _FILE_SHARE_WRITE
    if share_delete:
        share |= _FILE_SHARE_DELETE
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    else:
        access = _GENERIC_READ
    if desired_access is not None:
        access = desired_access
    handle = _CreateFileW(
        str(path),
        access,
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


def _raise_windows_ntstatus(status: int) -> None:
    error = _RtlNtStatusToDosError(status)
    raise ctypes.WinError(error)


def _validate_windows_handle(
    handle: object,
    path: Path,
    *,
    directory: bool,
) -> Path:
    information = _ByHandleFileInformation()
    if not _GetFileInformationByHandle(handle, ctypes.byref(information)):
        raise ctypes.WinError(ctypes.get_last_error())
    attributes = information.dwFileAttributes
    if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise UnsafeFileError(
            path, "symlink or reparse point rejected", kind="symlink"
        )
    is_directory = bool(attributes & _FILE_ATTRIBUTE_DIRECTORY)
    if is_directory != directory:
        raise UnsafeFileError(
            path, "node type does not match the requested file type"
        )
    if not directory and _GetFileType(handle) != _FILE_TYPE_DISK:
        raise UnsafeFileError(path, "target is not a regular disk file")
    return _windows_final_path(handle)


def _open_windows_relative_verified(
    parent_handle: object,
    name: str,
    *,
    directory: bool,
    create: bool = False,
    create_if_missing: bool = False,
    desired_access: int | None = None,
    share_mode: int | None = None,
) -> tuple[object, Path]:
    """Open one child relative to an already verified directory handle."""

    if (
        not name
        or Path(name).name != name
        or any(separator in name for separator in ("/", "\\"))
    ):
        raise ValueError("Windows relative open requires one child name")
    encoded = name.encode("utf-16-le")
    name_buffer = ctypes.create_unicode_buffer(name)
    unicode_name = _UnicodeString(
        Length=len(encoded),
        MaximumLength=len(encoded) + ctypes.sizeof(ctypes.c_wchar),
        Buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        Length=ctypes.sizeof(_ObjectAttributes),
        RootDirectory=wintypes.HANDLE(_windows_handle_value(parent_handle)),
        ObjectName=ctypes.pointer(unicode_name),
        Attributes=_OBJ_CASE_INSENSITIVE,
        SecurityDescriptor=None,
        SecurityQualityOfService=None,
    )
    handle = wintypes.HANDLE()
    status_block = _IoStatusBlock()
    if desired_access is None:
        desired_access = _FILE_READ_ATTRIBUTES | _SYNCHRONIZE_ACCESS
        if directory:
            desired_access |= _FILE_TRAVERSE
        else:
            desired_access |= _FILE_READ_DATA
    options = _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT_NT
    options |= _FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE
    if share_mode is None:
        share_mode = _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE
    if create and create_if_missing:
        raise ValueError("relative open cannot combine create modes")
    disposition = (
        _FILE_CREATE
        if create
        else _FILE_OPEN_IF
        if create_if_missing
        else _FILE_OPEN
    )
    status = _NtCreateFile(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(attributes),
        ctypes.byref(status_block),
        None,
        _FILE_ATTRIBUTE_NORMAL if (create or create_if_missing) and not directory else 0,
        share_mode,
        disposition,
        options,
        None,
        0,
    )
    if status < 0:
        _raise_windows_ntstatus(status)
    try:
        logical_path = _windows_final_path(parent_handle) / name
        return handle, _validate_windows_handle(
            handle, logical_path, directory=directory
        )
    except BaseException:
        _CloseHandle(handle)
        raise


def _windows_descriptor_handle(descriptor: int) -> object:
    return wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))


def _windows_file_identity(handle: object) -> tuple[int, int]:
    information = _ByHandleFileInformation()
    if not _GetFileInformationByHandle(handle, ctypes.byref(information)):
        raise ctypes.WinError(ctypes.get_last_error())
    index = (information.nFileIndexHigh << 32) | information.nFileIndexLow
    return information.dwVolumeSerialNumber, index


def _iter_tree_no_follow_windows(
    package_root: Path,
    *,
    max_entries: int | None,
    pruned_names: frozenset[str],
    root_share_delete: bool = False,
) -> Iterator[tuple[Path, os.stat_result]]:
    directory_access = (
        _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE_ACCESS
    )
    directory_share = _FILE_SHARE_READ | _FILE_SHARE_WRITE
    root_handle: object | None = None
    try:
        root_handle, root_final_path = _open_windows_verified(
            package_root,
            directory=True,
            desired_access=directory_access,
            share_delete=root_share_delete,
        )
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(package_root, exc) from exc
    stack = [_TreeWalkFrame(package_root, root_handle, root_final_path)]
    root_handle = None
    observed = 0
    try:
        while stack:
            frame = stack[-1]
            if not frame.scanned:
                entries, observed = _scan_tree_directory(
                    Path(frame.scan_source),
                    package_root,
                    observed=observed,
                    max_entries=max_entries,
                )
                children: list[
                    tuple[str, Path, os.stat_result, tuple[int, int]]
                ] = []
                for name, stat_result in entries:
                    path = frame.logical_path / name
                    if _tree_directory(stat_result) and name not in pruned_names:
                        child_handle: object | None = None
                        try:
                            child_handle, _ = _open_windows_relative_verified(
                                frame.guard,
                                name,
                                directory=True,
                                desired_access=directory_access,
                            )
                            expected_identity = _windows_file_identity(child_handle)
                        except UnsafeFileError:
                            raise
                        except OSError as exc:
                            raise _unsafe_open_error(path, exc) from exc
                        finally:
                            if child_handle is not None:
                                _CloseHandle(child_handle)
                        children.append(
                            (name, path, stat_result, expected_identity)
                        )
                    yield path, stat_result
                frame.children = tuple(children)
                frame.scanned = True
                continue
            if frame.next_child < len(frame.children):
                name, path, _, expected_identity = frame.children[
                    frame.next_child
                ]
                frame.next_child += 1
                child_handle: object | None = None
                try:
                    child_handle, child_final_path = _open_windows_relative_verified(
                        frame.guard,
                        name,
                        directory=True,
                        desired_access=directory_access,
                        share_mode=directory_share,
                    )
                    if _windows_file_identity(child_handle) != expected_identity:
                        raise UnsafeFileError(
                            path,
                            "directory identity changed before traversal",
                            kind="escape",
                        )
                    stack.append(
                        _TreeWalkFrame(path, child_handle, child_final_path)
                    )
                    child_handle = None
                except UnsafeFileError:
                    raise
                except OSError as exc:
                    raise _unsafe_open_error(path, exc) from exc
                finally:
                    if child_handle is not None:
                        _CloseHandle(child_handle)
                continue
            handle = frame.guard
            frame.guard = None
            stack.pop()
            _CloseHandle(handle)
    finally:
        if root_handle is not None:
            _CloseHandle(root_handle)
        for frame in reversed(stack):
            if frame.guard is not None:
                _CloseHandle(frame.guard)
                frame.guard = None


def _windows_root_identity(handle: object) -> RootIdentity:
    volume, index = _windows_file_identity(handle)
    return RootIdentity("windows", int(volume), int(index))


def capture_root_identity(root: str | Path) -> RootIdentity:
    """Capture a directory identity from one verified opened fd/handle."""

    package_root = Path(os.path.abspath(root))
    if os.name == "nt":
        handle: object | None = None
        try:
            handle, _ = _open_windows_verified(package_root, directory=True)
            return _windows_root_identity(handle)
        except UnsafeFileError:
            raise
        except OSError as exc:
            raise _unsafe_open_error(package_root, exc) from exc
        finally:
            if handle is not None:
                _CloseHandle(handle)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(package_root, flags)
        current = os.fstat(descriptor)
        if not stat.S_ISDIR(current.st_mode):
            raise UnsafeFileError(package_root, "trusted root is not a directory")
        return _posix_root_identity(current)
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(package_root, exc) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _assert_windows_directory_chain(
    package_root: Path,
    parent_parts: tuple[str, ...],
    directory_handles: list[object],
) -> None:
    if len(directory_handles) != len(parent_parts) + 1:
        raise UnsafeFileError(package_root, "verified directory chain is incomplete")
    current = package_root
    paths = [current]
    for component in parent_parts:
        current /= component
        paths.append(current)
    for path, expected_handle in zip(paths, directory_handles):
        reopened = None
        try:
            try:
                reopened, _ = _open_windows_verified(path, directory=True)
            except OSError as exc:
                raise UnsafeFileError(
                    path,
                    "directory could not be reopened during identity check",
                    kind="escape",
                ) from exc
            if _windows_file_identity(reopened) != _windows_file_identity(
                expected_handle
            ):
                raise UnsafeFileError(
                    path,
                    "directory identity changed during operation",
                    kind="escape",
                )
        finally:
            if reopened is not None:
                _CloseHandle(reopened)


def _open_windows_directory_chain(
    package_root: Path,
    parent_parts: tuple[str, ...],
    *,
    create: bool,
    root_identity: RootIdentity | None = None,
) -> list[object]:
    """Open a root-bound parent chain without resolving child path strings."""

    handles: list[object] = []
    try:
        root_handle, _ = _open_windows_verified(
            package_root,
            directory=True,
            desired_access=(
                _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE_ACCESS
            ),
        )
    except OSError as exc:
        if root_identity is not None:
            raise UnsafeFileError(
                package_root,
                "trusted root could not be reopened",
                kind="escape",
            ) from exc
        raise
    handles.append(root_handle)
    try:
        _require_root_identity(
            _windows_root_identity(root_handle), root_identity, package_root
        )
        for component in parent_parts:
            try:
                handle, _ = _open_windows_relative_verified(
                    handles[-1], component, directory=True
                )
            except FileNotFoundError:
                if not create:
                    raise
                handle, _ = _open_windows_relative_verified(
                    handles[-1], component, directory=True, create=True
                )
            handles.append(handle)
        return handles
    except BaseException:
        for handle in reversed(handles):
            _CloseHandle(handle)
        raise


def _create_windows_temp_descriptor(
    parent_handle: object,
    *,
    target_name: str,
    package_root: Path,
    parent_parts: tuple[str, ...],
    directory_handles: list[object],
    requested_leaf: str | None = None,
) -> tuple[int, str]:
    """Create a sibling temporary file while the verified parent stays open."""

    attempts = 1 if requested_leaf is not None else 128
    for _ in range(attempts):
        _assert_windows_directory_chain(
            package_root, parent_parts, directory_handles
        )
        leaf = requested_leaf or (
            f".{target_name}.tmp-{os.getpid()}-"
            f"{next(tempfile._get_candidate_names())}"
        )
        try:
            handle, path = _open_windows_relative_verified(
                parent_handle,
                leaf,
                directory=False,
                create=True,
                desired_access=(
                    _FILE_READ_DATA
                    | _FILE_WRITE_DATA
                    | _FILE_READ_ATTRIBUTES
                    | _DELETE_ACCESS
                    | _SYNCHRONIZE_ACCESS
                ),
            )
        except OSError as exc:
            if getattr(exc, "winerror", None) in {80, 183}:
                if requested_leaf is not None:
                    raise
                continue
            raise
        try:
            final_path = _windows_final_path(handle)
            if final_path.name != leaf:
                raise UnsafeFileError(
                    path, "temporary file escaped its verified parent"
                )
            descriptor = msvcrt.open_osfhandle(
                _windows_handle_value(handle), os.O_RDWR | os.O_BINARY
            )
            handle = None
            return descriptor, leaf
        finally:
            if handle is not None:
                _CloseHandle(handle)
    raise FileExistsError("could not allocate a unique atomic temporary file")


def _write_windows_descriptor(
    descriptor: int, content: bytes, *, target: Path, temporary: Path
) -> None:
    view = memoryview(content)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset : offset + 64 * 1024])
        if written <= 0:
            raise OSError("atomic temporary write made no progress")
        offset += written
        _atomic_write_progress_checkpoint(
            target, temporary, offset, len(view)
        )
    os.fsync(descriptor)


def _rename_windows_handle_relative(
    source_handle: object,
    parent_handle: object,
    target_name: str,
    *,
    replace: bool,
) -> None:
    if (
        not target_name
        or Path(target_name).name != target_name
        or any(separator in target_name for separator in ("/", "\\"))
    ):
        raise ValueError("atomic destination must be one relative file name")
    encoded = target_name.encode("utf-16-le")
    filename_offset = _FileRenameInfo.FileName.offset
    size = ctypes.sizeof(_FileRenameInfo) + len(encoded)
    buffer = ctypes.create_string_buffer(size)
    information = _FileRenameInfo.from_buffer(buffer)
    information.ReplaceIfExists = int(replace)
    # The target directory is the already verified handle; no mutable path is
    # resolved during publication.
    information.RootDirectory = wintypes.HANDLE(
        _windows_handle_value(parent_handle)
    )
    information.FileNameLength = len(encoded)
    ctypes.memmove(
        ctypes.addressof(buffer) + filename_offset, encoded, len(encoded)
    )
    status_block = _IoStatusBlock()
    status = _NtSetInformationFile(
        source_handle,
        ctypes.byref(status_block),
        ctypes.byref(buffer),
        size,
        _FILE_RENAME_INFORMATION_CLASS_NT,
    )
    if status < 0:
        _raise_windows_ntstatus(status)


def _rename_windows_descriptor(
    descriptor: int,
    parent_handle: object,
    target_name: str,
    *,
    package_root: Path,
    parent_parts: tuple[str, ...],
    directory_handles: list[object],
) -> None:
    _assert_windows_directory_chain(
        package_root, parent_parts, directory_handles
    )
    _rename_windows_handle_relative(
        _windows_descriptor_handle(descriptor),
        parent_handle,
        target_name,
        replace=True,
    )


def _delete_windows_handle(
    handle: object,
    *,
    package_root: Path | None = None,
    parent_parts: tuple[str, ...] = (),
    directory_handles: list[object] | None = None,
) -> None:
    if package_root is not None and directory_handles is not None:
        _assert_windows_directory_chain(
            package_root, parent_parts, directory_handles
        )
    information = _FileDispositionInfo(DeleteFile=True)
    if not _SetFileInformationByHandle(
        handle,
        _FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def _read_regular_file_windows(
    target: Path,
    root: Path,
    relative: Path,
    *,
    max_bytes: int | None,
    root_identity: RootIdentity | None,
) -> bytes:
    directory_handles: list[object] = []
    file_handle: object | None = None
    try:
        parent_parts = tuple(relative.parts[:-1])
        directory_handles = _open_windows_directory_chain(
            root,
            parent_parts,
            create=False,
            root_identity=root_identity,
        )
        _assert_windows_directory_chain(root, parent_parts, directory_handles)
        file_handle, _ = _open_windows_relative_verified(
            directory_handles[-1],
            relative.parts[-1],
            directory=False,
            desired_access=(
                _FILE_READ_DATA | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE_ACCESS
            ),
        )
        _assert_windows_directory_chain(root, parent_parts, directory_handles)
        descriptor = msvcrt.open_osfhandle(
            _windows_handle_value(file_handle),
            os.O_RDONLY | os.O_BINARY,
        )
        file_handle = None
        with os.fdopen(descriptor, "rb") as stream:
            opened_stat = os.fstat(stream.fileno())
            if max_bytes is not None and opened_stat.st_size > max_bytes:
                raise UnsafeFileError(
                    target, "regular file exceeds bounded read limit", kind="limit"
                )
            return _read_bounded_stream(stream, target, max_bytes)
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(target, exc) from exc
    finally:
        if file_handle is not None:
            _CloseHandle(file_handle)
        for handle in reversed(directory_handles):
            _CloseHandle(handle)


def read_regular_file_no_follow(
    path: str | Path,
    root: str | Path,
    *,
    max_bytes: int | None = None,
    root_identity: RootIdentity | None = None,
) -> bytes:
    target, package_root, relative = _contained_relative(path, root)
    if os.name == "nt":
        return _read_regular_file_windows(
            target,
            package_root,
            relative,
            max_bytes=max_bytes,
            root_identity=root_identity,
        )
    return _read_regular_file_posix(
        target,
        package_root,
        relative,
        max_bytes=max_bytes,
        root_identity=root_identity,
    )


@contextmanager
def open_stable_transport_file(
    path: str | Path,
    root: str | Path,
    *,
    root_identity: RootIdentity | None = None,
) -> Iterator[tuple[BinaryIO, str, tuple[int, ...]]]:
    """Hold the verified file object used by a transport subprocess.

    POSIX children receive an inherited descriptor path, so replacing the
    pathname cannot change bytes in flight.  Windows keeps a read-share-only
    handle open, which prevents concurrent replacement while the child reopens
    the advertised path for reading.
    """

    target, package_root, relative = _contained_relative(path, root)
    if os.name == "nt":
        directory_handles: list[object] = []
        file_handle: object | None = None
        stream: BinaryIO | None = None
        try:
            parent_parts = tuple(relative.parts[:-1])
            directory_handles = _open_windows_directory_chain(
                package_root,
                parent_parts,
                create=False,
                root_identity=root_identity,
            )
            _assert_windows_directory_chain(
                package_root, parent_parts, directory_handles
            )
            file_handle, final_path = _open_windows_relative_verified(
                directory_handles[-1],
                relative.parts[-1],
                directory=False,
                desired_access=(
                    _FILE_READ_DATA | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE_ACCESS
                ),
                share_mode=_FILE_SHARE_READ,
            )
            descriptor = msvcrt.open_osfhandle(
                _windows_handle_value(file_handle), os.O_RDONLY | os.O_BINARY
            )
            file_handle = None
            stream = os.fdopen(descriptor, "rb", buffering=0)
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise UnsafeFileError(target, "transport target is not regular")
            yield stream, str(final_path), ()
        finally:
            if stream is not None:
                stream.close()
            if file_handle is not None:
                _CloseHandle(file_handle)
            for handle in reversed(directory_handles):
                _CloseHandle(handle)
        return

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    directory_fds: list[int] = []
    file_fd: int | None = None
    stream: BinaryIO | None = None
    try:
        root_fd = os.open(package_root, directory_flags)
        directory_fds.append(root_fd)
        _require_root_identity(
            _posix_root_identity(os.fstat(root_fd)), root_identity, package_root
        )
        current_fd = root_fd
        for component in relative.parts[:-1]:
            current_fd = os.open(component, directory_flags, dir_fd=current_fd)
            directory_fds.append(current_fd)
        file_fd = os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise UnsafeFileError(target, "transport target is not regular")
        stream = os.fdopen(file_fd, "rb", buffering=0)
        file_fd = None
        descriptor_path = (
            Path("/proc/self/fd")
            if Path("/proc/self/fd").is_dir()
            else Path("/dev/fd")
        ) / str(stream.fileno())
        yield stream, str(descriptor_path), (stream.fileno(),)
    finally:
        if stream is not None:
            stream.close()
        if file_fd is not None:
            os.close(file_fd)
        for descriptor in reversed(directory_fds):
            os.close(descriptor)


def unlink_regular_file_no_follow(
    path: str | Path,
    root: str | Path,
    *,
    root_identity: RootIdentity | None = None,
) -> bool:
    """Unlink one contained regular file without following parent aliases."""

    target, package_root, relative = _contained_relative(path, root)
    if os.name == "nt":
        directory_handles: list[object] = []
        file_handle: object | None = None
        try:
            parent_parts = tuple(relative.parts[:-1])
            directory_handles = _open_windows_directory_chain(
                package_root,
                parent_parts,
                create=False,
                root_identity=root_identity,
            )
            _assert_windows_directory_chain(
                package_root, parent_parts, directory_handles
            )
            try:
                file_handle, _ = _open_windows_relative_verified(
                    directory_handles[-1],
                    relative.parts[-1],
                    directory=False,
                    desired_access=(
                        _FILE_READ_ATTRIBUTES
                        | _DELETE_ACCESS
                        | _SYNCHRONIZE_ACCESS
                    ),
                )
            except FileNotFoundError:
                return False
            _delete_windows_handle(
                file_handle,
                package_root=package_root,
                parent_parts=parent_parts,
                directory_handles=directory_handles,
            )
            return True
        except UnsafeFileError:
            raise
        except OSError as exc:
            raise _unsafe_open_error(target, exc) from exc
        finally:
            if file_handle is not None:
                _CloseHandle(file_handle)
            for handle in reversed(directory_handles):
                _CloseHandle(handle)

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    directory_fds: list[int] = []
    try:
        try:
            root_fd = os.open(package_root, directory_flags)
        except OSError as exc:
            if root_identity is not None:
                raise UnsafeFileError(
                    package_root,
                    "trusted root could not be reopened",
                    kind="escape",
                ) from exc
            raise
        directory_fds.append(root_fd)
        _require_root_identity(
            _posix_root_identity(os.fstat(root_fd)), root_identity, package_root
        )
        current_fd = root_fd
        for component in relative.parts[:-1]:
            current_fd = os.open(component, directory_flags, dir_fd=current_fd)
            directory_fds.append(current_fd)
        try:
            current = os.stat(
                relative.parts[-1],
                dir_fd=current_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode):
            raise UnsafeFileError(target, "unlink target is not a regular file")
        os.unlink(relative.parts[-1], dir_fd=current_fd)
        os.fsync(current_fd)
        return True
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(target, exc) from exc
    finally:
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def verify_sealed_artifact(
    root: str | Path,
    relative_path: str | Path,
    *,
    data: bytes | None = None,
) -> bool:
    package_root = Path(root)
    manifest_path = package_root / "MANIFEST.json"
    if not os.path.lexists(manifest_path):
        return False
    try:
        manifest = json.loads(
            read_regular_file_no_follow(manifest_path, package_root)
        )
    except Exception as exc:
        raise ValueError("sealed artifact manifest is malformed") from exc
    normalized = Path(relative_path).as_posix()
    if (
        not isinstance(manifest, dict)
        or manifest.get("manifest_version") != "1.1"
        or not isinstance(manifest.get("artifacts"), list)
    ):
        raise ValueError("sealed artifact manifest is unsupported")
    matches = [
        item
        for item in manifest["artifacts"]
        if isinstance(item, dict) and item.get("path") == normalized
    ]
    if len(matches) != 1:
        raise ValueError(f"sealed artifact is not uniquely registered: {normalized}")
    content = (
        data
        if data is not None
        else read_regular_file_no_follow(package_root / normalized, package_root)
    )
    record = matches[0]
    if (
        record.get("sha256") != hashlib.sha256(content).hexdigest()
        or record.get("bytes") != len(content)
        or record.get("mode") != logical_mode(normalized)
    ):
        raise ValueError(f"sealed artifact hash mismatch: {normalized}")
    return True


def append_regular_file_no_follow(
    path: str | Path, root: str | Path, content: bytes
) -> None:
    target, package_root, relative = _contained_relative(path, root)
    if os.name == "nt":
        directory_handles: list[object] = []
        file_handle: object | None = None
        try:
            root_handle, final_root = _open_windows_verified(
                package_root, directory=True
            )
            directory_handles.append(root_handle)
            current = package_root
            for component in relative.parts[:-1]:
                current /= component
                handle, final_directory = _open_windows_verified(
                    current, directory=True
                )
                if not _windows_contained(final_directory, final_root):
                    _CloseHandle(handle)
                    raise UnsafeFileError(
                        current, "directory resolves outside the trusted root"
                    )
                directory_handles.append(handle)
            file_handle, final_target = _open_windows_verified(
                target,
                directory=False,
                desired_access=_FILE_APPEND_DATA,
            )
            if not _windows_contained(final_target, final_root):
                raise UnsafeFileError(
                    target, "file resolves outside the trusted root"
                )
            descriptor = msvcrt.open_osfhandle(
                _windows_handle_value(file_handle),
                os.O_APPEND | os.O_WRONLY | os.O_BINARY,
            )
            file_handle = None
            with os.fdopen(descriptor, "ab") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except UnsafeFileError:
            raise
        except OSError as exc:
            raise _unsafe_open_error(target, exc) from exc
        finally:
            if file_handle is not None:
                _CloseHandle(file_handle)
            for handle in reversed(directory_handles):
                _CloseHandle(handle)
        return

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
        file_flags |= os.O_CLOEXEC
    directory_fds: list[int] = []
    file_fd: int | None = None
    try:
        root_fd = os.open(package_root, directory_flags)
        directory_fds.append(root_fd)
        current_fd = root_fd
        for component in relative.parts[:-1]:
            current_fd = os.open(component, directory_flags, dir_fd=current_fd)
            directory_fds.append(current_fd)
        file_fd = os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise UnsafeFileError(target, "target is not a regular file")
        with os.fdopen(file_fd, "ab") as stream:
            file_fd = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(target, exc) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for descriptor in reversed(directory_fds):
            os.close(descriptor)


def canonical_text_bytes(content: str) -> bytes:
    return content.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _atomic_write_checkpoint(target: Path, temporary: Path) -> None:
    """Internal process-death fault-injection seam; production is a no-op."""

    del target, temporary


def _atomic_write_progress_checkpoint(
    target: Path, temporary: Path, written: int, total: int
) -> None:
    """Internal mid-write process-death fault seam; production is a no-op."""

    del target, temporary, written, total


def _write_bytes_atomic_posix(
    target: Path,
    package_root: Path,
    relative: Path,
    content: bytes,
    *,
    root_identity: RootIdentity | None,
    requested_temporary_leaf: str | None,
) -> None:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        file_flags |= os.O_CLOEXEC
    directory_fds: list[int] = []
    temporary_name: str | None = None
    descriptor: int | None = None
    try:
        try:
            root_fd = os.open(package_root, directory_flags)
        except OSError as exc:
            if root_identity is not None:
                raise UnsafeFileError(
                    package_root,
                    "trusted root could not be reopened",
                    kind="escape",
                ) from exc
            raise
        directory_fds.append(root_fd)
        _require_root_identity(
            _posix_root_identity(os.fstat(root_fd)), root_identity, package_root
        )
        current_fd = root_fd
        for component in relative.parts[:-1]:
            try:
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            except FileNotFoundError:
                os.mkdir(component, 0o755, dir_fd=current_fd)
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            directory_fds.append(next_fd)
            current_fd = next_fd
        final_name = relative.parts[-1]
        try:
            current = os.stat(final_name, dir_fd=current_fd, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if current is not None and (
            not stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode)
        ):
            raise UnsafeFileError(target, "atomic target is not a regular file")
        temporary_name = requested_temporary_leaf or (
            f".{final_name}.tmp-{os.getpid()}-"
            f"{next(tempfile._get_candidate_names())}"
        )
        descriptor = os.open(
            temporary_name, file_flags, 0o600, dir_fd=current_fd
        )
        with os.fdopen(descriptor, "wb", buffering=0) as stream:
            descriptor = None
            view = memoryview(content)
            offset = 0
            while offset < len(view):
                written = stream.write(view[offset : offset + 64 * 1024])
                if written is None or written <= 0:
                    raise OSError("atomic temporary write made no progress")
                offset += written
                _atomic_write_progress_checkpoint(
                    target,
                    target.parent / temporary_name,
                    offset,
                    len(view),
                )
            os.fsync(stream.fileno())
        _atomic_write_checkpoint(
            target, target.parent / temporary_name
        )
        os.replace(
            temporary_name,
            final_name,
            src_dir_fd=current_fd,
            dst_dir_fd=current_fd,
        )
        temporary_name = None
        os.fsync(current_fd)
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(target, exc) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name is not None and directory_fds:
            try:
                os.unlink(temporary_name, dir_fd=directory_fds[-1])
            except OSError:
                pass
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def _write_bytes_atomic_windows(
    target: Path,
    package_root: Path,
    relative: Path,
    content: bytes,
    *,
    root_identity: RootIdentity | None,
    requested_temporary_leaf: str | None,
) -> None:
    directory_handles: list[object] = []
    descriptor: int | None = None
    temporary_leaf: str | None = None
    published = False
    try:
        parent_parts = tuple(relative.parts[:-1])
        directory_handles = _open_windows_directory_chain(
            package_root,
            parent_parts,
            create=True,
            root_identity=root_identity,
        )
        _assert_windows_directory_chain(
            package_root, parent_parts, directory_handles
        )
        existing_handle: object | None = None
        try:
            existing_handle, _ = _open_windows_relative_verified(
                directory_handles[-1],
                relative.parts[-1],
                directory=False,
            )
        except FileNotFoundError:
            pass
        finally:
            if existing_handle is not None:
                _CloseHandle(existing_handle)
        descriptor, temporary_leaf = _create_windows_temp_descriptor(
            directory_handles[-1],
            target_name=relative.parts[-1],
            package_root=package_root,
            parent_parts=parent_parts,
            directory_handles=directory_handles,
            requested_leaf=requested_temporary_leaf,
        )
        _write_windows_descriptor(
            descriptor,
            content,
            target=target,
            temporary=target.parent / temporary_leaf,
        )
        _atomic_write_checkpoint(
            target, target.parent / temporary_leaf
        )
        _rename_windows_descriptor(
            descriptor,
            directory_handles[-1],
            relative.parts[-1],
            package_root=package_root,
            parent_parts=parent_parts,
            directory_handles=directory_handles,
        )
        published = True
    except UnsafeFileError:
        raise
    except OSError as exc:
        raise _unsafe_open_error(target, exc) from exc
    finally:
        if descriptor is not None:
            if not published:
                try:
                    descriptor_handle = _windows_descriptor_handle(descriptor)
                    current_leaf = _windows_final_path(descriptor_handle).name
                    if (
                        temporary_leaf is not None
                        and os.path.normcase(current_leaf)
                        == os.path.normcase(temporary_leaf)
                    ):
                        _delete_windows_handle(descriptor_handle)
                except OSError:
                    pass
            os.close(descriptor)
        for handle in reversed(directory_handles):
            _CloseHandle(handle)


def write_bytes_atomic(
    path: str | Path,
    content: bytes,
    *,
    root: str | Path | None = None,
    root_identity: RootIdentity | None = None,
    temporary_path: str | Path | None = None,
) -> None:
    target = Path(path)
    if root is not None:
        target, package_root, relative = _contained_relative(target, root)
        requested_temporary_leaf: str | None = None
        if temporary_path is not None:
            temporary, temporary_root, temporary_relative = _contained_relative(
                temporary_path, root
            )
            if (
                temporary_root != package_root
                or temporary_relative.parent != relative.parent
                or temporary_relative.name == relative.name
            ):
                raise ValueError(
                    "atomic temporary path must be a distinct sibling of its target"
                )
            requested_temporary_leaf = temporary_relative.name
        if os.name == "nt":
            _write_bytes_atomic_windows(
                target,
                package_root,
                relative,
                content,
                root_identity=root_identity,
                requested_temporary_leaf=requested_temporary_leaf,
            )
        else:
            _write_bytes_atomic_posix(
                target,
                package_root,
                relative,
                content,
                root_identity=root_identity,
                requested_temporary_leaf=requested_temporary_leaf,
            )
        return
    if temporary_path is not None:
        raise ValueError("temporary_path requires a rooted atomic write")
    if root_identity is not None:
        raise ValueError("root_identity requires a rooted atomic write")
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


def write_utf8_lf(
    path: str | Path,
    content: str,
    *,
    root: str | Path | None = None,
) -> None:
    write_bytes_atomic(path, canonical_text_bytes(content), root=root)


def _publication_relative_parts(path: str | Path) -> tuple[str, ...]:
    raw = os.fspath(path)
    if not isinstance(raw, str):
        raise TypeError("publication paths must be text")
    normalized = raw.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} or ":" in part for part in relative.parts)
    ):
        raise ValueError("publication path must be a contained relative path")
    return tuple(relative.parts)


def _posix_publication_directory_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_posix_publication_chain(
    root_descriptor: int,
    parts: tuple[str, ...],
    *,
    create: bool,
    mode: int = 0o755,
) -> list[int]:
    descriptors = [os.dup(root_descriptor)]
    try:
        for component in parts:
            created = False
            try:
                descriptor = os.open(
                    component,
                    _posix_publication_directory_flags(),
                    dir_fd=descriptors[-1],
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, mode, dir_fd=descriptors[-1])
                created = True
                descriptor = os.open(
                    component,
                    _posix_publication_directory_flags(),
                    dir_fd=descriptors[-1],
                )
            if created:
                os.fchmod(descriptor, mode)
            descriptors.append(descriptor)
        return descriptors
    except BaseException:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _rename_posix_directory_no_replace(
    parent_descriptor: int, source_name: str, target_name: str
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            parent_descriptor,
            os.fsencode(source_name),
            parent_descriptor,
            os.fsencode(target_name),
            1,
        )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error not in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            raise OSError(error, os.strerror(error), target_name)
    try:
        os.stat(target_name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), target_name)
    os.rename(
        source_name,
        target_name,
        src_dir_fd=parent_descriptor,
        dst_dir_fd=parent_descriptor,
    )


def _discard_posix_directory_contents(descriptor: int) -> None:
    with os.scandir(descriptor) as iterator:
        entries = [
            (entry.name, entry.stat(follow_symlinks=False)) for entry in iterator
        ]
    for name, stat_result in entries:
        if _tree_directory(stat_result):
            child_descriptor = os.open(
                name,
                _posix_publication_directory_flags(),
                dir_fd=descriptor,
            )
            try:
                _discard_posix_directory_contents(child_descriptor)
            finally:
                os.close(child_descriptor)
            os.rmdir(name, dir_fd=descriptor)
        else:
            os.unlink(name, dir_fd=descriptor)
    os.fsync(descriptor)


def _open_windows_publication_chain(
    root_handle: object,
    parts: tuple[str, ...],
    *,
    create: bool,
) -> list[object]:
    handles: list[object] = []
    current = root_handle
    try:
        for component in parts:
            try:
                handle, _ = _open_windows_relative_verified(
                    current,
                    component,
                    directory=True,
                    desired_access=(
                        _FILE_TRAVERSE
                        | _FILE_READ_ATTRIBUTES
                        | _SYNCHRONIZE_ACCESS
                    ),
                )
            except FileNotFoundError:
                if not create:
                    raise
                handle, _ = _open_windows_relative_verified(
                    current,
                    component,
                    directory=True,
                    create=True,
                    desired_access=(
                        _FILE_TRAVERSE
                        | _FILE_READ_ATTRIBUTES
                        | _SYNCHRONIZE_ACCESS
                    ),
                )
            handles.append(handle)
            current = handle
        return handles
    except BaseException:
        for handle in reversed(handles):
            _CloseHandle(handle)
        raise


def _discard_windows_directory_contents(directory_handle: object) -> None:
    directory_path = _windows_final_path(directory_handle)
    with os.scandir(directory_path) as iterator:
        entries = [
            (entry.name, entry.stat(follow_symlinks=False)) for entry in iterator
        ]
    for name, stat_result in entries:
        child_handle: object | None = None
        try:
            if _tree_directory(stat_result):
                child_handle, _ = _open_windows_relative_verified(
                    directory_handle,
                    name,
                    directory=True,
                    desired_access=(
                        _DELETE_ACCESS
                        | _FILE_TRAVERSE
                        | _FILE_READ_ATTRIBUTES
                        | _SYNCHRONIZE_ACCESS
                    ),
                )
                _discard_windows_directory_contents(child_handle)
            else:
                child_handle, _ = _open_windows_relative_verified(
                    directory_handle,
                    name,
                    directory=False,
                    desired_access=(
                        _DELETE_ACCESS
                        | _FILE_READ_ATTRIBUTES
                        | _SYNCHRONIZE_ACCESS
                    ),
                )
            _delete_windows_handle(child_handle)
        finally:
            if child_handle is not None:
                _CloseHandle(child_handle)


class StagedDirectoryPublication:
    """Build and atomically publish one directory through verified handles."""

    def __init__(
        self,
        output_path: Path,
        parent_guard: object,
        staging_guard: object,
        staging_name: str,
        staging_path: Path,
        parent_identity: RootIdentity,
    ) -> None:
        self.output_path = output_path
        self.staging_path = staging_path
        self._parent_path = output_path.parent
        self._parent_guard: object | None = parent_guard
        self._staging_guard: object | None = staging_guard
        self._staging_name = staging_name
        self._parent_identity = parent_identity
        self._published = False
        self._closed = False

    @property
    def staging_root(self) -> "StagedDirectoryPublication":
        """Return the handle-bound root used for all staging I/O."""

        return self

    def _require_writable(self) -> None:
        if self._closed:
            raise RuntimeError("directory publication is closed")
        if self._published:
            raise RuntimeError("directory publication is already published")

    def _verify_named_parent(self) -> None:
        if os.name == "nt":
            reopened: object | None = None
            try:
                reopened, _ = _open_windows_verified(
                    self._parent_path,
                    directory=True,
                    desired_access=(
                        _FILE_TRAVERSE
                        | _FILE_READ_ATTRIBUTES
                        | _SYNCHRONIZE_ACCESS
                    ),
                )
                actual = _windows_root_identity(reopened)
            except (OSError, UnsafeFileError) as exc:
                raise UnsafeFileError(
                    self._parent_path,
                    "publication parent identity changed",
                    kind="escape",
                ) from exc
            finally:
                if reopened is not None:
                    _CloseHandle(reopened)
        else:
            reopened_descriptor: int | None = None
            try:
                reopened_descriptor = os.open(
                    self._parent_path, _posix_publication_directory_flags()
                )
                actual = _posix_root_identity(os.fstat(reopened_descriptor))
            except OSError as exc:
                raise UnsafeFileError(
                    self._parent_path,
                    "publication parent identity changed",
                    kind="escape",
                ) from exc
            finally:
                if reopened_descriptor is not None:
                    os.close(reopened_descriptor)
        _require_root_identity(actual, self._parent_identity, self._parent_path)

    def _validate_staged_tree(self, logical_root: Path) -> None:
        entries = None
        try:
            if os.name == "nt":
                entries = _iter_tree_no_follow_windows(
                    logical_root,
                    max_entries=None,
                    pruned_names=frozenset(),
                    root_share_delete=True,
                )
            else:
                entries = _iter_tree_no_follow_posix(
                    logical_root,
                    max_entries=None,
                    pruned_names=frozenset(),
                    root_descriptor=int(self._staging_guard),
                )
            for path, stat_result in entries:
                if stat.S_ISLNK(stat_result.st_mode) or is_reparse_point(
                    stat_result
                ):
                    raise UnsafeFileError(
                        path,
                        "staged publication contains a symlink or reparse point",
                        kind="symlink",
                    )
                if not (
                    stat.S_ISDIR(stat_result.st_mode)
                    or stat.S_ISREG(stat_result.st_mode)
                ):
                    raise UnsafeFileError(
                        path,
                        "staged publication contains a special file",
                    )
        finally:
            close = getattr(entries, "close", None)
            if close is not None:
                close()

    def ensure_directory(self, relative_path: str | Path, *, mode: int = 0o755) -> None:
        self._require_writable()
        parts = _publication_relative_parts(relative_path)
        if type(mode) is not int or not 0 <= mode <= 0o777:
            raise ValueError("directory mode must be 0o000..0o777")
        if os.name == "nt":
            handles = _open_windows_publication_chain(
                self._staging_guard, parts, create=True
            )
            for handle in reversed(handles):
                _CloseHandle(handle)
            return
        descriptors = _open_posix_publication_chain(
            int(self._staging_guard), parts, create=True, mode=mode
        )
        for descriptor in reversed(descriptors):
            os.close(descriptor)

    def write_bytes(
        self,
        relative_path: str | Path,
        content: bytes,
        *,
        mode: int = 0o600,
    ) -> None:
        self._require_writable()
        parts = _publication_relative_parts(relative_path)
        if not isinstance(content, bytes):
            raise TypeError("publication content must be bytes")
        if type(mode) is not int or not 0 <= mode <= 0o777:
            raise ValueError("file mode must be 0o000..0o777")
        if os.name == "nt":
            self._write_bytes_windows(parts, content)
        else:
            self._write_bytes_posix(parts, content, mode)

    def _write_bytes_posix(
        self, parts: tuple[str, ...], content: bytes, mode: int
    ) -> None:
        descriptors = _open_posix_publication_chain(
            int(self._staging_guard), parts[:-1], create=True
        )
        parent_descriptor = descriptors[-1]
        temporary_name: str | None = None
        file_descriptor: int | None = None
        try:
            try:
                current = os.stat(
                    parts[-1],
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                current = None
            if current is not None and (
                not stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode)
            ):
                raise UnsafeFileError(
                    self.staging_path.joinpath(*parts),
                    "publication target is not a regular file",
                )
            temporary_name = (
                f".{parts[-1]}.tmp-{os.getpid()}-"
                f"{next(tempfile._get_candidate_names())}"
            )
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            file_descriptor = os.open(
                temporary_name,
                flags,
                mode,
                dir_fd=parent_descriptor,
            )
            view = memoryview(content)
            offset = 0
            while offset < len(view):
                written = os.write(
                    file_descriptor, view[offset : offset + 64 * 1024]
                )
                if written <= 0:
                    raise OSError("publication write made no progress")
                offset += written
            os.fchmod(file_descriptor, mode)
            os.fsync(file_descriptor)
            os.close(file_descriptor)
            file_descriptor = None
            os.replace(
                temporary_name,
                parts[-1],
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_name = None
            os.fsync(parent_descriptor)
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
                except OSError:
                    pass
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _write_bytes_windows(
        self, parts: tuple[str, ...], content: bytes
    ) -> None:
        handles = _open_windows_publication_chain(
            self._staging_guard, parts[:-1], create=True
        )
        parent_handle = handles[-1] if handles else self._staging_guard
        descriptor: int | None = None
        temporary_handle: object | None = None
        temporary_name: str | None = None
        published = False
        try:
            existing: object | None = None
            try:
                existing, _ = _open_windows_relative_verified(
                    parent_handle, parts[-1], directory=False
                )
            except FileNotFoundError:
                pass
            finally:
                if existing is not None:
                    _CloseHandle(existing)
            for _ in range(128):
                temporary_name = (
                    f".{parts[-1]}.tmp-{os.getpid()}-"
                    f"{next(tempfile._get_candidate_names())}"
                )
                try:
                    temporary_handle, temporary_path = (
                        _open_windows_relative_verified(
                            parent_handle,
                            temporary_name,
                            directory=False,
                            create=True,
                            desired_access=(
                                _FILE_READ_DATA
                                | _FILE_WRITE_DATA
                                | _FILE_READ_ATTRIBUTES
                                | _DELETE_ACCESS
                                | _SYNCHRONIZE_ACCESS
                            ),
                        )
                    )
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) not in {80, 183}:
                        raise
            else:
                raise FileExistsError(
                    "could not allocate a unique publication temporary file"
                )
            descriptor = msvcrt.open_osfhandle(
                _windows_handle_value(temporary_handle), os.O_RDWR | os.O_BINARY
            )
            temporary_handle = None
            _write_windows_descriptor(
                descriptor,
                content,
                target=self.staging_path.joinpath(*parts),
                temporary=temporary_path,
            )
            _rename_windows_handle_relative(
                _windows_descriptor_handle(descriptor),
                parent_handle,
                parts[-1],
                replace=True,
            )
            published = True
        finally:
            if temporary_handle is not None:
                _CloseHandle(temporary_handle)
            if descriptor is not None:
                if not published:
                    try:
                        _delete_windows_handle(
                            _windows_descriptor_handle(descriptor)
                        )
                    except OSError:
                        pass
                os.close(descriptor)
            for handle in reversed(handles):
                _CloseHandle(handle)

    def publish(self) -> Path:
        self._require_writable()
        self._verify_named_parent()
        self._validate_staged_tree(self.staging_path)
        if os.name == "nt":
            try:
                _rename_windows_handle_relative(
                    self._staging_guard,
                    self._parent_guard,
                    self.output_path.name,
                    replace=False,
                )
            except OSError as exc:
                if os.path.lexists(self.output_path):
                    raise FileExistsError(
                        errno.EEXIST,
                        os.strerror(errno.EEXIST),
                        self.output_path,
                    ) from exc
                raise
            try:
                self._verify_named_parent()
                self._validate_staged_tree(self.output_path)
            except BaseException:
                _rename_windows_handle_relative(
                    self._staging_guard,
                    self._parent_guard,
                    self._staging_name,
                    replace=False,
                )
                raise
        else:
            _rename_posix_directory_no_replace(
                int(self._parent_guard),
                self._staging_name,
                self.output_path.name,
            )
            os.fsync(int(self._parent_guard))
            try:
                self._verify_named_parent()
                self._validate_staged_tree(self.output_path)
            except BaseException:
                os.rename(
                    self.output_path.name,
                    self._staging_name,
                    src_dir_fd=int(self._parent_guard),
                    dst_dir_fd=int(self._parent_guard),
                )
                raise
        self._published = True
        return self.output_path

    def close(self) -> None:
        if self._closed:
            return
        try:
            if not self._published and self._staging_guard is not None:
                if os.name == "nt":
                    _discard_windows_directory_contents(self._staging_guard)
                    _delete_windows_handle(self._staging_guard)
                else:
                    _discard_posix_directory_contents(int(self._staging_guard))
                    expected = _posix_root_identity(
                        os.fstat(int(self._staging_guard))
                    )
                    current = os.stat(
                        self._staging_name,
                        dir_fd=int(self._parent_guard),
                        follow_symlinks=False,
                    )
                    _require_root_identity(
                        _posix_root_identity(current),
                        expected,
                        self.staging_path,
                    )
                    os.rmdir(
                        self._staging_name, dir_fd=int(self._parent_guard)
                    )
                    os.fsync(int(self._parent_guard))
        finally:
            if self._staging_guard is not None:
                if os.name == "nt":
                    _CloseHandle(self._staging_guard)
                else:
                    os.close(int(self._staging_guard))
                self._staging_guard = None
            if self._parent_guard is not None:
                if os.name == "nt":
                    _CloseHandle(self._parent_guard)
                else:
                    os.close(int(self._parent_guard))
                self._parent_guard = None
            self._closed = True


@contextmanager
def staged_directory_publication(
    output_path: str | Path,
) -> Iterator[StagedDirectoryPublication]:
    """Create a private sibling tree and publish it through one parent guard."""

    output = Path(os.path.abspath(output_path))
    if not output.name:
        raise ValueError("publication output must name one directory")
    parent = output.parent
    parent_guard: object | None = None
    staging_guard: object | None = None
    staging_name: str | None = None
    publication: StagedDirectoryPublication | None = None
    try:
        if os.name == "nt":
            parent_guard, _ = _open_windows_verified(
                parent,
                directory=True,
                desired_access=(
                    _FILE_TRAVERSE
                    | _FILE_READ_ATTRIBUTES
                    | _SYNCHRONIZE_ACCESS
                ),
                share_delete=False,
            )
            parent_identity = _windows_root_identity(parent_guard)
            if os.path.lexists(output):
                raise FileExistsError(
                    errno.EEXIST, os.strerror(errno.EEXIST), output
                )
            for _ in range(128):
                staging_name = (
                    f".{output.name}.stage-{os.getpid()}-"
                    f"{next(tempfile._get_candidate_names())}"
                )
                try:
                    staging_guard, staging_path = _open_windows_relative_verified(
                        parent_guard,
                        staging_name,
                        directory=True,
                        create=True,
                        desired_access=(
                            _DELETE_ACCESS
                            | _FILE_TRAVERSE
                            | _FILE_READ_ATTRIBUTES
                            | _SYNCHRONIZE_ACCESS
                        ),
                        share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
                    )
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) not in {80, 183}:
                        raise
            else:
                raise FileExistsError(
                    "could not allocate a unique publication directory"
                )
        else:
            parent_guard = os.open(parent, _posix_publication_directory_flags())
            parent_identity = _posix_root_identity(os.fstat(parent_guard))
            try:
                os.stat(
                    output.name,
                    dir_fd=parent_guard,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(
                    errno.EEXIST, os.strerror(errno.EEXIST), output
                )
            for _ in range(128):
                staging_name = (
                    f".{output.name}.stage-{os.getpid()}-"
                    f"{next(tempfile._get_candidate_names())}"
                )
                try:
                    os.mkdir(staging_name, 0o700, dir_fd=parent_guard)
                    staging_guard = os.open(
                        staging_name,
                        _posix_publication_directory_flags(),
                        dir_fd=parent_guard,
                    )
                    break
                except FileExistsError:
                    continue
            else:
                raise FileExistsError(
                    "could not allocate a unique publication directory"
                )
            staging_path = parent / staging_name
        publication = StagedDirectoryPublication(
            output,
            parent_guard,
            staging_guard,
            staging_name,
            staging_path,
            parent_identity,
        )
        parent_guard = None
        staging_guard = None
        yield publication
    finally:
        if publication is not None:
            publication.close()
        else:
            if staging_guard is not None:
                if os.name == "nt":
                    try:
                        _discard_windows_directory_contents(staging_guard)
                        _delete_windows_handle(staging_guard)
                    finally:
                        _CloseHandle(staging_guard)
                else:
                    os.close(int(staging_guard))
            if parent_guard is not None:
                if os.name == "nt":
                    _CloseHandle(parent_guard)
                else:
                    os.close(int(parent_guard))


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


@contextmanager
def _open_contained_lock_file(
    path: str | Path,
    root: str | Path,
    *,
    root_identity: RootIdentity | None = None,
    create: bool = False,
) -> Iterator[BinaryIO]:
    target, package_root, relative = _contained_relative(path, root)
    if os.name == "nt":
        directory_handles: list[object] = []
        file_handle: object | None = None
        descriptor: int | None = None
        stream: BinaryIO | None = None
        try:
            try:
                root_handle, final_root = _open_windows_verified(
                    package_root, directory=True
                )
                if root_identity is not None:
                    _require_root_identity(
                        _windows_root_identity(root_handle),
                        root_identity,
                        package_root,
                    )
                directory_handles.append(root_handle)
                current = package_root
                for component in relative.parts[:-1]:
                    current /= component
                    handle, final_directory = _open_windows_verified(
                        current, directory=True
                    )
                    if not _windows_contained(final_directory, final_root):
                        _CloseHandle(handle)
                        raise UnsafeFileError(
                            current,
                            "lock directory resolves outside the trusted root",
                        )
                    directory_handles.append(handle)
                parent_parts = tuple(relative.parts[:-1])
                _assert_windows_directory_chain(
                    package_root, parent_parts, directory_handles
                )
                try:
                    before = target.lstat()
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or stat.S_ISLNK(before.st_mode)
                        or is_reparse_point(before)
                    ):
                        raise UnsafeFileError(
                            target, "lock path is not a regular file"
                        )
                    descriptor = os.open(
                        target, os.O_RDWR | os.O_BINARY
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        file_handle, _ = _open_windows_relative_verified(
                            directory_handles[-1],
                            relative.parts[-1],
                            create_if_missing=True,
                            directory=False,
                            desired_access=(
                                _FILE_READ_DATA
                                | _FILE_WRITE_DATA
                                | _FILE_READ_ATTRIBUTES
                                | _SYNCHRONIZE_ACCESS
                            ),
                            share_mode=(
                                _FILE_SHARE_READ
                                | _FILE_SHARE_WRITE
                                | _FILE_SHARE_DELETE
                            ),
                        )
                        descriptor = msvcrt.open_osfhandle(
                            _windows_handle_value(file_handle),
                            os.O_RDWR | os.O_BINARY,
                        )
                        file_handle = None
                    except PermissionError:
                        descriptor = os.open(
                            target, os.O_RDWR | os.O_BINARY
                        )
                opened = os.fstat(descriptor)
                current = target.lstat()
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or not stat.S_ISREG(current.st_mode)
                    or stat.S_ISLNK(current.st_mode)
                    or is_reparse_point(current)
                    or (opened.st_dev, opened.st_ino)
                    != (current.st_dev, current.st_ino)
                ):
                    raise UnsafeFileError(
                        target, "lock path changed while opening"
                    )
                final_target = _windows_final_path(
                    msvcrt.get_osfhandle(descriptor)
                )
                _assert_windows_directory_chain(
                    package_root, parent_parts, directory_handles
                )
                if not _windows_contained(final_target, final_root):
                    raise UnsafeFileError(
                        target, "lock file resolves outside the trusted root"
                    )
                stream = os.fdopen(descriptor, "r+b", buffering=0)
                descriptor = None
                opened_size = os.fstat(stream.fileno()).st_size
                if opened_size == 0 and create:
                    stream.write(b"\0")
                    stream.flush()
                    os.fsync(stream.fileno())
                elif opened_size != 1:
                    raise UnsafeFileError(target, "lock file must contain one byte")
            except UnsafeFileError:
                raise
            except OSError as exc:
                raise _unsafe_open_error(target, exc) from exc
            yield stream
        finally:
            if stream is not None:
                stream.close()
            if descriptor is not None:
                os.close(descriptor)
            if file_handle is not None:
                _CloseHandle(file_handle)
            for handle in reversed(directory_handles):
                _CloseHandle(handle)
        return

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDWR | os.O_NOFOLLOW
    if create:
        file_flags |= os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
        file_flags |= os.O_CLOEXEC
    directory_fds: list[int] = []
    file_fd: int | None = None
    stream: BinaryIO | None = None
    try:
        try:
            root_fd = os.open(package_root, directory_flags)
            directory_fds.append(root_fd)
            if root_identity is not None:
                _require_root_identity(
                    _posix_root_identity(os.fstat(root_fd)),
                    root_identity,
                    package_root,
                )
            current_fd = root_fd
            for component in relative.parts[:-1]:
                current_fd = os.open(component, directory_flags, dir_fd=current_fd)
                directory_fds.append(current_fd)
            file_fd = os.open(
                relative.parts[-1],
                file_flags,
                0o644,
                dir_fd=current_fd,
            )
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise UnsafeFileError(
                    target, "lock file must be a one-byte regular file"
                )
            stream = os.fdopen(file_fd, "r+b", buffering=0)
            file_fd = None
            if opened.st_size == 0 and create:
                stream.write(b"\0")
                stream.flush()
                os.fsync(stream.fileno())
            elif opened.st_size != 1:
                raise UnsafeFileError(
                    target, "lock file must be a one-byte regular file"
                )
        except UnsafeFileError:
            raise
        except OSError as exc:
            if root_identity is not None:
                try:
                    _require_root_identity(
                        capture_root_identity(package_root),
                        root_identity,
                        package_root,
                    )
                except UnsafeFileError as root_exc:
                    raise root_exc from exc
            raise _unsafe_open_error(target, exc) from exc
        yield stream
    finally:
        if stream is not None:
            stream.close()
        if file_fd is not None:
            os.close(file_fd)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


@contextmanager
def _open_lock_stream(
    path: Path,
    root: str | Path | None,
    *,
    root_identity: RootIdentity | None = None,
    create: bool = False,
) -> Iterator[BinaryIO]:
    if root is not None:
        with _open_contained_lock_file(
            path,
            root,
            root_identity=root_identity,
            create=create,
        ) as stream:
            yield stream
        return
    if root_identity is not None:
        raise ValueError("root_identity requires a rooted package lock")
    stream = _open_lock_file(path)
    try:
        yield stream
    finally:
        stream.close()


def package_operation_lock_path(root: str | Path) -> Path:
    package_root = Path(root).resolve(strict=False)
    return package_root.parent / f".{package_root.name}.operation.lock"


def package_namespace_lock_path(root: str | Path) -> Path:
    return package_operation_lock_path(root)


def package_identity_lock_path(root: str | Path) -> Path:
    package_root = Path(root).resolve(strict=False)
    return package_root / "runtime" / "operation.lock"


def delivery_reservation_path(root: str | Path, kind: str) -> Path:
    if kind not in DELIVERY_RESERVATION_KINDS:
        raise ValueError("unsupported delivery reservation kind")
    package_root = Path(root).resolve(strict=False)
    name = (
        "review-delivery-reservation.json"
        if kind == "review-md-files"
        else "final-delivery-reservation.json"
    )
    return package_root / "runtime" / name


def delivery_reservation_pending_path(root: str | Path, kind: str) -> Path:
    reservation = delivery_reservation_path(root, kind)
    return reservation.with_name(f"{reservation.stem}.pending.json")


def delivery_receipt_pending_path(root: str | Path, kind: str) -> Path:
    if kind not in DELIVERY_RESERVATION_KINDS:
        raise ValueError("unsupported delivery reservation kind")
    package_root = Path(root).resolve(strict=False)
    name = (
        "review-md-files-delivery-receipt.pending.json"
        if kind == "review-md-files"
        else "final-artifacts-delivery-receipt.pending.json"
    )
    return package_root / "out" / name


def pending_delivery_reservation_paths(root: str | Path) -> list[Path]:
    return [
        path
        for kind in sorted(DELIVERY_RESERVATION_KINDS)
        if os.path.lexists(path := delivery_reservation_path(root, kind))
    ]


def delivery_transaction_paths(root: str | Path, kind: str) -> tuple[Path, ...]:
    return (
        delivery_reservation_path(root, kind),
        delivery_reservation_pending_path(root, kind),
        delivery_receipt_pending_path(root, kind),
    )


def pending_delivery_transaction_paths(root: str | Path) -> list[Path]:
    return [
        path
        for kind in sorted(DELIVERY_RESERVATION_KINDS)
        for path in delivery_transaction_paths(root, kind)
        if os.path.lexists(path)
    ]


def assert_no_pending_delivery_reservations(
    root: str | Path, *, allow_kind: str | None = None
) -> None:
    allowed = (
        {
            os.path.normcase(str(path))
            for path in delivery_transaction_paths(root, allow_kind)
        }
        if allow_kind is not None
        else set()
    )
    pending = [
        path
        for path in pending_delivery_transaction_paths(root)
        if os.path.normcase(str(path)) not in allowed
    ]
    if pending:
        raise ValueError(
            "SGV-DELIVERY-SEND-PENDING: a delivery reservation must be recorded or cancelled first"
        )


@contextmanager
def package_operation_lock(
    root: str | Path,
    *,
    timeout: float = 10.0,
    retry_interval: float = 0.05,
    expected_root_identity: RootIdentity | None = None,
    expected_namespace_root_identity: RootIdentity | None = None,
) -> Iterator[None]:
    if (expected_root_identity is None) != (
        expected_namespace_root_identity is None
    ):
        raise ValueError(
            "expected identities must be supplied together"
        )
    package_root = (
        Path(os.path.abspath(os.fspath(root)))
        if expected_root_identity is not None
        else Path(root).resolve(strict=False)
    )
    if expected_namespace_root_identity is not None:
        namespace_root = package_root.parent
        namespace_lock = namespace_root / f".{package_root.name}.operation.lock"
        namespace_context = package_lock(
            namespace_lock,
            root=namespace_root,
            root_identity=expected_namespace_root_identity,
            create=True,
            timeout=timeout,
            retry_interval=retry_interval,
        )
    else:
        namespace_lock = package_operation_lock_path(package_root)
        namespace_context = package_lock(
            namespace_lock,
            timeout=timeout,
            retry_interval=retry_interval,
        )
    with namespace_context:
        if expected_root_identity is not None:
            _require_root_identity(
                capture_root_identity(package_root),
                expected_root_identity,
                package_root,
            )
        if not (
            package_root.is_dir() and (package_root / "MANIFEST.json").is_file()
        ):
            yield
            return
        active_identity = (
            expected_root_identity or capture_root_identity(package_root)
        )
        identity_lock = package_identity_lock_path(package_root)
        if not os.path.lexists(identity_lock):
            write_bytes_atomic(
                identity_lock,
                b"\0",
                root=package_root,
                root_identity=active_identity,
            )
        with package_lock(
            identity_lock,
            root=package_root,
            root_identity=active_identity,
            timeout=timeout,
            retry_interval=retry_interval,
        ):
            _require_root_identity(
                capture_root_identity(package_root),
                active_identity,
                package_root,
            )
            yield


@contextmanager
def package_namespace_lock(
    root: str | Path,
    *,
    timeout: float = 10.0,
    retry_interval: float = 0.05,
) -> Iterator[None]:
    """Serialize operations that may replace the package directory itself."""

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
    root: str | Path | None = None,
    root_identity: RootIdentity | None = None,
    create: bool = False,
    timeout: float = 10.0,
    retry_interval: float = 0.05,
) -> Iterator[None]:
    lock_path = Path(path)
    with _open_lock_stream(
        lock_path,
        root,
        root_identity=root_identity,
        create=create,
    ) as stream:
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
                    size_before = os.fstat(stream.fileno()).st_size
                    stream.seek(0)
                    lock_byte = stream.read(1)
                    size_after = os.fstat(stream.fileno()).st_size
                    if size_before != 1 or size_after != 1:
                        raise UnsafeFileError(
                            lock_path, "lock file must contain one byte"
                        )
                    if lock_byte != b"\0":
                        raise UnsafeFileError(
                            lock_path, "lock file byte is invalid"
                        )
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
            if acquired:
                _release(stream)
