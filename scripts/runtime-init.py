#!/usr/bin/env python3
"""No-follow, owner-bound initialization of mutable SuperGoal runtime state."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import sys
from pathlib import Path

REQUIRED = ("PLAN.md", "TODO.md", "MEMORY.md", "STATUS.md", "RUN_LOG.md", "CHECKS.md", "REVIEW.md")


def fail(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, sort_keys=True), file=sys.stderr)
    raise SystemExit(2)


def check_owned_dir(path: Path, *, max_mode: int) -> None:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        fail(f"unsafe directory: {path}")
    if st.st_uid != os.getuid():
        fail(f"directory owner mismatch: {path}")
    if stat.S_IMODE(st.st_mode) & ~max_mode:
        fail(f"directory mode is too broad: {path} mode={stat.S_IMODE(st.st_mode):04o}")


def open_dir(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def mkdir_at(parent_fd: int, name: str, mode: int) -> None:
    try:
        os.mkdir(name, mode=mode, dir_fd=parent_fd)
    except FileExistsError:
        pass


def copy_exclusive(src: Path, runtime_fd: int, name: str) -> bool:
    st = os.lstat(src)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        fail(f"unsafe runtime seed: {src}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, 0o600, dir_fd=runtime_fd)
    except FileExistsError:
        existing = os.stat(name, dir_fd=runtime_fd, follow_symlinks=False)
        if not stat.S_ISREG(existing.st_mode) or existing.st_uid != os.getuid() or stat.S_IMODE(existing.st_mode) & 0o077:
            fail(f"unsafe existing runtime file: {name}")
        return False
    try:
        with src.open("rb") as fh:
            while True:
                block = fh.read(1 << 20)
                if not block:
                    break
                os.write(fd, block)
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: runtime-init.py <package-root>")
    raw = Path(sys.argv[1])
    root = raw.resolve(strict=True)
    if raw.is_symlink() or not root.is_dir():
        fail("package root must be a real directory")
    check_owned_dir(root, max_mode=0o755)
    seed = root / "runtime-seed"
    check_owned_dir(seed, max_mode=0o755)

    root_fd = open_dir(root)
    try:
        mkdir_at(root_fd, "out", 0o700)
        out = root / "out"
        check_owned_dir(out, max_mode=0o700)
        out_fd = open_dir(out)
        try:
            mkdir_at(out_fd, "runtime", 0o700)
            runtime = out / "runtime"
            check_owned_dir(runtime, max_mode=0o700)
            lock_flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                lock_flags |= os.O_NOFOLLOW
            lock_fd = os.open(".runtime-init.lock", lock_flags, 0o600, dir_fd=out_fd)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                runtime_fd = open_dir(runtime)
                try:
                    created = [name for name in REQUIRED if copy_exclusive(seed / name, runtime_fd, name)]
                    os.fsync(runtime_fd)
                finally:
                    os.close(runtime_fd)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
        finally:
            os.close(out_fd)
    finally:
        os.close(root_fd)
    print(json.dumps({"ok": True, "status": "initialized" if created else "already initialized", "runtime": str(root / "out" / "runtime"), "created": created}, sort_keys=True))


if __name__ == "__main__":
    main()
