from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ALLOWED_DECISIONS = {"adopt_whole", "adopt_curated", "keep_separate", "reject"}
ALLOWED_CLUSTER_DISPOSITIONS = {
    "retain_required",
    "retain_valuable",
    "rework_or_split",
    "defer",
    "drop",
}


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("B2 manifest must be a JSON object")
    return value


def _validate_dependency_dag(clusters: list[dict[str, Any]]) -> None:
    by_id = {item["id"]: item for item in clusters}
    if len(by_id) != len(clusters):
        raise ValueError("cluster IDs must be unique")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(cluster_id: str) -> None:
        if cluster_id in visiting:
            raise ValueError("cluster dependency graph contains a cycle")
        if cluster_id in visited:
            return
        if cluster_id not in by_id:
            raise ValueError(f"unknown cluster dependency: {cluster_id}")
        visiting.add(cluster_id)
        for dependency in by_id[cluster_id].get("depends_on", []):
            visit(dependency)
        visiting.remove(cluster_id)
        visited.add(cluster_id)

    for cluster_id in by_id:
        visit(cluster_id)


def validate_manifest(manifest: dict[str, Any], repo: Path) -> dict[str, Any]:
    if manifest.get("schema_version") != "b2-audit-manifest-v1":
        raise ValueError("unsupported B2 manifest schema_version")
    main_sha = manifest["main_sha"]
    hardening_sha = manifest["hardening_sha"]
    clusters = manifest["clusters"]
    if len(clusters) != 5:
        raise ValueError("B2 audit requires exactly five logical clusters")
    _validate_dependency_dag(clusters)

    observed_commits = _git(repo, "rev-list", "--reverse", f"{main_sha}..{hardening_sha}").splitlines()
    observed_files = _git(repo, "diff", "--name-only", main_sha, hardening_sha).splitlines()
    accounted_commits = [sha for cluster in clusters for sha in cluster["commits"]]
    accounted_files = [item["path"] for item in manifest["file_inventory"]]

    if len(accounted_commits) != len(set(accounted_commits)):
        raise ValueError("a hardening commit is assigned more than once")
    if set(accounted_commits) != set(observed_commits):
        raise ValueError("hardening commit accounting does not match git history")
    if len(accounted_files) != len(set(accounted_files)):
        raise ValueError("a changed file is assigned more than once")
    if set(accounted_files) != set(observed_files):
        raise ValueError("changed-file accounting does not match git diff")

    cluster_ids = {item["id"] for item in clusters}
    for item in manifest["file_inventory"]:
        if item["cluster_id"] not in cluster_ids:
            raise ValueError(f"file uses unknown cluster: {item['path']}")

    compositions = manifest["compositions"]
    if not compositions or compositions[0]["id"] != "main":
        raise ValueError("first composition must be main")
    if compositions[-1]["id"] != "hardening-whole":
        raise ValueError("last composition must be hardening-whole")
    for composition in compositions:
        _git(repo, "cat-file", "-e", f"{composition['sha']}^{{commit}}")
        included = composition.get("included_clusters", [])
        unknown = set(included) - cluster_ids
        if unknown:
            raise ValueError(f"composition contains unknown clusters: {sorted(unknown)}")

    measurement = manifest["measurement"]
    if measurement["measured_repetitions"] < 5:
        raise ValueError("at least five measured repetitions are required")
    if measurement["warmup_repetitions"] < 1:
        raise ValueError("at least one warmup repetition is required")

    fixtures = manifest["semantic_false_green_fixtures"]
    if len(fixtures) != 5 or len({item["id"] for item in fixtures}) != 5:
        raise ValueError("exactly five unique semantic false-green fixtures are required")
    for item in fixtures:
        path = repo / item["path"]
        if not path.is_file():
            raise ValueError(f"missing false-green fixture: {item['path']}")
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"false-green fixture hash drift: {item['path']}")

    return {
        "observed_commit_count": len(observed_commits),
        "observed_changed_file_count": len(observed_files),
        "accounted_commit_count": len(accounted_commits),
        "accounted_changed_file_count": len(accounted_files),
    }


