#!/usr/bin/env python3
"""Authenticate a Hermes reviewer session against the local read-only session store."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, sort_keys=True), file=sys.stderr)
    raise SystemExit(2)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--started-at", type=float, required=True)
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve(strict=True)
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).resolve(strict=True)
    db = home / "state.db"
    info = os.lstat(db)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        fail("Hermes session store is missing or unsafe")

    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT id,source,model,billing_provider,cwd,started_at,ended_at,message_count,tool_call_count,system_prompt_hash "
            "FROM sessions WHERE id=?",
            (args.session_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        fail("Hermes reviewer session does not exist")

    keys = ["id", "source", "model", "billing_provider", "cwd", "started_at", "ended_at", "message_count", "tool_call_count", "system_prompt_hash"]
    evidence = dict(zip(keys, row))
    if evidence["source"] != "supergoal-independent-review":
        fail("Hermes reviewer session source mismatch")
    if evidence["model"] != args.model or evidence["billing_provider"] != args.provider:
        fail("Hermes reviewer provider/model mismatch")
    if Path(str(evidence["cwd"])).resolve() != repo:
        fail("Hermes reviewer cwd mismatch")
    if float(evidence["started_at"] or 0) < args.started_at - 5:
        fail("Hermes reviewer session predates the review invocation")
    if evidence["ended_at"] is None or int(evidence["message_count"] or 0) < 2:
        fail("Hermes reviewer session is incomplete")

    result = {
        "ok": True,
        "db_path": str(db),
        "row": evidence,
        "row_sha256": hashlib.sha256(canonical(evidence)).hexdigest(),
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
