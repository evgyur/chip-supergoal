#!/usr/bin/env python3
"""Immutable package-owned verifier for exact SuperGoal implementation filesets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path


def die(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, sort_keys=True), file=sys.stderr)
    raise SystemExit(2)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def run(repo: Path, *args: str, binary: bool = False):
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=not binary)
    if p.returncode:
        die(f"git {' '.join(args)} failed: {(p.stderr if not binary else p.stderr.decode(errors='replace')).strip()}")
    return p.stdout


def safe_root(raw: str) -> Path:
    source = Path(raw)
    root = source.resolve(strict=True)
    if source.is_symlink() or not root.is_dir():
        die(f"unsafe directory: {source}")
    return root


def safe_rel(value: str) -> str:
    p = Path(value)
    if p.is_absolute() or not value or ".." in p.parts or value.startswith(".supergoal/"):
        die(f"unsafe contract path: {value}")
    return p.as_posix()


def validate_package(package: Path) -> None:
    sys.path.insert(0, str(package / "lib"))
    from chip_supergoal.validate import validate_package as validate
    diagnostics = validate(package)
    if diagnostics:
        die("immutable package validation failed: " + "; ".join(d.code for d in diagnostics))


def file_record(repo: Path, rel: str) -> dict:
    p = repo / rel
    try:
        resolved = p.resolve(strict=True)
        st = os.lstat(p)
    except FileNotFoundError:
        die(f"required candidate path is missing: {rel}")
    if not resolved.is_relative_to(repo) or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        die(f"candidate path must be a regular in-repo file: {rel}")
    return {"path": rel, "mode": f"{stat.S_IMODE(st.st_mode):04o}", "bytes": st.st_size, "sha256": sha(p)}


def nul_paths(raw: bytes) -> set[str]:
    return {x.decode("utf-8", errors="strict") for x in raw.split(b"\0") if x}


def contract_scope(contract: dict, phase_id: str) -> tuple[list[str], list[str]]:
    phases = contract.get("phases") or []
    ids = [p.get("id") for p in phases]
    if phase_id not in ids:
        die(f"unknown phase id: {phase_id}")
    ordinal = ids.index(phase_id)
    paths: list[str] = []
    for phase in phases[: ordinal + 1]:
        for item in phase.get("deliverables") or []:
            paths.append(safe_rel(str(item.get("path", ""))))
    allowed = sorted(set(paths))
    return allowed, allowed.copy()


def build(package: Path, repo: Path, baseline: str, phase_id: str) -> dict:
    validate_package(package)
    contract_path = package / "CONTRACT.json"
    manifest_path = package / "MANIFEST.json"
    contract = json.loads(contract_path.read_text())
    repo_baselines = contract.get("architecture", {}).get("repo_baselines") or []
    expected = [{"root": str(repo), "baseline_sha": baseline}]
    if repo_baselines != expected:
        die(f"repository baseline ABI mismatch: {repo_baselines!r}")
    contract_baseline = contract.get("compatibility", {}).get("baseline_ref")
    if contract_baseline != baseline:
        die("contract baseline_ref mismatch")
    head = run(repo, "rev-parse", "HEAD").strip()
    if head != baseline:
        die(f"HEAD drift: expected {baseline}, got {head}")
    run(repo, "cat-file", "-e", f"{baseline}^{{commit}}")

    allowed, required = contract_scope(contract, phase_id)
    tracked = nul_paths(run(repo, "diff", "--name-only", "-z", baseline, "--", binary=True))
    untracked = nul_paths(run(repo, "ls-files", "--others", "--exclude-standard", "-z", binary=True))
    changed = sorted(tracked | untracked)
    forbidden = sorted(set(changed) - set(allowed))
    missing_changed = sorted(set(required) - set(changed))
    if forbidden:
        die("changed paths outside sealed phase scope: " + ", ".join(forbidden))
    if missing_changed:
        die("sealed required paths are not changed: " + ", ".join(missing_changed))
    dependency_names = {"pyproject.toml", "poetry.lock", "uv.lock", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
    dependency_drift = [p for p in changed if Path(p).name in dependency_names or Path(p).name.startswith("requirements")]
    if dependency_drift:
        die("dependency manifest drift is not allowed by this contract: " + ", ".join(dependency_drift))

    changed_records = [file_record(repo, p) for p in changed]
    required_records = [file_record(repo, p) for p in required]
    status_bytes = run(repo, "status", "--porcelain=v2", "--untracked-files=all", "-z", binary=True)
    diff_bytes = run(repo, "diff", "--binary", baseline, "--", binary=True)
    core = {
        "schema": "chip-supergoal.candidate-fileset.v1",
        "goal_id": contract.get("goal", {}).get("id"),
        "phase": phase_id,
        "package_manifest_sha256": sha(manifest_path),
        "package_fingerprint": json.loads(manifest_path.read_text()).get("package_fingerprint"),
        "contract_sha256": sha(contract_path),
        "repo_root": str(repo),
        "baseline_sha": baseline,
        "head_sha": head,
        "phase_id": phase_id,
        "allowed_paths": allowed,
        "required_paths": required,
        "changed_records": changed_records,
        "required_records": required_records,
        "git_status_sha256": hashlib.sha256(status_bytes).hexdigest(),
        "git_diff_sha256": hashlib.sha256(diff_bytes).hexdigest(),
    }
    core["candidate_fingerprint"] = hashlib.sha256(canonical(core).encode()).hexdigest()
    return core


def safe_write(package: Path, out: Path, payload: dict) -> None:
    runtime = (package / "out" / "runtime").resolve(strict=True)
    target = out.resolve(strict=False)
    if not target.is_relative_to(runtime) or out.is_symlink():
        die("receipt output must be a non-symlink path under package out/runtime")
    tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-root", required=True)
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--emit-receipt")
    ap.add_argument("--verify-receipt")
    args = ap.parse_args()
    package = safe_root(args.package_root)
    repo = safe_root(args.repo_root)
    current = build(package, repo, args.baseline, args.phase)
    if args.verify_receipt:
        receipt_path = Path(args.verify_receipt)
        if receipt_path.is_symlink() or not receipt_path.is_file():
            die("candidate receipt is missing or unsafe")
        receipt = json.loads(receipt_path.read_text())
        expected = {k: receipt.get(k) for k in current}
        if expected != current:
            die("candidate receipt no longer matches exact package/worktree state")
    if args.emit_receipt:
        payload = dict(current)
        payload["generated_at"] = int(time.time())
        safe_write(package, Path(args.emit_receipt), payload)
    print(json.dumps({"ok": True, "phase": args.phase, "candidate_fingerprint": current["candidate_fingerprint"], "changed_count": len(current["changed_records"]), "required_count": len(current["required_records"])}, sort_keys=True))


if __name__ == "__main__":
    main()
