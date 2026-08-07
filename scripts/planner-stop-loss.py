#!/usr/bin/env python3
"""Fail-closed planning stop-loss for Chip-facing SuperGoal packages."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

SCHEMA = "chip-supergoal.planner-stop-loss.v1"
MAX_REVIEWS = 2
MAX_META_FIXES = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def die(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, sort_keys=True), file=sys.stderr)
    raise SystemExit(2)


def package_paths(raw: str) -> tuple[Path, Path]:
    supplied = Path(raw)
    if supplied.is_symlink():
        die("package root must not be a symlink")
    try:
        root = supplied.resolve(strict=True)
    except FileNotFoundError:
        die("package root does not exist")
    st = os.stat(root)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        die("package root must be a same-UID directory")
    out = root / "out"
    out.mkdir(mode=0o700, exist_ok=True)
    out_st = os.lstat(out)
    if stat.S_ISLNK(out_st.st_mode) or not stat.S_ISDIR(out_st.st_mode) or out_st.st_uid != os.getuid():
        die("package out directory is unsafe")
    if stat.S_IMODE(out_st.st_mode) & 0o077:
        os.chmod(out, 0o700)
    return root, out / "planner-stop-loss.json"


def initial_state(root: Path) -> dict:
    contract = root / "CONTRACT.json"
    goal_id = None
    if contract.is_file() and not contract.is_symlink():
        try:
            goal_id = json.loads(contract.read_text()).get("goal_id")
        except (OSError, json.JSONDecodeError):
            goal_id = None
    return {
        "schema": SCHEMA,
        "package_root": str(root),
        "goal_id": goal_id,
        "review_rounds": 0,
        "review_in_flight": False,
        "candidate_sha": None,
        "meta_fix_cycles": 0,
        "terminal": "active",
        "history": [],
    }


def load_state(path: Path, root: Path) -> dict:
    if path.is_symlink():
        die("planner stop-loss ledger must not be a symlink")
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        die("planner stop-loss ledger is missing; run init")
    except json.JSONDecodeError:
        die("planner stop-loss ledger is malformed")
    if data.get("schema") != SCHEMA or data.get("package_root") != str(root):
        die("planner stop-loss ledger identity mismatch")
    return data


def write_state(path: Path, data: dict) -> None:
    payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def event(state: dict, kind: str, **fields: object) -> None:
    state["history"].append({"at": int(time.time()), "kind": kind, **fields})


def require_sha(value: str) -> None:
    if not SHA256_RE.fullmatch(value):
        die("candidate SHA must be 64 lowercase hexadecimal characters")


def emit(state: dict) -> None:
    print(json.dumps({
        "ok": True,
        "terminal": state["terminal"],
        "review_rounds": state["review_rounds"],
        "review_in_flight": state["review_in_flight"],
        "candidate_sha": state["candidate_sha"],
        "meta_fix_cycles": state["meta_fix_cycles"],
        "may_dispatch_review": (
            state["terminal"] not in {"go", "blocked"}
            and not state["review_in_flight"]
            and state["review_rounds"] < MAX_REVIEWS
        ),
    }, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("init", "status"):
        p = sub.add_parser(name)
        p.add_argument("--package-root", required=True)
    pre = sub.add_parser("pre-review")
    pre.add_argument("--package-root", required=True)
    pre.add_argument("--candidate-sha", required=True)
    result = sub.add_parser("review-result")
    result.add_argument("--package-root", required=True)
    result.add_argument("--candidate-sha", required=True)
    result.add_argument("--verdict", choices=("GO", "NO_GO", "INTERRUPTED"), required=True)
    result.add_argument("--p0", type=int, required=True)
    result.add_argument("--p1", type=int, required=True)
    meta = sub.add_parser("meta-fix")
    meta.add_argument("--package-root", required=True)
    meta.add_argument("--reason", required=True)
    args = parser.parse_args()

    root, ledger = package_paths(args.package_root)
    if args.action == "init":
        if ledger.exists():
            state = load_state(ledger, root)
        else:
            state = initial_state(root)
            event(state, "initialized")
            write_state(ledger, state)
        emit(state)
        return

    state = load_state(ledger, root)
    if args.action == "status":
        emit(state)
        return

    if args.action == "pre-review":
        require_sha(args.candidate_sha)
        if state["terminal"] in {"go", "blocked"}:
            die(f"planner is terminal: {state['terminal']}")
        if state["review_in_flight"]:
            die("a blocking semantic review is already in flight")
        if state["review_rounds"] >= MAX_REVIEWS:
            die("review stop-loss reached; emit SUPERGOAL_REVIEW_BLOCKED")
        state["review_in_flight"] = True
        state["candidate_sha"] = args.candidate_sha
        event(state, "review_dispatched", round=state["review_rounds"] + 1, candidate_sha=args.candidate_sha)
        write_state(ledger, state)
        emit(state)
        return

    if args.action == "review-result":
        require_sha(args.candidate_sha)
        if not state["review_in_flight"]:
            die("no blocking semantic review is in flight")
        if state["candidate_sha"] != args.candidate_sha:
            die("review result candidate does not match the in-flight candidate")
        if args.p0 < 0 or args.p1 < 0:
            die("P0/P1 counts must be non-negative")
        state["review_in_flight"] = False
        state["review_rounds"] += 1
        event(state, "review_result", round=state["review_rounds"], candidate_sha=args.candidate_sha, verdict=args.verdict, p0=args.p0, p1=args.p1)
        if args.verdict == "GO" and args.p0 == 0 and args.p1 == 0:
            state["terminal"] = "go"
        elif state["review_rounds"] >= MAX_REVIEWS:
            state["terminal"] = "blocked"
        else:
            state["terminal"] = "repair"
        write_state(ledger, state)
        emit(state)
        return

    if args.action == "meta-fix":
        if state["terminal"] in {"go", "blocked"}:
            die(f"planner is terminal: {state['terminal']}")
        if state["meta_fix_cycles"] >= MAX_META_FIXES:
            die("meta-fix stop-loss reached; keep the shared planner frozen")
        reason = args.reason.strip()
        if not reason:
            die("meta-fix reason must be non-empty")
        state["meta_fix_cycles"] += 1
        event(state, "meta_fix", cycle=state["meta_fix_cycles"], reason_sha256=hashlib.sha256(reason.encode()).hexdigest())
        write_state(ledger, state)
        emit(state)
        return

    die("unsupported action")


if __name__ == "__main__":
    main()