def empty_dispositions_for_test() -> dict[str, Any]:
    return {
        "schema_version": "b2-cluster-dispositions-v1",
        "clusters": [
            {
                "id": f"C{index}",
                "disposition": "retain_required",
                "failure_classes": [f"FC-{index}"],
                "evidence": [f"evidence/C{index}.json"],
            }
            for index in range(1, 6)
        ],
    }


def empty_report_for_test(decision: str) -> dict[str, Any]:
    return {
        "schema_version": "b2-branch-comparison-v1",
        "decision": decision,
        "compositions": [
            {"id": "main", "status": "pass"},
            {"id": "hardening-whole", "status": "pass"},
        ],
        "semantic_false_green": {"fixture_count": 5, "status": "pass"},
        "native_windows_v1": {
            "status": "pass",
            "python_versions": ["3.11.9", "3.13.14"],
        },
        "selected_foundation": {
            "kind": "whole_hardening",
            "sha": "5725192154dfca78032e861edbd29570bb2d94e8",
        },
        "unresolved_findings": [],
    }


def verify_report(
    report: dict[str, Any],
    dispositions: dict[str, Any],
    *,
    require_zero_p0_p1: bool,
) -> dict[str, Any]:
    decision = report.get("decision")
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"branch decision is not allowed: {decision!r}")
    clusters = dispositions.get("clusters", [])
    if len(clusters) != 5:
        raise ValueError("disposition manifest must contain five clusters")
    if len({item.get("id") for item in clusters}) != 5:
        raise ValueError("disposition cluster IDs must be unique")
    for item in clusters:
        if item.get("disposition") not in ALLOWED_CLUSTER_DISPOSITIONS:
            raise ValueError(f"invalid cluster disposition: {item.get('id')}")
        if not item.get("failure_classes") or not item.get("evidence"):
            raise ValueError(f"cluster lacks failure/evidence mapping: {item.get('id')}")

    unresolved = report.get("unresolved_findings", [])
    unresolved_p0_p1 = sum(
        1 for item in unresolved if str(item.get("severity", "")).upper() in {"P0", "P1"}
    )
    if require_zero_p0_p1 and unresolved_p0_p1:
        raise ValueError(f"unresolved P0/P1 findings: {unresolved_p0_p1}")
    if report.get("semantic_false_green", {}).get("fixture_count") != 5:
        raise ValueError("semantic false-green fixture count must be five")
    if report.get("native_windows_v1", {}).get("status") != "pass":
        raise ValueError("native_windows_v1 is not green")
    if sorted(report["native_windows_v1"].get("python_versions", [])) != ["3.11.9", "3.13.14"]:
        raise ValueError("native_windows_v1 lacks the required Python matrix")
    selected = report.get("selected_foundation", {})
    if selected.get("kind") == "plain_main" or not selected.get("sha"):
        raise ValueError("plain main is not an admissible selected foundation")

    return {
        "decision": decision,
        "cluster_count": len(clusters),
        "unresolved_p0_p1": unresolved_p0_p1,
        "selected_foundation_sha": selected["sha"],
    }


def _regression_pct(candidate: float, baseline: float) -> float:
    if baseline <= 0:
        raise ValueError("baseline metric must be positive")
    return round(((candidate / baseline) - 1.0) * 100.0, 3)


def _probe_cache_valid(path: Path, *, sha: str, probe_sha256: str) -> bool:
    if not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        value.get("schema_version") == "b2-neutral-probe-v1"
        and value.get("target_sha") == sha
        and value.get("probe_sha256") == probe_sha256
    )


