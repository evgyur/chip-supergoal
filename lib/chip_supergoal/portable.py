from __future__ import annotations

from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
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
    "delivery/review-md-files-delivery-receipt.schema.json",
)
RUNTIME_SPEC_FILES = (
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
    desired_access: int | None = None,
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
    status = _NtCreateFile(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(attributes),
        ctypes.byref(status_block),
        None,
        _FILE_ATTRIBUTE_NORMAL if create and not directory else 0,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        _FILE_CREATE if create else _FILE_OPEN,
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
            reopened, _ = _open_windows_verified(path, directory=True)
            if _windows_file_identity(reopened) != _windows_file_identity(
                expected_handle
            ):
                raise UnsafeFileError(path, "directory identity changed during operation")
        finally:
            if reopened is not None:
                _CloseHandle(reopened)


def _open_windows_directory_chain(
    package_root: Path,
    parent_parts: tuple[str, ...],
    *,
    create: bool,
) -> list[object]:
    """Open a root-bound parent chain without resolving child path strings."""

    handles: list[object] = []
    root_handle, _ = _open_windows_verified(
        package_root,
        directory=True,
        desired_access=(
            _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE_ACCESS
        ),
    )
    handles.append(root_handle)
    try:
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
) -> tuple[int, str]:
    """Create a sibling temporary file while the verified parent stays open."""

    for _ in range(128):
        _assert_windows_directory_chain(
            package_root, parent_parts, directory_handles
        )
        leaf = (
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


def _write_windows_descriptor(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            raise OSError("atomic temporary write made no progress")
        offset += written
    os.fsync(descriptor)


def _rename_windows_descriptor(
    descriptor: int,
    parent_handle: object,
    target_name: str,
    *,
    package_root: Path,
    parent_parts: tuple[str, ...],
    directory_handles: list[object],
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
    information.ReplaceIfExists = 1
    # The target directory is the already verified handle; no mutable path is
    # resolved during publication.
    information.RootDirectory = wintypes.HANDLE(
        _windows_handle_value(parent_handle)
    )
    information.FileNameLength = len(encoded)
    ctypes.memmove(
        ctypes.addressof(buffer) + filename_offset, encoded, len(encoded)
    )
    _assert_windows_directory_chain(
        package_root, parent_parts, directory_handles
    )
    status_block = _IoStatusBlock()
    status = _NtSetInformationFile(
        _windows_descriptor_handle(descriptor),
        ctypes.byref(status_block),
        ctypes.byref(buffer),
        size,
        _FILE_RENAME_INFORMATION_CLASS_NT,
    )
    if status < 0:
        _raise_windows_ntstatus(status)


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


def unlink_regular_file_no_follow(path: str | Path, root: str | Path) -> bool:
    """Unlink one contained regular file without following parent aliases."""

    target, package_root, relative = _contained_relative(path, root)
    if os.name == "nt":
        directory_handles: list[object] = []
        file_handle: object | None = None
        try:
            parent_parts = tuple(relative.parts[:-1])
            directory_handles = _open_windows_directory_chain(
                package_root, parent_parts, create=False
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
        root_fd = os.open(package_root, directory_flags)
        directory_fds.append(root_fd)
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


def _write_bytes_atomic_posix(
    target: Path, package_root: Path, relative: Path, content: bytes
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
        root_fd = os.open(package_root, directory_flags)
        directory_fds.append(root_fd)
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
        temporary_name = (
            f".{final_name}.tmp-{os.getpid()}-"
            f"{next(tempfile._get_candidate_names())}"
        )
        descriptor = os.open(
            temporary_name, file_flags, 0o600, dir_fd=current_fd
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
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
    target: Path, package_root: Path, relative: Path, content: bytes
) -> None:
    directory_handles: list[object] = []
    descriptor: int | None = None
    temporary_leaf: str | None = None
    published = False
    try:
        parent_parts = tuple(relative.parts[:-1])
        directory_handles = _open_windows_directory_chain(
            package_root, parent_parts, create=True
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
        )
        _write_windows_descriptor(descriptor, content)
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
) -> None:
    target = Path(path)
    if root is not None:
        target, package_root, relative = _contained_relative(target, root)
        if os.name == "nt":
            _write_bytes_atomic_windows(
                target, package_root, relative, content
            )
        else:
            _write_bytes_atomic_posix(
                target, package_root, relative, content
            )
        return
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
    path: str | Path, root: str | Path
) -> Iterator[BinaryIO]:
    target, package_root, relative = _contained_relative(path, root)
    if os.name == "nt":
        directory_handles: list[object] = []
        file_handle: object | None = None
        stream: BinaryIO | None = None
        try:
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
                            current,
                            "lock directory resolves outside the trusted root",
                        )
                    directory_handles.append(handle)
                file_handle, final_target = _open_windows_verified(
                    target,
                    directory=False,
                    desired_access=_GENERIC_READ | _GENERIC_WRITE,
                    share_delete=False,
                )
                if not _windows_contained(final_target, final_root):
                    raise UnsafeFileError(
                        target, "lock file resolves outside the trusted root"
                    )
                descriptor = msvcrt.open_osfhandle(
                    _windows_handle_value(file_handle), os.O_RDWR | os.O_BINARY
                )
                file_handle = None
                stream = os.fdopen(descriptor, "r+b", buffering=0)
                if os.fstat(stream.fileno()).st_size != 1:
                    raise UnsafeFileError(target, "lock file must contain one byte")
                stream.seek(0)
                if stream.read(1) != b"\0":
                    raise UnsafeFileError(target, "lock file byte is invalid")
            except UnsafeFileError:
                raise
            except OSError as exc:
                raise _unsafe_open_error(target, exc) from exc
            yield stream
        finally:
            if stream is not None:
                stream.close()
            if file_handle is not None:
                _CloseHandle(file_handle)
            for handle in reversed(directory_handles):
                _CloseHandle(handle)
        return

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDWR | os.O_NOFOLLOW
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
            current_fd = root_fd
            for component in relative.parts[:-1]:
                current_fd = os.open(component, directory_flags, dir_fd=current_fd)
                directory_fds.append(current_fd)
            file_fd = os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size != 1:
                raise UnsafeFileError(
                    target, "lock file must be a one-byte regular file"
                )
            stream = os.fdopen(file_fd, "r+b", buffering=0)
            file_fd = None
            stream.seek(0)
            if stream.read(1) != b"\0":
                raise UnsafeFileError(target, "lock file byte is invalid")
        except UnsafeFileError:
            raise
        except OSError as exc:
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
    path: Path, root: str | Path | None
) -> Iterator[BinaryIO]:
    if root is not None:
        with _open_contained_lock_file(path, root) as stream:
            yield stream
        return
    stream = _open_lock_file(path)
    try:
        yield stream
    finally:
        stream.close()


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
    root: str | Path | None = None,
    timeout: float = 10.0,
    retry_interval: float = 0.05,
) -> Iterator[None]:
    lock_path = Path(path)
    with _open_lock_stream(lock_path, root) as stream:
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
            if acquired:
                _release(stream)
