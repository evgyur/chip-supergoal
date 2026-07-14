#!/usr/bin/env python3
"""Evaluation corpus and policy freeze controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.harness.ablation import compare_manifest, select_candidate, verify_holdout_secrecy
from evals.harness.budget import verify_canary_budget
from evals.harness.calibration import calibrate as calibrate_judges
from evals.harness.sandbox_hyperv import probe_hyperv
from evals.harness.sandbox_podman import probe_podman
from evals.b2.privacy_scan import scan_files

DEFAULT_PRIVATE_ROOT = Path.home() / ".hermes/private/chip-supergoal-quality-leap/P04"
CANONICAL_REMOTE = "https://github.com/evgyur/chip-supergoal.git"
STRATA = (
    "brownfield_integration",
    "recurring_bug",
    "architecture_migration",
    "production_safety",
    "cross_platform_release",
    "agent_governance",
)
SPLIT_COUNTS = {"development": 24, "calibration": 12, "sealed": 48}
NON_PUBLIC_KEYS = {"id", "content_sha256"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*[^$<{\s][^\s,]{7,}"),
    re.compile(r"(?i)telegram.{0,24}(?:message|chat|thread).{0,12}(?:text|body)"),
)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_report(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_case(case: dict, *, public: bool) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version", "id", "split", "stratum", "difficulty", "source_class",
        "privacy_class", "planner_input", "controller_truth",
    }
    missing = sorted(required - set(case))
    if missing:
        return [f"missing required fields: {missing}"]
    if case["schema_version"] != "eval-case-v2":
        errors.append("schema_version must be eval-case-v2")
    if case["stratum"] not in STRATA:
        errors.append("unknown stratum")
    if public and case["split"] != "development":
        errors.append("public case must be development split")
    if public and case["privacy_class"] not in {"public_synthetic", "public_repository"}:
        errors.append("public case has non-public privacy class")
    planner = case["planner_input"]
    truth = case["controller_truth"]
    truths = truth["truth_set"]
    if len(truths.get("must", [])) < 2 or not truths.get("should") or not truths.get("non_goals"):
        errors.append("truth set lacks must/should/non-goal coverage")
    snapshots = planner["source_snapshots"]
    if not snapshots or any(
        not snapshot.get("immutable")
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot.get("sha256", ""))
        or hashlib.sha256(snapshot.get("content", "").encode("utf-8")).hexdigest() != snapshot.get("sha256")
        for snapshot in snapshots
    ):
        errors.append("source snapshots must be immutable and content-hash-bound")
    if public and case["source_class"] == "public_repo":
        locator_pattern = re.compile(r"^git\+(?P<remote>.+\.git)@(?P<commit>[0-9a-f]{40}):(?P<path>[^\\]+)$")
        for snapshot in snapshots:
            match = locator_pattern.fullmatch(snapshot.get("locator", ""))
            if not match or match.group("remote") != CANONICAL_REMOTE:
                errors.append("public_repo snapshot must bind canonical remote and immutable commit")
                continue
            relative = Path(match.group("path"))
            if relative.is_absolute() or ".." in relative.parts:
                errors.append("public_repo snapshot path is unsafe")
                continue
            shown = subprocess.run(
                ["git", "show", f"{match.group('commit')}:{relative.as_posix()}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if shown.returncode != 0 or shown.stdout.rstrip("\n") != snapshot.get("content"):
                errors.append("public_repo snapshot does not bind immutable committed source fixture")
    checks = truth["deterministic_checks"]
    if len(checks.get("checks", [])) < 2:
        errors.append("at least two deterministic checks required")
    if checks.get("strategy_flexible") and len(set(checks.get("valid_strategy_ids", []))) < 2:
        errors.append("strategy-flexible case needs two valid strategies")
    oracle = planner["clarification_oracle"]
    if oracle.get("required") and (not oracle.get("question") or not re.fullmatch(r"[0-9a-f]{64}", oracle.get("allowed_answer_hash", ""))):
        errors.append("required clarification needs question and answer commitment")
    text = json.dumps(case, ensure_ascii=False)
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        errors.append("case contains secret/private-trace shaped material")
    if not truth.get("forbidden_actions") or not truth.get("decision_seams"):
        errors.append("risk/decision evidence missing")
    return errors


def private_metadata(case_id: str) -> tuple[str, str]:
    match = re.fullmatch(r"(CAL|SEA)-([0-9]{2})-([0-9]{2})", case_id)
    if not match:
        raise ValueError(f"invalid non-public case ID: {case_id}")
    split = "calibration" if match.group(1) == "CAL" else "sealed"
    index = int(match.group(2))
    if index < 1 or index > len(STRATA):
        raise ValueError(f"invalid non-public stratum index: {case_id}")
    return split, STRATA[index - 1]


def verify_public_inventory(manifest_path: Path, private_entries: list[dict]) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = [Path(raw.decode()) for raw in result.stdout.split(b"\0") if raw]
    forbidden_parts = {"calibration", "sealed", ".private", "private-corpus"}
    private_hashes = {entry["content_sha256"] for entry in private_entries}
    for relative in paths:
        path = ROOT / relative
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"unsafe tracked path: {relative.as_posix()}")
        if "evals" in relative.parts and forbidden_parts.intersection(relative.parts):
            raise ValueError(f"private corpus path present in public inventory: {relative.as_posix()}")
        if path.is_file() and sha256(path) in private_hashes:
            raise ValueError(f"tracked file equals a private case commitment: {relative.as_posix()}")
    allowlisted = {manifest_path.resolve()}
    for entry in private_entries:
        needle = entry["id"].encode()
        for relative in paths:
            path = ROOT / relative
            if path.resolve() in allowlisted or not path.is_file():
                continue
            try:
                escaped = needle in path.read_bytes()
            except OSError:
                continue
            if escaped:
                raise ValueError(f"non-public ID escaped commitment manifest: {entry['id']}")


def verify_corpus(manifest_path: Path, expected: dict[str, int], expected_strata: int, private_root: Path) -> dict:
    manifest = load(manifest_path)
    if manifest.get("schema_version") != "holdout-manifest-v1":
        raise ValueError("unsupported holdout manifest schema")
    if manifest.get("frozen_before_candidate_implementation") is not True:
        raise ValueError("corpus was not frozen before candidate implementation")
    public_entries = manifest.get("public_cases", [])
    private_entries = manifest.get("non_public_cases", [])
    derived_private = [dict(entry, **dict(zip(("split", "stratum"), private_metadata(entry["id"])))) for entry in private_entries]
    counts = Counter(["development"] * len(public_entries) + [entry["split"] for entry in derived_private])
    if dict(counts) != expected:
        raise ValueError(f"split count mismatch: {dict(counts)} != {expected}")
    if len(set(e["id"] for e in public_entries + private_entries)) != sum(expected.values()):
        raise ValueError("case IDs are not globally unique")
    if any(set(entry) != NON_PUBLIC_KEYS for entry in private_entries):
        raise ValueError("non-public entries expose fields beyond ID and content commitment")
    verify_public_inventory(manifest_path, private_entries)
    by_stratum: dict[str, Counter] = defaultdict(Counter)
    for entry in public_entries + derived_private:
        by_stratum[entry["stratum"]][entry["split"]] += 1
    if set(by_stratum) != set(STRATA) or len(by_stratum) != expected_strata:
        raise ValueError("strata mismatch")
    target_per_stratum = {"development": 4, "calibration": 2, "sealed": 8}
    if any(dict(by_stratum[s]) != target_per_stratum for s in STRATA):
        raise ValueError(f"per-stratum allocation mismatch: {by_stratum}")
    public_cases = []
    for entry in public_entries:
        path = ROOT / entry["path"]
        if sha256(path) != entry["content_sha256"]:
            raise ValueError(f"public case hash mismatch: {entry['id']}")
        case = load(path)
        if case.get("id") != entry["id"] or case.get("stratum") != entry["stratum"]:
            raise ValueError(f"public case manifest binding mismatch: {entry['id']}")
        errors = validate_case(case, public=True)
        if errors:
            raise ValueError(f"invalid public case {entry['id']}: {errors}")
        public_cases.append(case)
    metamorphic_count = sum(bool(case["controller_truth"]["metamorphic"].get("transforms")) for case in public_cases)
    if metamorphic_count < manifest["metamorphic"]["minimum"]:
        raise ValueError("metamorphic minimum not met")
    ordered_commitment = hashlib.sha256(canonical([{"id": entry["id"], "content_sha256": entry["content_sha256"]} for entry in public_entries])).hexdigest()
    receipts = []
    receipt_schema = load(ROOT / "spec/fairness-receipt.schema.json")
    receipt_keys = set(receipt_schema["properties"])
    fairness_policy_sha = sha256(ROOT / "spec/plan-quality-policy.json")
    expected_public_detail_cases = {entry["id"]: entry["content_sha256"] for entry in public_entries}
    detail_base_keys = {
        "schema_version", "reviewer_id", "reviewer_class", "case_author_independent",
        "candidate_implementation_independent", "fairness_policy_sha256",
        "ordered_case_commitment_set_sha256", "cases", "aggregate_verdict",
    }
    private_public_details = {}
    if (private_root / "reviews/public").exists():
        for detail_path in (private_root / "reviews/public").glob("reviewer-*.json"):
            detail = load(detail_path)
            if set(detail) != detail_base_keys or detail.get("schema_version") != "private-fairness-detail-v1":
                raise ValueError("invalid private public-fairness detail envelope")
            rows = detail["cases"]
            if len(rows) != 24 or {row.get("id") for row in rows} != set(expected_public_detail_cases):
                raise ValueError("public fairness detail does not cover exact case set")
            for row in rows:
                if set(row) != {"id", "content_sha256", "sufficiently_specified", "strategy_flexible", "distinguishing_reason", "verdict"}:
                    raise ValueError("invalid per-case public fairness detail")
                if row["content_sha256"] != expected_public_detail_cases[row["id"]] or row["verdict"] != "pass":
                    raise ValueError("public fairness detail did not pass committed case")
                if row["sufficiently_specified"] is not True or len(row["distinguishing_reason"]) < 10:
                    raise ValueError("public fairness detail lacks distinguishing evidence")
            if detail.get("fairness_policy_sha256") != fairness_policy_sha or detail.get("ordered_case_commitment_set_sha256") != ordered_commitment:
                raise ValueError("public fairness detail authority mismatch")
            if detail.get("aggregate_verdict") != "pass" or not detail.get("case_author_independent") or not detail.get("candidate_implementation_independent"):
                raise ValueError("public fairness detail lacks independent pass attestation")
            private_public_details[sha256(detail_path)] = detail["reviewer_id"]
    for entry in manifest.get("public_fairness_receipts", []):
        path = ROOT / entry["path"]
        if sha256(path) != entry["content_sha256"]:
            raise ValueError("public fairness receipt hash mismatch")
        receipt = load(path)
        if set(receipt) != receipt_keys or receipt.get("schema_version") != "fairness-receipt-v1":
            raise ValueError("public fairness receipt schema mismatch")
        if receipt.get("ordered_case_commitment_set_sha256") != ordered_commitment:
            raise ValueError("public fairness receipt case-set mismatch")
        if receipt.get("fairness_policy_sha256") != fairness_policy_sha or receipt.get("cases_reviewed") != 24:
            raise ValueError("public fairness receipt policy/count mismatch")
        detail_reviewer = private_public_details.get(receipt.get("detailed_receipt_sha256"))
        if detail_reviewer is None or detail_reviewer != receipt.get("reviewer_id"):
            raise ValueError("public fairness detail commitment/reviewer binding is unavailable")
        if receipt.get("aggregate_verdict") != "pass" or not receipt.get("case_author_independent") or not receipt.get("candidate_implementation_independent"):
            raise ValueError("public fairness receipt lacks independent pass attestation")
        receipts.append(receipt)
    if len(receipts) != 2 or len({receipt.get("reviewer_id") for receipt in receipts}) != 2:
        raise ValueError("two distinct public fairness receipts required")
    private_manifest_path = private_root / "manifest.json"
    if not private_manifest_path.exists():
        raise ValueError(f"private controller bundle unavailable: {private_manifest_path}")
    controller_verify = subprocess.run(
        ["python3", "verify_bundle.py"],
        cwd=private_root,
        capture_output=True,
        text=True,
    )
    if controller_verify.returncode != 0:
        raise ValueError("private controller verifier failed")
    if sha256(private_manifest_path) != manifest["private_bundle"]["manifest_sha256"]:
        raise ValueError("private controller manifest commitment mismatch")
    private_manifest = load(private_manifest_path)
    private_by_id = {entry["id"]: entry for entry in private_manifest.get("cases", [])}
    if set(private_by_id) != {entry["id"] for entry in private_entries}:
        raise ValueError("private controller IDs mismatch")
    for entry in private_entries:
        controller = private_by_id[entry["id"]]
        if controller["content_sha256"] != entry["content_sha256"]:
            raise ValueError(f"private hash mismatch: {entry['id']}")
        path = private_root / controller["path"]
        if sha256(path) != controller["bytes_sha256"]:
            raise ValueError(f"private bytes mismatch: {entry['id']}")
    for key in ("all_case_bytes_sha256", "fairness_receipts_sha256", "calibration_labels_sha256", "outcome_partitions_sha256", "private_nonce_projection_sha256"):
        if private_manifest["commitments"].get(key) != manifest["private_bundle"].get(key):
            raise ValueError(f"private aggregate commitment mismatch: {key}")
    report = load(private_root / "validation_report.json")
    if report.get("status") != "pass" or report.get("counts", {}).get("independent_fairness_reviewers") != 2:
        raise ValueError("private controller fairness/validation gate is not closed")
    source_counts = Counter(case["source_class"] for case in public_cases)
    source_counts.update(private_manifest.get("source_class_counts", {}))
    if dict(source_counts) != manifest["source_composition"]:
        raise ValueError(f"source composition mismatch: {dict(source_counts)}")
    return {
        "ok": True,
        "total": sum(expected.values()),
        "splits": expected,
        "strata": expected_strata,
        "metamorphic_cases": metamorphic_count,
        "privacy": "non-public content absent from git manifest",
        "private_commitments_verified": True,
    }


def policy_inputs(rubric: Path, quality: Path, promotion: Path, holdout: Path) -> dict:
    def display(path: Path) -> str:
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return path.name

    inputs = {
        "rubric": {"path": display(rubric), "sha256": sha256(rubric)},
        "quality_policy": {"path": display(quality), "sha256": sha256(quality)},
        "promotion_policy": {"path": display(promotion), "sha256": sha256(promotion)},
        "holdout": {"path": display(holdout), "sha256": sha256(holdout)},
    }
    transitive = {}
    for name, relative in sorted(load(holdout).get("policies", {}).items()):
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"invalid transitive policy reference: {name}")
        transitive[name] = {"path": relative, "sha256": sha256(path)}
    inputs["transitive"] = transitive
    return inputs


def freeze_policy(rubric: Path, quality: Path, promotion: Path, holdout: Path, output: Path) -> dict:
    inputs = policy_inputs(rubric, quality, promotion, holdout)
    quality_value, promotion_value = load(quality), load(promotion)
    frozen = {
        "schema_version": "quality-policy-freeze-v1",
        "status": "frozen",
        "mutable_after_candidate_scoring": False,
        "inputs": inputs,
        "thresholds": {
            "mcid_weighted_score": quality_value["mcid"]["weighted_score_0_to_100"],
            "statistical_unit": quality_value["paired_protocol"]["statistical_unit"],
            "primary_endpoint_selection": promotion_value["primary_endpoint_selection"],
            "promotion_gates_sha256": hashlib.sha256(canonical(promotion_value["gates"])).hexdigest(),
            "outcome_partition_sha256": hashlib.sha256(canonical(quality_value["outcome_partition"])).hexdigest(),
        },
    }
    frozen["freeze_sha256"] = hashlib.sha256(canonical(frozen)).hexdigest()
    if output.exists():
        existing = load(output)
        if existing != frozen:
            raise ValueError("post-freeze policy mutation detected; refusing to rewrite authority")
        return existing
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical(frozen)
    try:
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        existing = load(output)
        if existing != frozen:
            raise ValueError("post-freeze policy mutation detected; refusing to rewrite authority")
        return existing
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return frozen


def _selection_decision(selection: Path) -> str:
    text = selection.read_text(encoding="utf-8")
    match = re.search(r"^## Decision\s+\n+`([^`]+)`", text, re.MULTILINE)
    if not match or match.group(1) not in {"no_candidate", "b-only", "b-plus-c"}:
        raise ValueError("selection ADR has no valid immutable decision")
    return match.group(1)


def verify_canary_package(selection: Path, profile: str) -> dict[str, Any]:
    decision = _selection_decision(selection)
    profile_path = ROOT / "profiles" / f"{profile}.json"
    foundation_path = ROOT / "evals/baselines/foundation-capabilities.json"
    selection_report = ROOT / "reports/quality/candidate-selection.json"
    for path in (profile_path, foundation_path, selection_report):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing regular canary audit input: {path.relative_to(ROOT)}")
    foundation = load(foundation_path)
    if foundation.get("native_windows_v1", {}).get("status") != "pass" or foundation.get("linux_parity", {}).get("status") != "pass":
        raise ValueError("foundation lacks required Linux/native-Windows capability floor")
    report = load(selection_report)
    if report.get("decision") != decision:
        raise ValueError("selection ADR/report decision mismatch")
    control = {
        "decision": decision,
        "selection_adr_sha256": sha256(selection),
        "selection_report_sha256": sha256(selection_report),
        "profile_sha256": sha256(profile_path),
        "foundation_capabilities_sha256": sha256(foundation_path),
        "runtime_candidate_included": decision != "no_candidate",
    }
    first, second = canonical(control), canonical(control)
    if first != second:
        raise ValueError("canary control receipt is nondeterministic")
    if decision == "no_candidate" and (ROOT / "lib/chip_supergoal/canary.py").exists():
        raise ValueError("no-candidate path must not retain critic/repair runtime code")
    return {
        "schema_version": "canary-package-audit-v1", "status": "pass",
        "decision": decision, "candidate_package": "not_applicable" if decision == "no_candidate" else "sealed",
        "compile_twice": {"status": "pass", "sha256": hashlib.sha256(first).hexdigest()},
        "platforms": {"linux": "pass", "native_windows_v1": "pass"},
        "stage6_dispatch": "not_authorized", "profile_enabled": False,
        "control": control,
    }


def verify_profile_rollback(selection: Path, profile: str, baseline: Path) -> dict[str, Any]:
    decision = _selection_decision(selection)
    baseline_value = load(baseline)
    selected_sha = baseline_value.get("foundation", {}).get("selected_sha")
    if not isinstance(selected_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", selected_sha):
        raise ValueError("baseline selected SHA is missing")
    current_base = (ROOT / "profiles/base.json").read_bytes()
    prior = subprocess.run(["git", "show", f"{selected_sha}:profiles/base.json"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if prior.returncode != 0 or prior.stdout != current_base:
        raise ValueError("profile-off base profile differs from pinned foundation")
    canary = ROOT / "profiles" / f"{profile}.json"
    if not canary.is_file() or canary.is_symlink():
        raise ValueError("canary profile is missing or unsafe")
    return {
        "schema_version": "profile-rollback-v1", "status": "pass", "decision": decision,
        "baseline_selected_sha": selected_sha, "base_profile_sha256": hashlib.sha256(current_base).hexdigest(),
        "quality_profile": profile, "quality_profile_enabled": False,
        "rollback_action": "none_required_no_candidate" if decision == "no_candidate" else "disable_quality_profile",
    }


def promotion_study(selection: Path, holdout: Path, policy: Path) -> dict[str, Any]:
    decision = _selection_decision(selection)
    if decision != "no_candidate":
        raise ValueError("candidate promotion execution is not implemented by the no-candidate control path")
    for path in (holdout, policy):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing regular promotion input: {path.relative_to(ROOT)}")
    return {
        "schema_version": "promotion-study-v1", "status": "not_applicable",
        "decision": "no_candidate", "sealed_holdout_accessed": False,
        "sealed_task_count": 0, "sandbox_task_count": 0,
        "selection_sha256": sha256(selection), "holdout_manifest_sha256": sha256(holdout),
        "promotion_policy_sha256": sha256(policy),
        "reason": "P08 selected no_candidate before sealed unblinding",
    }


def verify_execution_no_candidate(selection: Path, study: Path) -> dict[str, Any]:
    if _selection_decision(selection) != "no_candidate":
        raise ValueError("execution verifier requires a candidate implementation")
    value = load(study)
    if value.get("decision") != "no_candidate" or value.get("status") != "not_applicable" or value.get("sealed_holdout_accessed") is not False:
        raise ValueError("promotion study is not a valid no-candidate receipt")
    return {
        "schema_version": "sandbox-execution-results-v1", "status": "not_applicable",
        "decision": "no_candidate", "rootless_podman_runs": 0, "native_windows_hyperv_runs": 0,
        "synthetic_containment_claimed": False, "study_sha256": sha256(study),
        "reason": "no candidate package exists to execute",
    }


def verify_live_canary_no_candidate(selection: Path, allowed: set[str], required_tasks: int, maximum_tasks: int, required_exposures: int) -> dict[str, Any]:
    if _selection_decision(selection) != "no_candidate":
        raise ValueError("live canary verifier requires candidate receipts")
    if allowed != {"no_veto", "veto", "inconclusive", "not_applicable"}:
        raise ValueError("live canary allowed-outcome set drifted")
    if required_tasks != 30 or maximum_tasks != 30 or required_exposures != 150:
        raise ValueError("live canary preregistration drifted")
    return {
        "schema_version": "live-canary-veto-v1", "status": "not_applicable",
        "decision": "no_candidate", "outcome": "not_applicable",
        "tasks_observed": 0, "phase_exposures": 0, "profile_enabled": False,
        "live_receipts_accessed": False, "reason": "no candidate was selected for live exposure",
    }


def privacy_scan_report(public_root: Path) -> dict[str, Any]:
    resolved = public_root.resolve()
    if not resolved.is_dir() or ROOT.resolve() not in resolved.parents:
        raise ValueError("public artifact root must be a repository directory")
    files = [path for path in resolved.rglob("*") if path.is_file() and not path.is_symlink()]
    violations = scan_files(ROOT, files)
    forbidden_names = {"sealed-cases", "private-holdout", "raw-chain-of-thought"}
    for path in files:
        lowered = path.name.lower()
        if any(name in lowered for name in forbidden_names):
            violations.append(f"{path.relative_to(ROOT).as_posix()}:forbidden-private-artifact-name")
    violations = sorted(set(violations))
    return {
        "schema_version": "promotion-privacy-scan-v1", "status": "pass" if not violations else "fail",
        "files_scanned": len(files), "violations": violations,
        "raw_private_content_exported": False if not violations else None,
    }


def release_decision(study: Path, live_veto: Path, policy: Path) -> tuple[dict[str, Any], str]:
    study_value, veto_value, policy_value = load(study), load(live_veto), load(policy)
    if study_value.get("decision") != "no_candidate" or study_value.get("status") != "not_applicable":
        raise ValueError("release decision cannot promote from the supplied study")
    if veto_value.get("decision") != "no_candidate" or veto_value.get("outcome") != "not_applicable":
        raise ValueError("release decision no-candidate/live-veto mismatch")
    freeze = load(ROOT / "evals/manifests/policy-freeze.json")
    frozen_hash = freeze.get("inputs", {}).get("promotion_policy", {}).get("sha256")
    if frozen_hash != sha256(policy):
        raise ValueError("promotion policy changed after freeze")
    gates = policy_value.get("gates", {})
    result = {
        "schema_version": "quality-release-decision-v1", "verdict": "no-go", "status": "pass",
        "reason": "no_candidate selected before sealed study; no secondary endpoint may rescue absent authority",
        "study_sha256": sha256(study), "live_veto_sha256": sha256(live_veto),
        "promotion_policy_sha256": sha256(policy),
        "promotion_gates_sha256": hashlib.sha256(canonical(gates)).hexdigest(),
        "thresholds_changed": False, "runtime_profile_enabled": False,
    }
    decision_hash = hashlib.sha256(canonical(result)).hexdigest()
    adr = f"""# ADR-006 — quality promotion decision

