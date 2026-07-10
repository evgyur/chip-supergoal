from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import tempfile
import time
from typing import BinaryIO, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


EXECUTABLE_WRAPPERS = frozenset(
    {
        "scripts/validate-loop-design.sh",
        "scripts/validate-phase.sh",
    }
)


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
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    stream = os.fdopen(descriptor, "r+b", buffering=0)
    try:
        if os.fstat(descriptor).st_size == 0:
            stream.seek(0)
            stream.write(b"\0")
            stream.flush()
            os.fsync(descriptor)
        return stream
    except BaseException:
        stream.close()
        raise


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