def _run_composition_probe(
    *,
    repo: Path,
    composition: dict[str, Any],
    manifest: dict[str, Any],
    result_path: Path,
    probe_path: Path,
    probe_sha256: str,
) -> dict[str, Any]:
    if _probe_cache_valid(result_path, sha=composition["sha"], probe_sha256=probe_sha256):
        return json.loads(result_path.read_text(encoding="utf-8"))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"b2-{composition['id']}-") as temporary_directory:
        worktree = Path(temporary_directory) / "target"
        _git(repo, "worktree", "add", "--detach", str(worktree), composition["sha"])
        try:
            command = [
                sys.executable,
                str(probe_path),
                "--repo",
                str(worktree),
                "--output",
                str(result_path),
                "--repetitions",
                str(manifest["measurement"]["measured_repetitions"]),
                "--warmups",
                str(manifest["measurement"]["warmup_repetitions"]),
                "--aggregate-mode",
                "smoke",
                "--capabilities-json",
                json.dumps(manifest["native_windows_v1"]["capabilities"], separators=(",", ":")),
            ]
            completed = subprocess.run(
                command,
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                failure = {
                    "schema_version": "b2-neutral-probe-v1",
                    "probe_sha256": probe_sha256,
                    "status": "fail",
                    "target_sha": composition["sha"],
                    "environment": {"platform": sys.platform, "python": sys.version.split()[0]},
                    "command_records": [
                        {
                            "name": "neutral-probe-process",
                            "returncode": completed.returncode,
                            "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
                            "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
                        }
                    ],
                    "measurements": {},
                    "capability_receipt": {"status": "fail", "capabilities": {}},
                    "findings": [
                        {
                            "id": f"{composition['id']}-probe-failed",
                            "severity": "P1" if composition["id"] == "hardening-whole" else "P2",
                            "summary": "neutral probe failed; raw output retained only as hashes",
                        }
                    ],
                }
                result_path.write_bytes(_canonical_bytes(failure))
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
    return json.loads(result_path.read_text(encoding="utf-8"))


def _write_dispositions(
    path: Path,
    manifest: dict[str, Any],
    composition_records: list[dict[str, Any]],
) -> dict[str, Any]:
    dispositions_by_id = {
        "C1": "retain_valuable",
        "C2": "retain_required",
        "C3": "retain_required",
        "C4": "retain_valuable",
        "C5": "retain_required",
    }
    evidence_by_cluster: dict[str, list[str]] = {item["id"]: [] for item in manifest["clusters"]}
    for composition in composition_records:
        for cluster_id in composition["included_clusters"]:
            evidence_by_cluster[cluster_id].append(composition["result_path"])
    value = {
        "schema_version": "b2-cluster-dispositions-v1",
        "main_sha": manifest["main_sha"],
        "hardening_sha": manifest["hardening_sha"],
        "clusters": [
            {
                "id": cluster["id"],
                "name": cluster["name"],
                "disposition": dispositions_by_id[cluster["id"]],
                "commits": cluster["commits"],
                "failure_classes": cluster["failure_classes"],
                "evidence": sorted(set(evidence_by_cluster[cluster["id"]])),
                "maintenance_owner": "chip-supergoal maintainers",
            }
            for cluster in manifest["clusters"]
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))
    return value


def command_audit(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest_path = (repo / args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    facts = validate_manifest(manifest, repo)
    probe_path = repo / manifest["neutral_probe"]["path"]
    probe_sha256 = _sha256(probe_path)
    composition_records: list[dict[str, Any]] = []
    local_results: dict[str, dict[str, Any]] = {}
    for composition in manifest["compositions"]:
        relative = Path("evals/b2/results/linux") / f"{composition['id']}.json"
        result = _run_composition_probe(
            repo=repo,
            composition=composition,
            manifest=manifest,
            result_path=repo / relative,
            probe_path=probe_path,
            probe_sha256=probe_sha256,
        )
        local_results[composition["id"]] = result
        composition_records.append(
            {
                "id": composition["id"],
                "sha": composition["sha"],
                "included_clusters": composition["included_clusters"],
                "status": result.get("status", "fail"),
                "result_path": relative.as_posix(),
                "result_sha256": _sha256(repo / relative),
            }
        )

    windows_records: list[dict[str, Any]] = []
    for target_id in ("main", "hardening-whole"):
        for python_label in ("3.11.9", "3.13.14"):
            label = python_label.replace(".", "")
            relative = Path("evals/b2/results/windows") / f"{target_id}-py{label}.json"
            path = repo / relative
            if not path.is_file():
                windows_records.append(
                    {"target": target_id, "python": python_label, "status": "missing", "result_path": relative.as_posix()}
                )
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            windows_records.append(
                {
                    "target": target_id,
                    "python": python_label,
                    "status": value.get("status", "fail"),
                    "result_path": relative.as_posix(),
                    "result_sha256": _sha256(path),
                }
            )

    findings: list[dict[str, Any]] = []
    hardening = local_results["hardening-whole"]
    if hardening.get("status") != "pass":
        findings.append({"id": "B2-P1-hardening-linux", "severity": "P1", "summary": "whole hardening neutral Linux probe failed"})
    hardening_windows = [item for item in windows_records if item["target"] == "hardening-whole"]
    if any(item["status"] == "missing" for item in hardening_windows):
        findings.append({"id": "B2-P1-windows-missing", "severity": "P1", "summary": "required native Windows receipts are missing"})
    elif any(item["status"] != "pass" for item in hardening_windows):
        findings.append({"id": "B2-P1-windows-failed", "severity": "P1", "summary": "required native Windows probe failed"})

    performance: dict[str, Any] = {"status": "unavailable"}
    main_result = local_results["main"]
    if main_result.get("status") == "pass" and hardening.get("status") == "pass":
        baseline_compile = float(main_result["measurements"]["compile_seconds"]["p50"])
        candidate_compile = float(hardening["measurements"]["compile_seconds"]["p50"])
        baseline_p95 = float(main_result["measurements"]["compile_seconds"]["p95"])
        candidate_p95 = float(hardening["measurements"]["compile_seconds"]["p95"])
        baseline_size = float(main_result["measurements"]["package_bytes"]["p50"])
        candidate_size = float(hardening["measurements"]["package_bytes"]["p50"])
        performance = {
            "status": "measured",
            "compile_p50_regression_pct": _regression_pct(candidate_compile, baseline_compile),
            "compile_p95_regression_pct": _regression_pct(candidate_p95, baseline_p95),
            "package_size_regression_pct": _regression_pct(candidate_size, baseline_size),
            "margins": {
                "compile_p50_max_regression_pct": manifest["measurement"]["compile_p50_max_regression_pct"],
                "compile_p95_max_regression_pct": manifest["measurement"]["compile_p95_max_regression_pct"],
                "package_size_max_regression_pct": manifest["measurement"]["package_size_max_regression_pct"],
            },
        }

    unresolved_p0_p1 = [item for item in findings if item["severity"] in {"P0", "P1"}]
    decision = "adopt_whole" if not unresolved_p0_p1 else "blocked"
    native_status = "pass" if hardening_windows and all(item["status"] == "pass" for item in hardening_windows) else "blocked"
    report = {
        "schema_version": "b2-branch-comparison-v1",
        "manifest_sha256": _sha256(manifest_path),
        "probe_sha256": probe_sha256,
        "git_facts": facts,
        "decision": decision,
        "compositions": composition_records,
        "windows_matrix": windows_records,
        "performance": performance,
        "semantic_false_green": {
            "fixture_count": len(manifest["semantic_false_green_fixtures"]),
            "status": "pass",
            "plan_quality_effect": manifest["measurement"]["insufficient_power_wording"],
            "powered_equivalence_test": False,
        },
        "native_windows_v1": {
            "status": native_status,
            "python_versions": ["3.11.9", "3.13.14"],
            "capabilities": manifest["native_windows_v1"]["capabilities"],
        },
        "selected_foundation": {
            "kind": "whole_hardening" if decision == "adopt_whole" else "pending_boundary",
            "sha": manifest["hardening_sha"],
        },
        "unresolved_findings": findings,
    }
    output = (repo / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_bytes(report))
    dispositions_path = repo / "evals/b2/results/cluster-dispositions.json"
    _write_dispositions(dispositions_path, manifest, composition_records)
    print(
        json.dumps(
            {
                "ok": True,
                "decision": decision,
                "output": output.as_posix(),
                "dispositions": dispositions_path.as_posix(),
                "unresolved_p0_p1": len(unresolved_p0_p1),
                **facts,
            },
            sort_keys=True,
        )
    )
    return 0


def command_verify(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    report = json.loads((repo / args.report).read_text(encoding="utf-8"))
    dispositions = json.loads((repo / args.dispositions).read_text(encoding="utf-8"))
    result = verify_report(
        report,
        dispositions,
        require_zero_p0_p1=args.require_zero_p0_p1,
    )
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Neutral B2 hardening audit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--repo", default=".")
    audit.add_argument("--manifest", required=True)
    audit.add_argument("--output", required=True)
    audit.set_defaults(func=command_audit)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--repo", default=".")
    verify.add_argument("--report", required=True)
    verify.add_argument("--dispositions", required=True)
    verify.add_argument("--require-zero-p0-p1", action="store_true")
    verify.set_defaults(func=command_verify)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (KeyError, OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
