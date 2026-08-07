#!/usr/bin/env python3
"""Run a separate Hermes review session and seal its exact-candidate verdict."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def die(msg: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": msg}, sort_keys=True), file=sys.stderr)
    raise SystemExit(code)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        die(f"missing or unsafe file: {path}")


def safe_write(package: Path, path: Path, data: bytes) -> None:
    runtime = (package / "out" / "runtime").resolve(strict=True)
    target = path.resolve(strict=False)
    if not target.is_relative_to(runtime) or path.is_symlink():
        die("review output must stay under package out/runtime")
    tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)


def parse_json_object(text: str) -> dict:
    candidates = [text]
    candidates.extend(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S))
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for idx, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(candidate[idx:])
            except Exception:
                continue
            if isinstance(obj, dict) and "verdict" in obj and "package_manifest_sha256" in obj:
                return obj
    die("independent reviewer did not return the required JSON verdict")


def run_candidate_verifier(package: Path, repo: Path, baseline: str, receipt: Path) -> None:
    receipt_phase = str(json.loads(receipt.read_text()).get("phase", ""))
    if not receipt_phase:
        die("candidate receipt phase is missing")
    cmd = [
        sys.executable, str(package / "scripts" / "verify-candidate-fileset.py"),
        "--package-root", str(package), "--repo-root", str(repo),
        "--baseline", baseline, "--phase", receipt_phase, "--verify-receipt", str(receipt),
    ]
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode:
        die(f"candidate receipt verification failed: {p.stderr.strip()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-root", required=True)
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate-receipt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--provider", default="openai-codex")
    ap.add_argument("--model", default="gpt-5.6-sol")
    ap.add_argument("--timeout", type=int, default=1200)
    args = ap.parse_args()

    package = Path(args.package_root).resolve(strict=True)
    repo = Path(args.repo_root).resolve(strict=True)
    candidate = Path(args.candidate_receipt)
    out = Path(args.out)
    if package.is_symlink() or repo.is_symlink():
        die("package/repo root must not be symlinks")
    safe_file(package / "MANIFEST.json")
    safe_file(candidate)
    run_candidate_verifier(package, repo, args.baseline, candidate)
    manifest_sha = sha(package / "MANIFEST.json")
    candidate_sha = sha(candidate)
    candidate_data = json.loads(candidate.read_text())
    expected_fingerprint = candidate_data.get("candidate_fingerprint")
    if not expected_fingerprint:
        die("candidate receipt lacks fingerprint")

    hermes = shutil.which("hermes")
    if not hermes:
        die("hermes executable not found")
    try:
        version = subprocess.run([hermes, "--version"], text=True, capture_output=True, timeout=30).stdout.strip()
    except Exception:
        version = "unknown"

    prompt = f"""You are the independent final reviewer for an exact local-only SuperGoal implementation candidate.
READ-ONLY: do not modify files, create files, run installs, send messages, or perform external effects.
Package root: {package}
Target repo: {repo}
Baseline/head required: {args.baseline}
Package MANIFEST SHA-256: {manifest_sha}
Candidate receipt: {candidate}
Candidate receipt SHA-256: {candidate_sha}
Candidate fingerprint: {expected_fingerprint}

Review exact source/diff, package contract, tests/evidence, security boundaries, and candidate receipt. Fail closed on circular/self-authored evidence, secret/body egress, proxy lifecycle gaps, SSRF/origin widening, duplicate effects, CAPTCHA/protected-effect use, missing real-browser proof, unbounded retries/concurrency, scope drift, or post-freeze mutation. Recompute package/candidate bindings and confirm repo stays unchanged.