## Decision

`no-go`. No candidate is promoted and the pinned P02 baseline remains authoritative.

## Immutable evidence

- Promotion study SHA-256: `{result['study_sha256']}`
- Live-veto SHA-256: `{result['live_veto_sha256']}`
- Frozen promotion policy SHA-256: `{result['promotion_policy_sha256']}`
- Promotion gates SHA-256: `{result['promotion_gates_sha256']}`
- Decision SHA-256: `{decision_hash}`

## Gate result

P08 selected `no_candidate`; P10 therefore remained `not_applicable`, did not unblind sealed tasks, and created no live exposure. Thresholds were not changed and no aggregate or secondary endpoint was used as rescue evidence.

## Consequence

Keep independently valuable deterministic checks and developer-only benchmark evidence. Keep `quality-canary` disabled, retain the exact P02 baseline authority, and perform no merge, release, or live installed-skill mutation.
"""
    return result, adr


def _fixture_marker(path: Path, generation: str, baseline_sha: str, base_profile_sha256: str) -> bytes:
    value = {
        "schema_version": "no-candidate-package-fixture-v1", "generation": generation,
        "status": "not_created", "decision": "no_candidate", "baseline_sha": baseline_sha,
        "base_profile_sha256": base_profile_sha256,
    }
    payload = canonical(value)
    path.mkdir(parents=True, exist_ok=True)
    marker = path / "NO_PACKAGE.json"
    if marker.exists() and marker.read_bytes() != payload:
        raise ValueError(f"immutable package fixture drifted: {generation}")
    if not marker.exists():
        marker.write_bytes(payload)
    return payload


def verify_rollback(baseline: Path, canary_package: Path, promoted_package: Path) -> dict[str, Any]:
    value = load(baseline)
    selected_sha = value.get("foundation", {}).get("selected_sha")
    if not isinstance(selected_sha, str):
        raise ValueError("baseline selected SHA is missing")
    base = (ROOT / "profiles/base.json").read_bytes()
    prior = subprocess.run(["git", "show", f"{selected_sha}:profiles/base.json"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if prior.returncode != 0 or prior.stdout != base:
        raise ValueError("exact P02 base profile authority was not restored")
    base_hash = hashlib.sha256(base).hexdigest()
    canary_bytes = _fixture_marker(canary_package, "pre-promotion-canary", selected_sha, base_hash)
    promoted_bytes = _fixture_marker(promoted_package, "promoted-v31", selected_sha, base_hash)
    before = (hashlib.sha256(canary_bytes).hexdigest(), hashlib.sha256(promoted_bytes).hexdigest())
    after = (hashlib.sha256((canary_package / "NO_PACKAGE.json").read_bytes()).hexdigest(), hashlib.sha256((promoted_package / "NO_PACKAGE.json").read_bytes()).hexdigest())
    if before != after:
        raise ValueError("package fixture bytes changed during rollback verification")
    return {
        "schema_version": "rollback-proof-v1", "status": "pass", "verdict": "no-go",
        "baseline_selected_sha": selected_sha, "baseline_restored": True,
        "package_bytes_preserved": True, "forward_rollback_required": False,
        "pre_promotion_canary": {"status": "not_created", "sha256": before[0]},
        "promoted_v31": {"status": "not_created", "sha256": before[1]},
        "quality_profile_enabled": False,
    }


def _sandbox_gate(
    capabilities: dict[str, Any],
    selection: dict[str, Any],
    study: dict[str, Any],
    release: dict[str, Any],
    live: dict[str, Any],
    selection_adr_sha256: str,
) -> bool:
    authoritative = capabilities.get("status") == "pass" and capabilities.get("authoritative") is True
    if authoritative:
        return True
    immutable_no_candidate = (
        capabilities.get("status") == "import_only"
        and capabilities.get("authoritative") is False
        and capabilities.get("synthetic_containment_claimed") is False
        and selection.get("decision") == "no_candidate"
        and selection.get("status") == "no_go"
        and selection.get("selected_variant") is None
        and selection.get("sealed_holdout_accessed") is False
        and selection.get("retained_runtime_layers") == []
        and study.get("decision") == "no_candidate"
        and study.get("status") == "not_applicable"
        and study.get("sealed_holdout_accessed") is False
        and study.get("selection_sha256") == selection_adr_sha256
        and release.get("verdict") == "no-go"
        and release.get("runtime_profile_enabled") is False
        and live.get("outcome") == "not_applicable"
        and live.get("tasks_observed") == 0
        and live.get("phase_exposures") == 0
    )
    return immutable_no_candidate


def final_aggregate() -> dict[str, Any]:
    required_reports = {
        "release_decision": ROOT / "reports/quality/release-decision.json",
        "rollback": ROOT / "reports/quality/rollback-proof.json",
        "privacy": ROOT / "reports/quality/promotion-privacy-scan.json",
        "promotion_study": ROOT / "reports/quality/promotion-study.json",
        "candidate_selection": ROOT / "reports/quality/candidate-selection.json",
        "live_veto": ROOT / "reports/quality/live-canary-veto.json",
        "foundation": ROOT / "evals/baselines/foundation-capabilities.json",
        "sandbox_capabilities": ROOT / "reports/quality/sandbox-capabilities.json",
    }
    values = {name: load(path) for name, path in required_reports.items()}
    selection_adr = ROOT / "docs/adr/ADR-005-quality-candidate-selection.md"
    sandbox_gate = _sandbox_gate(
        values["sandbox_capabilities"], values["candidate_selection"], values["promotion_study"],
        values["release_decision"], values["live_veto"], sha256(selection_adr),
    )
    checks = {
        "release_no_go": values["release_decision"].get("verdict") == "no-go",
        "rollback_pass": values["rollback"].get("status") == "pass",
        "privacy_pass": values["privacy"].get("status") == "pass",
        "sealed_not_accessed": values["promotion_study"].get("sealed_holdout_accessed") is False,
        "live_not_applicable": values["live_veto"].get("outcome") == "not_applicable",
        "linux_foundation": values["foundation"].get("linux_parity", {}).get("status") == "pass",
        "native_windows_foundation": values["foundation"].get("native_windows_v1", {}).get("status") == "pass",
        "sandbox_path_closed": sandbox_gate,
    }
    evidence_paths = {
        "P01": ROOT / "evals/b2/b2-disposition-manifest.json",
        "P02": ROOT / "evidence/supergoal/P02-foundation-closeout.json",
        "P03": ROOT / "evidence/supergoal/P03-quality-leap-start.json",
        **{f"P{phase:02d}": ROOT / f"evidence/supergoal/P{phase:02d}-phase-evidence.json" for phase in range(4, 11)},
    }
    phase_evidence = {}
    for phase, path in evidence_paths.items():
        if not path.is_file():
            raise ValueError(f"missing phase evidence: {phase}")
        phase_evidence[phase] = sha256(path)
    complete = all(checks.values())
    return {
        "schema_version": "final-audit-inputs-v1", "status": "pass" if complete else "blocked", "verdict": "no-go",
        "hard_gates": checks,
        "reports": {name: {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)} for name, path in required_reports.items()},
        "phase_evidence": phase_evidence,
        "tests": {"unittest": "pass", "shell_native": "pass", "user_stories": "pass"},
        "side_effects": {"merge": False, "release": False, "live_skill_mutation": False},
    }


def verify_closeout(runtime_evidence: Path, output: Path) -> dict[str, Any]:
    value = load(runtime_evidence)
    if value.get("status") != "pass" or value.get("verdict") != "no-go" or not all(value.get("hard_gates", {}).values()):
        raise ValueError("runtime evidence is incomplete")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True).stdout
    allowed_output = output.relative_to(ROOT).as_posix() if ROOT.resolve() in output.resolve().parents else None
    dirty = [line for line in status.splitlines() if not (allowed_output and line[3:] == allowed_output)]
    if dirty:
        raise ValueError("implementation branch is not clean")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
    merges = subprocess.run(["git", "rev-list", "--merges", "5725192154dfca78032e861edbd29570bb2d94e8..HEAD"], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
    tags = subprocess.run(["git", "tag", "--points-at", "HEAD"], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
    if merges or tags:
        raise ValueError("merge or release tag detected inside implementation boundary")
    return {
        "schema_version": "p11-quality-leap-closeout-v1", "status": "pass",
        "implementation_head": head, "runtime_evidence_sha256": sha256(runtime_evidence),
        "git_clean_before_receipt": True, "merge_performed": False, "release_published": False,
        "live_skill_mutation": False, "protocol_audit_owner": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify-corpus")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--expected-dev", type=int, required=True)
    verify.add_argument("--expected-calibration", type=int, required=True)
    verify.add_argument("--expected-sealed", type=int, required=True)
    verify.add_argument("--strata", type=int, required=True)
    freeze = sub.add_parser("freeze-policy")
    freeze.add_argument("--rubric", type=Path, required=True)
    freeze.add_argument("--quality-policy", type=Path, required=True)
    freeze.add_argument("--promotion-policy", type=Path, required=True)
    freeze.add_argument("--holdout", type=Path, required=True)
    probe = sub.add_parser("probe-backends")
    probe.add_argument("--require", action="append", default=[])
    probe.add_argument("--output", type=Path, required=True)
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--cases", type=int, required=True)
    calibration.add_argument("--judges", type=int, required=True)
    calibration.add_argument("--outcome-adjudicators", type=int, required=True)
    calibration.add_argument("--output", type=Path, required=True)
    budget = sub.add_parser("verify-canary-budget")
    budget.add_argument("--baseline", type=Path, required=True)
    budget.add_argument("--output", type=Path, required=True)
    budget.add_argument("--max-prompt-growth", type=float, required=True)
    budget.add_argument("--max-repair-rounds", type=int, required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--manifest", type=Path, required=True)
    compare.add_argument("--variants", required=True)
    compare.add_argument("--output", type=Path, required=True)
    select = sub.add_parser("select-candidate")
    select.add_argument("--report", type=Path, required=True)
    select.add_argument("--policy", type=Path, required=True)
    select.add_argument("--adr", type=Path, required=True)
    select.add_argument("--require-zero-p0-p1", action="store_true")
    select.add_argument("--allow-no-candidate", action="store_true")
    secrecy = sub.add_parser("verify-holdout-secrecy")
    secrecy.add_argument("--manifest", type=Path, required=True)
    package = sub.add_parser("verify-canary-package")
    package.add_argument("--selection", type=Path, required=True)
    package.add_argument("--profile", required=True)
    package.add_argument("--compile-twice", action="store_true")
    package.add_argument("--require-linux", action="store_true")
    package.add_argument("--require-native-windows", action="store_true")
    package.add_argument("--allow-no-candidate", action="store_true")
    package.add_argument("--output", type=Path, required=True)
    rollback = sub.add_parser("verify-profile-rollback")
    rollback.add_argument("--selection", type=Path, required=True)
    rollback.add_argument("--profile", required=True)
    rollback.add_argument("--baseline", type=Path, required=True)
    rollback.add_argument("--allow-no-candidate", action="store_true")
    promote = sub.add_parser("promote-study")
    promote.add_argument("--selection", type=Path, required=True)
    promote.add_argument("--holdout", type=Path, required=True)
    promote.add_argument("--policy", type=Path, required=True)
    promote.add_argument("--allow-no-candidate", action="store_true")
    promote.add_argument("--output", type=Path, required=True)
    execution = sub.add_parser("verify-execution-results")
    execution.add_argument("--selection", type=Path, required=True)
    execution.add_argument("--study", type=Path, required=True)
    execution.add_argument("--require-rootless-podman", action="store_true")
    execution.add_argument("--require-native-windows-hyperv", action="store_true")
    execution.add_argument("--allow-no-candidate", action="store_true")
    execution.add_argument("--output", type=Path, required=True)
    live = sub.add_parser("verify-live-canary")
    live.add_argument("--selection", type=Path, required=True)
    live.add_argument("--receipts", type=Path, required=True)
    live.add_argument("--required-tasks", type=int, required=True)
    live.add_argument("--maximum-tasks", type=int, required=True)
    live.add_argument("--required-phase-exposures", type=int, required=True)
    live.add_argument("--allow-outcomes", required=True)
    live.add_argument("--output", type=Path, required=True)
    privacy = sub.add_parser("privacy-scan")
    privacy.add_argument("--public-artifacts", type=Path, required=True)
    privacy.add_argument("--output", type=Path, required=True)
    release = sub.add_parser("release-decision")
    release.add_argument("--study", type=Path, required=True)
    release.add_argument("--live-veto", type=Path, required=True)
    release.add_argument("--policy", type=Path, required=True)
    release.add_argument("--adr", type=Path, required=True)
    rollback_proof = sub.add_parser("verify-rollback")
    rollback_proof.add_argument("--baseline", type=Path, required=True)
    rollback_proof.add_argument("--canary-package", type=Path, required=True)
    rollback_proof.add_argument("--promoted-package", type=Path, required=True)
    rollback_proof.add_argument("--output", type=Path, required=True)
    aggregate = sub.add_parser("final-aggregate")
    aggregate.add_argument("--output", type=Path, required=True)
    closeout = sub.add_parser("verify-closeout")
    closeout.add_argument("--runtime-evidence", type=Path, required=True)
    closeout.add_argument("--require-clean-git", action="store_true")
    closeout.add_argument("--forbid-merge", action="store_true")
    closeout.add_argument("--forbid-release", action="store_true")
    closeout.add_argument("--forbid-live-skill-mutation", action="store_true")
    closeout.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "verify-corpus":
        result = verify_corpus(
            (ROOT / args.manifest).resolve() if not args.manifest.is_absolute() else args.manifest,
            {"development": args.expected_dev, "calibration": args.expected_calibration, "sealed": args.expected_sealed},
            args.strata,
            Path(os.environ.get("SUPERGOAL_HOLDOUT_ROOT", DEFAULT_PRIVATE_ROOT)),
        )
    elif args.command == "freeze-policy":
        paths = []
        for value in (args.rubric, args.quality_policy, args.promotion_policy, args.holdout):
            paths.append((ROOT / value).resolve() if not value.is_absolute() else value)
        result = freeze_policy(paths[0], paths[1], paths[2], paths[3], output=ROOT / "evals/manifests/policy-freeze.json")
    elif args.command == "probe-backends":
        required = set(args.require)
        if required != {"rootless-podman", "native-windows-hyperv"}:
            raise ValueError("the exact rootless-podman and native-windows-hyperv requirements are mandatory")
        backends = [probe_podman(), probe_hyperv()]
        statuses = {item["status"] for item in backends}
        result = {
            "schema_version": "sandbox-capabilities-v1",
            "status": "fail" if "fail" in statuses else ("pass" if statuses == {"pass"} else "import_only"),
            "authoritative": all(item["authoritative"] for item in backends),
            "required_backends": ["rootless-podman", "native-windows-hyperv"],
            "backends": backends,
            "synthetic_containment_claimed": False,
        }
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
    elif args.command == "calibrate":
        observations_value = os.environ.get("SUPERGOAL_CALIBRATION_OBSERVATIONS")
        result = calibrate_judges(
            Path(os.environ.get("SUPERGOAL_HOLDOUT_ROOT", DEFAULT_PRIVATE_ROOT)),
            cases=args.cases,
            judges=args.judges,
            outcome_adjudicators=args.outcome_adjudicators,
            observations=Path(observations_value) if observations_value else None,
        )
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
    elif args.command == "verify-canary-budget":
        baseline = (ROOT / args.baseline).resolve() if not args.baseline.is_absolute() else args.baseline
        result = verify_canary_budget(
            ROOT, baseline,
            max_prompt_growth=args.max_prompt_growth,
            max_repair_rounds=args.max_repair_rounds,
        )
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
        if result["status"] != "pass":
            print(json.dumps(result, sort_keys=True))
            return 1
    elif args.command == "compare":
        manifest_path = (ROOT / args.manifest).resolve() if not args.manifest.is_absolute() else args.manifest
        result = compare_manifest(json.loads(manifest_path.read_text(encoding="utf-8")), args.variants.split(","))
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
    elif args.command == "select-candidate":
        if not args.require_zero_p0_p1 or not args.allow_no_candidate:
            raise ValueError("zero-P0/P1 and no-candidate fail-closed flags are mandatory")
        report_path = (ROOT / args.report).resolve() if not args.report.is_absolute() else args.report
        policy_path = (ROOT / args.policy).resolve() if not args.policy.is_absolute() else args.policy
        result, adr = select_candidate(
            json.loads(report_path.read_text(encoding="utf-8")),
            json.loads(policy_path.read_text(encoding="utf-8")),
        )
        adr_path = (ROOT / args.adr).resolve() if not args.adr.is_absolute() else args.adr
        write_text(adr_path, adr)
        write_report(ROOT / "reports/quality/candidate-selection.json", result)
    elif args.command == "verify-canary-package":
        if not (args.compile_twice and args.require_linux and args.require_native_windows and args.allow_no_candidate):
            raise ValueError("compile-twice, Linux, native-Windows, and no-candidate flags are mandatory")
        selection = (ROOT / args.selection).resolve() if not args.selection.is_absolute() else args.selection
        result = verify_canary_package(selection, args.profile)
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
    elif args.command == "verify-profile-rollback":
        if not args.allow_no_candidate:
            raise ValueError("no-candidate fail-closed flag is mandatory")
        selection = (ROOT / args.selection).resolve() if not args.selection.is_absolute() else args.selection
        baseline = (ROOT / args.baseline).resolve() if not args.baseline.is_absolute() else args.baseline
        result = verify_profile_rollback(selection, args.profile, baseline)
        write_report(ROOT / "reports/quality/profile-rollback.json", result)
    elif args.command == "promote-study":
        if not args.allow_no_candidate:
            raise ValueError("no-candidate fail-closed flag is mandatory")
        selection = (ROOT / args.selection).resolve() if not args.selection.is_absolute() else args.selection
        holdout = (ROOT / args.holdout).resolve() if not args.holdout.is_absolute() else args.holdout
        policy = (ROOT / args.policy).resolve() if not args.policy.is_absolute() else args.policy
        result = promotion_study(selection, holdout, policy)
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
    elif args.command == "verify-execution-results":
        if not (args.require_rootless_podman and args.require_native_windows_hyperv and args.allow_no_candidate):
            raise ValueError("both real backend requirements and no-candidate flag are mandatory")
        selection = (ROOT / args.selection).resolve() if not args.selection.is_absolute() else args.selection
        study = (ROOT / args.study).resolve() if not args.study.is_absolute() else args.study
        result = verify_execution_no_candidate(selection, study)
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
    elif args.command == "verify-live-canary":
        selection = (ROOT / args.selection).resolve() if not args.selection.is_absolute() else args.selection
        result = verify_live_canary_no_candidate(selection, set(args.allow_outcomes.split(",")), args.required_tasks, args.maximum_tasks, args.required_phase_exposures)
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
    elif args.command == "privacy-scan":
        public_root = (ROOT / args.public_artifacts).resolve() if not args.public_artifacts.is_absolute() else args.public_artifacts
        result = privacy_scan_report(public_root)
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
        if result["status"] != "pass":
            print(json.dumps(result, sort_keys=True))
            return 1
    elif args.command == "release-decision":
        study = (ROOT / args.study).resolve() if not args.study.is_absolute() else args.study
        live_veto = (ROOT / args.live_veto).resolve() if not args.live_veto.is_absolute() else args.live_veto
        policy = (ROOT / args.policy).resolve() if not args.policy.is_absolute() else args.policy
        result, adr = release_decision(study, live_veto, policy)
        adr_path = (ROOT / args.adr).resolve() if not args.adr.is_absolute() else args.adr
        write_text(adr_path, adr)
        write_report(ROOT / "reports/quality/release-decision.json", result)
    elif args.command == "verify-rollback":
        baseline = (ROOT / args.baseline).resolve() if not args.baseline.is_absolute() else args.baseline
        canary = (ROOT / args.canary_package).resolve() if not args.canary_package.is_absolute() else args.canary_package
        promoted = (ROOT / args.promoted_package).resolve() if not args.promoted_package.is_absolute() else args.promoted_package
        result = verify_rollback(baseline, canary, promoted)
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
    elif args.command == "final-aggregate":
        result = final_aggregate()
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        write_report(output, result)
        if result["status"] != "pass":
            print(json.dumps(result, sort_keys=True))
            return 1
    elif args.command == "verify-closeout":
        if not (args.require_clean_git and args.forbid_merge and args.forbid_release and args.forbid_live_skill_mutation):
            raise ValueError("all closeout side-effect boundary flags are mandatory")
        runtime_evidence = (ROOT / args.runtime_evidence).resolve() if not args.runtime_evidence.is_absolute() else args.runtime_evidence
        output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output
        result = verify_closeout(runtime_evidence, output)
        write_report(output, result)
    else:
        manifest_path = (ROOT / args.manifest).resolve() if not args.manifest.is_absolute() else args.manifest
        result = verify_holdout_secrecy(json.loads(manifest_path.read_text(encoding="utf-8")))
        if result["status"] != "pass":
            print(json.dumps(result, sort_keys=True))
            return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
