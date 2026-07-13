#!/usr/bin/env python3
"""Materialize the immutable foundation selected by the B2 audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SELECTED_SHA_RE = re.compile(r"Selected SHA:\s*`([0-9a-f]{40})`")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _receipt(repo: Path, relative: str, *, expected_sha: str, expected_status: str) -> dict[str, Any]:
    path = repo / relative
    value = load_json(path)
    if value.get("target_sha") != expected_sha or value.get("status") != expected_status:
        raise ValueError(f"receipt target/status mismatch: {relative}")
    return {"path": relative, "sha256": sha256(path), "status": value["status"]}


def build_records(
    repo: Path,
    *,
    adr: Path,
    main_sha: str,
    hardening_sha: str,
    plan_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    repo = repo.resolve()
    adr_text = adr.read_text(encoding="utf-8")
    match = SELECTED_SHA_RE.search(adr_text)
    if match is None or match.group(1) != hardening_sha:
        raise ValueError("ADR selected SHA does not match --hardening")
    if hardening_sha == main_sha:
        raise ValueError("plain main is forbidden")

    git(repo, "cat-file", "-e", f"{main_sha}^{{commit}}")
    git(repo, "cat-file", "-e", f"{hardening_sha}^{{commit}}")
    if git(repo, "merge-base", main_sha, hardening_sha) != main_sha:
        raise ValueError("hardening is not based on frozen main")

    plan = repo / "docs/supergoal-quality-leap-plan.md"
    if sha256(plan) != plan_sha256:
        raise ValueError("reviewed plan SHA-256 mismatch")

    comparison_path = repo / "evals/baselines/b2-branch-comparison.json"
    disposition_path = repo / "evals/b2/b2-disposition-manifest.json"
    manifest_path = repo / "evals/b2/b2-audit-manifest.json"
    comparison = load_json(comparison_path)
    dispositions = load_json(disposition_path)
    manifest = load_json(manifest_path)
    if comparison.get("decision") != "adopt_whole":
        raise ValueError("B2 audit did not select adopt_whole")
    selected = comparison.get("selected_foundation", {})
    if selected.get("sha") != hardening_sha or selected.get("kind") != "whole_hardening":
        raise ValueError("comparison selected foundation mismatch")
    if manifest.get("main_sha") != main_sha or manifest.get("hardening_sha") != hardening_sha:
        raise ValueError("frozen manifest SHA mismatch")

    commits = git(repo, "rev-list", "--reverse", f"{main_sha}..{hardening_sha}").splitlines()
    changed_files = git(repo, "diff", "--name-only", f"{main_sha}..{hardening_sha}").splitlines()
    if len(commits) != 29 or len(changed_files) != 151:
        raise ValueError("frozen history no longer accounts for 29 commits and 151 files")

    with tempfile.TemporaryDirectory(prefix="b2-foundation-reconstruct-") as temporary:
        worktree = Path(temporary) / "foundation"
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), hardening_sha],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if add.returncode != 0:
            raise ValueError(f"clean reconstruction failed: {add.stderr.strip()}")
        try:
            if git(worktree, "rev-parse", "HEAD") != hardening_sha:
                raise ValueError("clean reconstruction HEAD mismatch")
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

    windows_receipts = [
        _receipt(repo, "evals/b2/results/windows/hardening-whole-py3119.json", expected_sha=hardening_sha, expected_status="pass"),
        _receipt(repo, "evals/b2/results/windows/hardening-whole-py31314.json", expected_sha=hardening_sha, expected_status="pass"),
    ]
    linux_receipt = _receipt(
        repo,
        "evals/b2/results/linux/hardening-whole.json",
        expected_sha=hardening_sha,
        expected_status="pass",
    )

    capabilities = {
        "schema_version": "foundation-capabilities-v1",
        "status": "pass",
        "selected_foundation_sha": hardening_sha,
        "rollback_sha": main_sha,
        "plan_sha256": plan_sha256,
        "native_windows_v1": {
            "status": "pass",
            "python_versions": ["3.11.9", "3.13.14"],
            "capabilities": manifest["native_windows_v1"]["capabilities"],
            "receipts": windows_receipts,
        },
        "linux_parity": {"status": "pass", "receipt": linux_receipt},
        "profile_hashes": {
            "audit_manifest_sha256": sha256(manifest_path),
            "neutral_probe_sha256": sha256(repo / manifest["neutral_probe"]["path"]),
            "comparison_sha256": sha256(comparison_path),
            "dispositions_sha256": sha256(disposition_path),
        },
    }
    provenance = {
        "schema_version": "foundation-provenance-v1",
        "decision": "adopt_whole",
        "selected_foundation_sha": hardening_sha,
        "selected_tree_sha": git(repo, "rev-parse", f"{hardening_sha}^{{tree}}"),
        "rollback_sha": main_sha,
        "rollback_tree_sha": git(repo, "rev-parse", f"{main_sha}^{{tree}}"),
        "plan_path": "docs/supergoal-quality-leap-plan.md",
        "plan_sha256": plan_sha256,
        "commit_count": len(commits),
        "commits": commits,
        "changed_file_count": len(changed_files),
        "changed_files": changed_files,
        "file_inventory": manifest["file_inventory"],
        "clusters": dispositions["clusters"],
        "reconstruction": {"command": f"git worktree add --detach <path> {hardening_sha}", "verified": True},
        "source_artifacts": {
            "adr_sha256": sha256(adr),
            "comparison_sha256": sha256(comparison_path),
            "dispositions_sha256": sha256(disposition_path),
            "manifest_sha256": sha256(manifest_path),
        },
    }
    return capabilities, provenance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--adr", required=True)
    parser.add_argument("--main", required=True)
    parser.add_argument("--hardening", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--capabilities-out", required=True)
    parser.add_argument("--provenance-out", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = Path(args.repo).resolve()
    capabilities, provenance = build_records(
        repo,
        adr=(repo / args.adr).resolve(),
        main_sha=args.main,
        hardening_sha=args.hardening,
        plan_sha256=args.plan_sha256,
    )
    capabilities_out = (repo / args.capabilities_out).resolve()
    provenance_out = (repo / args.provenance_out).resolve()
    capabilities_out.parent.mkdir(parents=True, exist_ok=True)
    provenance_out.parent.mkdir(parents=True, exist_ok=True)
    capabilities_out.write_bytes(canonical_bytes(capabilities))
    provenance_out.write_bytes(canonical_bytes(provenance))
    print(json.dumps({"ok": True, "selected_foundation_sha": args.hardening, "commit_count": provenance["commit_count"], "changed_file_count": provenance["changed_file_count"], "capabilities": capabilities_out.as_posix(), "provenance": provenance_out.as_posix()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
