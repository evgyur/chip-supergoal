#!/usr/bin/env python3
"""Atomic run-wide execution lease for compiled SuperGoal packages."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import stat
import sys
import time
from pathlib import Path


def fail(message: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": message}, sort_keys=True), file=sys.stderr)
    raise SystemExit(code)


def safe_root(raw: str) -> Path:
    root = Path(raw).resolve(strict=True)
    if not root.is_dir() or Path(raw).is_symlink():
        fail("package root must be a real directory")
    return root


def paths(root: Path, token_file_arg: str | None) -> tuple[Path, Path, Path]:
    out = root / "out"
    runtime = out / "runtime"
    lease = out / ".execution-lease"
    token_file = Path(token_file_arg).resolve() if token_file_arg else runtime / ".execution-lease-token"
    if not token_file.is_relative_to(runtime.resolve()):
        fail("token file must stay under out/runtime")
    return runtime, lease, token_file


def read_regular(path: Path) -> bytes:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        fail(f"unsafe file: {path}")
    return path.read_bytes()


def write_exclusive(path: Path, data: bytes, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    write_exclusive(tmp, data, mode)
    os.replace(tmp, path)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def process_identity(pid: int) -> dict | None:
    if pid <= 1:
        return None
    proc = Path("/proc") / str(pid)
    try:
        st = os.stat(proc)
        if st.st_uid != os.getuid():
            return None
        fields = (proc / "stat").read_text().split()
        start_time = int(fields[21])
        executable = str((proc / "exe").resolve(strict=True))
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
        return None
    return {"pid": pid, "start_time": start_time, "executable": executable, "uid": st.st_uid}


def load_token(token_file: Path) -> str:
    token = read_regular(token_file).decode().strip()
    if len(token) < 32:
        fail("lease token is missing or malformed")
    return token


def load_owner(lease: Path) -> dict:
    if lease.is_symlink() or not lease.is_dir():
        fail("execution lease directory is missing or unsafe")
    try:
        return json.loads(read_regular(lease / "owner.json"))
    except Exception as exc:
        fail(f"lease owner receipt is malformed: {exc}")


def verify(lease: Path, token_file: Path, owner_label: str) -> tuple[str, dict]:
    token = load_token(token_file)
    owner = load_owner(lease)
    if owner.get("token_sha256") != token_hash(token):
        fail("execution lease is owned by another token")
    if owner.get("owner_session_sha256") != hashlib.sha256(owner_label.encode()).hexdigest():
        fail("execution lease is owned by another Hermes session")
    expected = owner.get("owner_process")
    if not isinstance(expected, dict) or process_identity(int(expected.get("pid", 0))) != expected:
        fail("execution lease owner process is no longer live with the recorded identity; recover before resuming")
    return token, owner


def acquire(root: Path, owner_label: str, owner_pid: int, token_file_arg: str | None) -> None:
    runtime, lease, token_file = paths(root, token_file_arg)
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    if runtime.is_symlink():
        fail("runtime directory must not be a symlink")
    owner_process = process_identity(owner_pid)
    if owner_process is None:
        fail("owner PID must name a live same-UID process")
    token = secrets.token_urlsafe(48)
    now = int(time.time())
    try:
        os.mkdir(lease, 0o700)
    except FileExistsError:
        fail("execution lease already exists; use check with the existing private token or recover a proven-stale lease")
    try:
        receipt = {
            "version": 1,
            "goal_root": str(root),
            "owner_session_sha256": hashlib.sha256(owner_label.encode()).hexdigest(),
            "owner_process": owner_process,
            "token_sha256": token_hash(token),
            "acquired_at": now,
            "heartbeat_at": now,
            "hostname": socket.gethostname(),
            "acquire_pid": os.getpid(),
        }
        write_exclusive(lease / "owner.json", (json.dumps(receipt, sort_keys=True) + "\n").encode())
        write_exclusive(token_file, (token + "\n").encode())
    except Exception:
        shutil.rmtree(lease, ignore_errors=True)
        try:
            token_file.unlink()
        except FileNotFoundError:
            pass
        raise
    print(json.dumps({"ok": True, "status": "acquired", "token_file": str(token_file), "owner_hash": receipt["token_sha256"]}, sort_keys=True))


def check_or_refresh(root: Path, token_file_arg: str | None, owner_label: str, refresh: bool) -> None:
    _, lease, token_file = paths(root, token_file_arg)
    token, owner = verify(lease, token_file, owner_label)
    if refresh:
        owner["heartbeat_at"] = int(time.time())
        owner["refresh_pid"] = os.getpid()
        write_atomic(lease / "owner.json", (json.dumps(owner, sort_keys=True) + "\n").encode())
    print(json.dumps({"ok": True, "status": "refreshed" if refresh else "owned", "owner_hash": token_hash(token), "heartbeat_at": owner.get("heartbeat_at")}, sort_keys=True))


def release(root: Path, token_file_arg: str | None, owner_label: str) -> None:
    runtime, lease, token_file = paths(root, token_file_arg)
    token, owner = verify(lease, token_file, owner_label)
    tomb = runtime.parent / f".execution-lease.released-{token_hash(token)[:12]}-{int(time.time())}"
    os.replace(lease, tomb)
    shutil.rmtree(tomb)
    token_file.unlink()
    print(json.dumps({"ok": True, "status": "released", "owner_hash": owner["token_sha256"]}, sort_keys=True))


def recover(root: Path, token_file_arg: str | None, after_seconds: int, reason: str) -> None:
    runtime, lease, token_file = paths(root, token_file_arg)
    owner = load_owner(lease)
    expected = owner.get("owner_process")
    if not isinstance(expected, dict):
        fail("lease owner process identity is missing; authenticated manual takeover is required")
    current = process_identity(int(expected.get("pid", 0)))
    if current == expected:
        fail("lease owner process is still live; takeover denied")
    age = int(time.time()) - int(owner.get("heartbeat_at", 0))
    if after_seconds < 300 or age < after_seconds:
        fail(f"lease is not proven stale: age={age}s threshold={after_seconds}s")
    receipt = {
        "version": 1,
        "recovered_at": int(time.time()),
        "stale_age_seconds": age,
        "reason": reason,
        "prior_owner": owner,
    }
    recovery_path = runtime / f"execution-lease-recovery-{receipt['recovered_at']}.json"
    write_exclusive(recovery_path, (json.dumps(receipt, sort_keys=True) + "\n").encode())
    tomb = runtime.parent / f".execution-lease.recovered-{int(time.time())}"
    os.replace(lease, tomb)
    shutil.rmtree(tomb)
    try:
        token_file.unlink()
    except FileNotFoundError:
        pass
    print(json.dumps({"ok": True, "status": "recovered", "receipt": str(recovery_path)}, sort_keys=True))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["acquire", "check", "refresh", "release", "recover"])
    ap.add_argument("package_root")
    ap.add_argument("--owner", default="hermes")
    ap.add_argument("--owner-pid", type=int, default=os.getppid())
    ap.add_argument("--token-file")
    ap.add_argument("--after-seconds", type=int, default=3600)
    ap.add_argument("--reason", default="")
    args = ap.parse_args()
    root = safe_root(args.package_root)
    if args.action == "acquire":
        acquire(root, args.owner, args.owner_pid, args.token_file)
    elif args.action == "check":
        check_or_refresh(root, args.token_file, args.owner, False)
    elif args.action == "refresh":
        check_or_refresh(root, args.token_file, args.owner, True)
    elif args.action == "release":
        release(root, args.token_file, args.owner)
    else:
        if not args.reason.strip():
            fail("recover requires --reason")
        recover(root, args.token_file, args.after_seconds, args.reason.strip())


if __name__ == "__main__":
    main()