Return exactly one JSON object, no markdown:
{{"verdict":"GO|NO_GO","p0":[],"p1":[],"p2":[],"checked_holds":[],"package_manifest_sha256":"{manifest_sha}","candidate_receipt_sha256":"{candidate_sha}","candidate_fingerprint":"{expected_fingerprint}","target_head":"{args.baseline}","provider":"{args.provider}","model":"{args.model}"}}
Every finding array item must be a concise object with id, evidence, and remediation. GO requires p0 and p1 empty.
"""
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("HERMES_SESSION_") or key in {"HERMES_CRON_SESSION", "HERMES_UI_SESSION_ID"}:
            env.pop(key, None)
    cmd = [
        hermes, "chat", "-Q", "--pass-session-id", "--ignore-rules",
        "--source", "supergoal-independent-review", "--reasoning", "xhigh",
        "--provider", args.provider, "--model", args.model,
        "-s", "exact-candidate-integrity,generated-package-assurance",
        "-t", "file,terminal", "-q", prompt,
    ]
    started = int(time.time())
    try:
        p = subprocess.run(cmd, cwd=repo, env=env, text=True, capture_output=True, timeout=args.timeout)
    except subprocess.TimeoutExpired as exc:
        die(f"independent reviewer timed out after {args.timeout}s: {exc}")
    finished = int(time.time())
    raw = (p.stdout or "") + ("\nSTDERR:\n" + p.stderr if p.stderr else "")
    raw_path = out.with_name("final-independent-review.raw.txt")
    safe_write(package, raw_path, raw.encode())
    if p.returncode:
        die(f"independent reviewer process failed rc={p.returncode}; raw={raw_path}")
    verdict = parse_json_object(p.stdout)
    if verdict.get("package_manifest_sha256") != manifest_sha or verdict.get("candidate_receipt_sha256") != candidate_sha:
        die("reviewer verdict is not bound to exact package/candidate hashes")
    if verdict.get("candidate_fingerprint") != expected_fingerprint or verdict.get("target_head") != args.baseline:
        die("reviewer verdict is not bound to exact candidate identity")
    session_match = re.search(r"(?im)^(?:session_id|Session ID)\s*:\s*([A-Za-z0-9_.:-]+)\s*$", raw)
    session_id = session_match.group(1) if session_match else None
    if not session_id:
        die("reviewer session identity missing from Hermes CLI receipt")
    session_probe = subprocess.run([
        sys.executable, str(package / "scripts" / "verify-hermes-session.py"),
        "--session-id", session_id,
        "--repo-root", str(repo),
        "--provider", args.provider,
        "--model", args.model,
        "--started-at", str(started),
    ], text=True, capture_output=True)
    if session_probe.returncode:
        die(f"Hermes reviewer session-store authentication failed: {session_probe.stderr.strip()}")
    session_store = json.loads(session_probe.stdout)
    run_candidate_verifier(package, repo, args.baseline, candidate)
    if sha(package / "MANIFEST.json") != manifest_sha or sha(candidate) != candidate_sha:
        die("package or candidate receipt mutated during review")
    p0 = verdict.get("p0") if isinstance(verdict.get("p0"), list) else ["malformed"]
    p1 = verdict.get("p1") if isinstance(verdict.get("p1"), list) else ["malformed"]
    receipt = {
        "schema": "chip-supergoal.independent-review.v1",
        "source": "hermes-chat-external",
        "reviewer_session_id": session_id,
        "session_store": session_store,
        "provider": args.provider,
        "model": args.model,
        "hermes_executable": str(Path(hermes).resolve()),
        "hermes_version": version,
        "started_at": started,
        "finished_at": finished,
        "package_manifest_sha256": manifest_sha,
        "candidate_receipt_sha256": candidate_sha,
        "candidate_fingerprint": expected_fingerprint,
        "target_head": args.baseline,
        "verdict": verdict.get("verdict"),
        "p0": p0,
        "p1": p1,
        "p2": verdict.get("p2") if isinstance(verdict.get("p2"), list) else [],
        "checked_holds": verdict.get("checked_holds") if isinstance(verdict.get("checked_holds"), list) else [],
        "raw_output_sha256": sha(raw_path),
        "raw_output_path": str(raw_path),
    }
    safe_write(package, out, (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    if receipt["verdict"] != "GO" or p0 or p1:
        die(f"independent review blocked candidate: verdict={receipt['verdict']} p0={len(p0)} p1={len(p1)}", 3)
    print(json.dumps({"ok": True, "verdict": "GO", "session_id": session_id, "receipt": str(out)}, sort_keys=True))


if __name__ == "__main__":
    main()
