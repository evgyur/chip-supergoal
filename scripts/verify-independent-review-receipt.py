#!/usr/bin/env python3
"""Verify an externally produced Hermes review receipt against exact package/candidate bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def die(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, sort_keys=True), file=sys.stderr)
    raise SystemExit(2)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        die(f"missing or unsafe file: {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-root", required=True)
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate-receipt", required=True)
    ap.add_argument("--review-receipt", required=True)
    args = ap.parse_args()
    package = Path(args.package_root).resolve(strict=True)
    repo = Path(args.repo_root).resolve(strict=True)
    candidate = Path(args.candidate_receipt)
    review = Path(args.review_receipt)
    for p in (package / "MANIFEST.json", candidate, review):
        regular(p)
    candidate_data = json.loads(candidate.read_text())
    receipt_phase = str(candidate_data.get("phase", ""))
    if not receipt_phase:
        die("candidate receipt phase is missing")
    verify = subprocess.run([
        sys.executable, str(package / "scripts" / "verify-candidate-fileset.py"),
        "--package-root", str(package), "--repo-root", str(repo), "--baseline", args.baseline,
        "--phase", receipt_phase, "--verify-receipt", str(candidate),
    ], text=True, capture_output=True)
    if verify.returncode:
        die(f"candidate receipt verification failed: {verify.stderr.strip()}")
    data = json.loads(review.read_text())
    required = {
        "schema", "source", "reviewer_session_id", "session_store", "provider", "model", "hermes_executable", "started_at",
        "package_manifest_sha256", "candidate_receipt_sha256", "candidate_fingerprint",
        "target_head", "verdict", "p0", "p1", "checked_holds", "raw_output_sha256", "raw_output_path",
    }
    if missing := sorted(required - set(data)):
        die("review receipt missing fields: " + ", ".join(missing))
    candidate_data = json.loads(candidate.read_text())
    if data.get("schema") != "chip-supergoal.independent-review.v1" or data.get("source") != "hermes-chat-external":
        die("review receipt provenance is not the immutable Hermes external-review lane")
    if data.get("package_manifest_sha256") != sha(package / "MANIFEST.json"):
        die("review receipt package hash mismatch")
    if data.get("candidate_receipt_sha256") != sha(candidate):
        die("review receipt candidate-receipt hash mismatch")
    if data.get("candidate_fingerprint") != candidate_data.get("candidate_fingerprint"):
        die("review receipt candidate fingerprint mismatch")
    if data.get("target_head") != args.baseline:
        die("review receipt target head mismatch")
    if data.get("verdict") != "GO" or data.get("p0") != [] or data.get("p1") != []:
        die("independent review is not GO with P0=0/P1=0")
    if not isinstance(data.get("reviewer_session_id"), str) or len(data["reviewer_session_id"]) < 8:
        die("reviewer session identity is missing")
    if not data.get("provider") or not data.get("model"):
        die("reviewer provider/model identity is missing")
    session_probe = subprocess.run([
        sys.executable, str(package / "scripts" / "verify-hermes-session.py"),
        "--session-id", data["reviewer_session_id"],
        "--repo-root", str(repo),
        "--provider", data["provider"],
        "--model", data["model"],
        "--started-at", str(data["started_at"]),
    ], text=True, capture_output=True)
    if session_probe.returncode:
        die(f"Hermes reviewer session-store authentication failed: {session_probe.stderr.strip()}")
    if json.loads(session_probe.stdout) != data.get("session_store"):
        die("Hermes reviewer session-store evidence drift")
    raw = Path(str(data.get("raw_output_path")))
    regular(raw)
    runtime = (package / "out" / "runtime").resolve(strict=True)
    if not raw.resolve().is_relative_to(runtime) or sha(raw) != data.get("raw_output_sha256"):
        die("raw reviewer output binding mismatch")
    print(json.dumps({"ok": True, "verdict": "GO", "reviewer_session_id": data["reviewer_session_id"], "candidate_fingerprint": data["candidate_fingerprint"]}, sort_keys=True))


if __name__ == "__main__":
    main()
