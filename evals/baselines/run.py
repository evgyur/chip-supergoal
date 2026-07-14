#!/usr/bin/env python3
"""Freeze and replay the immutable v3 planning baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


PROMPT_REFERENCE_PATHS = [
    "SKILL.md",
    "references/core-planning-contract.md",
    "references/phase-design.md",
    "references/planning-depth.md",
    "templates/PROTOCOL.md",
    "templates/ROADMAP.md",
    "templates/LOOP_DESIGN.md",
]
COMPILER_ADAPTER_PATHS = [
    "scripts/sgctl.py",
    "lib/chip_supergoal/model.py",
    "lib/chip_supergoal/normalize.py",
    "lib/chip_supergoal/pipeline.py",
    "lib/chip_supergoal/render.py",
    "lib/chip_supergoal/validate.py",
    "spec/contract.schema.json",
    "spec/risk-policy.json",
]
REPRESENTATIVE_CONTRACTS = [
    ("brownfield-feature", "examples/brownfield-feature/CONTRACT.json"),
    ("private-data-migration", "evals/baselines/fixtures/contracts/private-data-migration.json"),
    ("gateway-integration", "evals/baselines/fixtures/contracts/gateway-integration.json"),
]


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def run(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return run(["git", *args], cwd=repo)


def git_file_record(repo: Path, selected_sha: str, relative: str) -> dict[str, str]:
    value = subprocess.run(
        ["git", "show", f"{selected_sha}:{relative}"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if value.returncode != 0:
        raise ValueError(f"selected foundation is missing {relative}: {value.stderr.decode().strip()}")
    return {
        "path": relative,
        "git_blob_sha": git(repo, "rev-parse", f"{selected_sha}:{relative}"),
        "sha256": sha256_bytes(value.stdout),
    }


def compile_contract(compiler_root: Path, contract: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        shutil.rmtree(output)
    run(
        ["python", "scripts/sgctl.py", "compile", str(contract), "--out", str(output)],
        cwd=compiler_root,
    )
    manifest = load_json(output / "MANIFEST.json")
    validation = run(
        ["python", "scripts/sgctl.py", "validate-package", str(output), "--strict"],
        cwd=compiler_root,
    )
    if validation.strip() != "valid":
        raise ValueError(f"compiled package failed strict validation: {contract}")
    return manifest


def freeze(repo: Path, foundation_path: Path) -> dict[str, Any]:
    foundation = load_json(foundation_path)
    selected_sha = str(foundation["selected_foundation_sha"])
    rollback_sha = str(foundation["rollback_sha"])
    if selected_sha == rollback_sha:
        raise ValueError("plain main cannot be frozen as the quality baseline")
    if foundation.get("status") != "pass":
        raise ValueError("foundation capability manifest is not green")
    if foundation.get("native_windows_v1", {}).get("status") != "pass":
        raise ValueError("native_windows_v1 is not green")
    if foundation.get("linux_parity", {}).get("status") != "pass":
        raise ValueError("Linux parity is not green")

    git(repo, "cat-file", "-e", f"{selected_sha}^{{commit}}")
    selected_tree = git(repo, "rev-parse", f"{selected_sha}^{{tree}}")
    prompt_refs = [git_file_record(repo, selected_sha, path) for path in PROMPT_REFERENCE_PATHS]
    compiler_adapter = [git_file_record(repo, selected_sha, path) for path in COMPILER_ADAPTER_PATHS]

    contracts = [(case_id, repo / path, path) for case_id, path in REPRESENTATIVE_CONTRACTS]
    for _, contract, _ in contracts:
        if not contract.is_file():
            raise ValueError(f"missing representative contract: {contract}")

    with tempfile.TemporaryDirectory(prefix="v3-baseline-") as temporary:
        temporary_path = Path(temporary)
        baseline_root = temporary_path / "selected-foundation"
        run(["git", "worktree", "add", "--detach", str(baseline_root), selected_sha], cwd=repo)
        try:
            representative: list[dict[str, Any]] = []
            for case_id, contract, relative in contracts:
                baseline_manifest = compile_contract(
                    baseline_root,
                    contract,
                    temporary_path / f"baseline-{case_id}",
                )
                current_manifest = compile_contract(
                    repo,
                    contract,
                    temporary_path / f"current-{case_id}",
                )
                baseline_fingerprint = baseline_manifest["package_fingerprint"]
                current_fingerprint = current_manifest["package_fingerprint"]
                if baseline_fingerprint != current_fingerprint:
                    raise ValueError(f"profile-off byte compatibility drift: {case_id}")
                representative.append(
                    {
                        "id": case_id,
                        "contract_path": relative,
                        "contract_sha256": sha256(contract),
                        "package_fingerprint": baseline_fingerprint,
                        "current_package_fingerprint": current_fingerprint,
                        "profile_off_byte_compatible": True,
                    }
                )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(baseline_root)],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

    b2_manifest = load_json(repo / "evals/b2/b2-audit-manifest.json")
    false_greens: list[dict[str, Any]] = []
    for record in b2_manifest["semantic_false_green_fixtures"]:
        fixture_path = repo / record["path"]
        fixture = load_json(fixture_path)
        if fixture.get("id") != record["id"]:
            raise ValueError(f"false-green fixture ID mismatch: {record['path']}")
        if fixture.get("review", {}).get("verdict") != "confirmed_false_green":
            raise ValueError(f"false-green independent review missing: {record['path']}")
        false_greens.append(
            {
                "id": record["id"],
                "path": record["path"],
                "sha256": sha256(fixture_path),
                "legacy_structural_validation": "pass",
                "independent_semantic_truth": "fail",
                "expected_defect": fixture["expected_defect"],
            }
        )

    review_path = repo / "evals/b2/results/false-green-review.json"
    review = load_json(review_path)
    if review.get("implementation_independent") is not True:
        raise ValueError("false-green review is not implementation-independent")
    review_fixtures = review.get("fixtures", [])
    if len(review_fixtures) != 5 or any(item.get("verdict") != "confirmed_false_green" for item in review_fixtures):
        raise ValueError("false-green independent review is incomplete")
    rpd_path = repo / "evals/b2/results/rpd-review.json"
    rpd = load_json(rpd_path)
    if rpd.get("unresolved_p0_p1") != 0 or rpd.get("verdict") != "READY FOR DISCUSSION":
        raise ValueError("B2 RPD review is not green")
    adr_path = repo / "docs/adr/ADR-004-eval-driven-plan-quality.md"
    plan_path = repo / "docs/supergoal-quality-leap-plan.md"
    if not adr_path.is_file():
        raise ValueError("ADR-004 is required before baseline freeze")

    return {
        "schema_version": "v3-baseline-manifest-v1",
        "status": "frozen",
        "frozen_at": git(repo, "show", "-s", "--format=%cI", selected_sha),
        "foundation": {
            "selected_sha": selected_sha,
            "selected_tree_sha": selected_tree,
            "rollback_sha": rollback_sha,
            "capabilities_path": foundation_path.relative_to(repo).as_posix(),
            "capabilities_sha256": sha256(foundation_path),
            "native_windows_v1": "pass",
            "linux_parity": "pass",
        },
        "quality_authority": {
            "adr_path": adr_path.relative_to(repo).as_posix(),
            "adr_sha256": sha256(adr_path),
            "plan_path": plan_path.relative_to(repo).as_posix(),
            "plan_sha256": sha256(plan_path),
            "canonical_authority": "CONTRACT.json.subject",
            "derived_report": "reports/plan-quality.json",
        },
        "prompt_reference_set": prompt_refs,
        "compiler_adapter": compiler_adapter,
        "representative_packages": representative,
        "false_green_fixtures": false_greens,
        "independent_review": {
            "path": review_path.relative_to(repo).as_posix(),
            "sha256": sha256(review_path),
            "implementation_independent": True,
            "fixture_count": 5,
            "status": "pass",
        },
        "rpd_review": {
            "path": rpd_path.relative_to(repo).as_posix(),
            "sha256": sha256(rpd_path),
            "verdict": rpd["verdict"],
            "unresolved_p0_p1": 0,
        },
        "profile_off": {
            "status": "pass",
            "mode": "quality profile absent; current compiler bytes equal selected-foundation bytes",
            "case_count": len(representative),
        },
        "budgets": {
            "b_only_semantic_calls": 0,
            "max_critic_repair_cycles": 2,
            "prompt_growth_max_pct": 10,
            "quality_mcid_points": 6.25,
            "no_progress_stop": True,
        },
        "deletion_rule": "Delete any layer without a reproduced failure class, unique regression test, incremental gain, profile isolation, and deterministic rollback.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--repo", default=".")
    freeze_parser.add_argument("--foundation", required=True)
    freeze_parser.add_argument("--manifest", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = Path(args.repo).resolve()
    manifest_path = (repo / args.manifest).resolve()
    value = freeze(repo, (repo / args.foundation).resolve())
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(canonical_bytes(value))
    print(
        json.dumps(
            {
                "ok": True,
                "manifest": manifest_path.as_posix(),
                "selected_sha": value["foundation"]["selected_sha"],
                "representative_packages": len(value["representative_packages"]),
                "false_green_fixtures": len(value["false_green_fixtures"]),
                "profile_off": value["profile_off"]["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
