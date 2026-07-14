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

from evals.harness.calibration import calibrate as calibrate_judges
from evals.harness.sandbox_hyperv import probe_hyperv
from evals.harness.sandbox_podman import probe_podman

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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(canonical(value))
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
    else:
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
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
