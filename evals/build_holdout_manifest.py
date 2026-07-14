#!/usr/bin/env python3
"""Publish a content-free commitment manifest for corpus v0."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "evals/corpus/public"
PRIVATE_ROOT = Path.home() / ".hermes/private/chip-supergoal-quality-leap/P04"
OUTPUT = ROOT / "evals/manifests/holdout-manifest.json"


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    private_manifest_path = PRIVATE_ROOT / "manifest.json"
    verified = subprocess.run(["python3", "verify_bundle.py"], cwd=PRIVATE_ROOT, capture_output=True, text=True)
    if verified.returncode != 0:
        raise ValueError("private controller verification failed")
    private = json.loads(private_manifest_path.read_text(encoding="utf-8"))
    if private.get("status") != "pass" or len(private.get("review_receipts", [])) != 2:
        raise ValueError("private fairness gate is not complete")
    public_entries = []
    for path in sorted(PUBLIC_ROOT.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        public_entries.append({
            "id": case["id"],
            "path": path.relative_to(ROOT).as_posix(),
            "content_sha256": digest(path),
            "split": "development",
            "stratum": case["stratum"],
        })
    non_public = []
    for entry in private["cases"]:
        non_public.append({
            "id": entry["id"],
            "content_sha256": entry["content_sha256"],
        })
    source_counts = Counter({"public_repo": len(public_entries)})
    source_counts.update(private.get("source_class_counts", {}))
    expected_sources = {"historical": 42, "public_repo": 24, "adversarial": 18}
    if dict(source_counts) != expected_sources:
        raise ValueError(f"private corpus source composition must complete {expected_sources}; got {dict(source_counts)}")
    fairness_entries = []
    fairness_receipts = []
    fairness_schema = json.loads((ROOT / "spec/fairness-receipt.schema.json").read_text(encoding="utf-8"))
    receipt_keys = set(fairness_schema["properties"])
    ordered_public_commitment = hashlib.sha256(canonical([
        {"id": entry["id"], "content_sha256": entry["content_sha256"]}
        for entry in sorted(public_entries, key=lambda item: item["id"])
    ])).hexdigest()
    policy_sha256 = digest(ROOT / "spec/plan-quality-policy.json")
    detail_keys = {
        "schema_version", "reviewer_id", "reviewer_class", "case_author_independent",
        "candidate_implementation_independent", "fairness_policy_sha256",
        "ordered_case_commitment_set_sha256", "cases", "aggregate_verdict",
    }
    expected_public = {entry["id"]: entry["content_sha256"] for entry in public_entries}
    private_detail_hashes = {}
    for detail_path in (PRIVATE_ROOT / "reviews/public").glob("reviewer-*.json"):
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        rows = detail.get("cases", [])
        if set(detail) != detail_keys or detail.get("schema_version") != "private-fairness-detail-v1":
            raise ValueError("invalid private public-fairness detail envelope")
        if len(rows) != 24 or {row.get("id") for row in rows} != set(expected_public):
            raise ValueError("public fairness detail case-set mismatch")
        if any(
            set(row) != {"id", "content_sha256", "sufficiently_specified", "strategy_flexible", "distinguishing_reason", "verdict"}
            or row["content_sha256"] != expected_public[row["id"]]
            or row["verdict"] != "pass"
            or row["sufficiently_specified"] is not True
            or len(row["distinguishing_reason"]) < 10
            for row in rows
        ):
            raise ValueError("public fairness detail did not pass exact committed cases")
        if detail.get("fairness_policy_sha256") != policy_sha256 or detail.get("ordered_case_commitment_set_sha256") != ordered_public_commitment:
            raise ValueError("public fairness detail authority mismatch")
        if detail.get("aggregate_verdict") != "pass" or not detail.get("case_author_independent") or not detail.get("candidate_implementation_independent"):
            raise ValueError("public fairness detail did not pass independence gate")
        private_detail_hashes[digest(detail_path)] = detail["reviewer_id"]
    for path in sorted((ROOT / "evals/fairness/public").glob("*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if set(receipt) != receipt_keys or receipt.get("schema_version") != "fairness-receipt-v1":
            raise ValueError("public fairness receipt schema mismatch")
        if receipt.get("ordered_case_commitment_set_sha256") != ordered_public_commitment:
            raise ValueError("public fairness receipt case-set mismatch")
        if receipt.get("fairness_policy_sha256") != policy_sha256 or receipt.get("cases_reviewed") != 24:
            raise ValueError("public fairness receipt policy/count mismatch")
        detail_reviewer = private_detail_hashes.get(receipt.get("detailed_receipt_sha256"))
        if detail_reviewer is None or detail_reviewer != receipt.get("reviewer_id"):
            raise ValueError("public fairness detailed receipt/reviewer commitment unavailable")
        if receipt.get("aggregate_verdict") != "pass" or not receipt.get("case_author_independent") or not receipt.get("candidate_implementation_independent"):
            raise ValueError("public fairness receipt did not pass independence gate")
        fairness_receipts.append(receipt)
        fairness_entries.append({
            "path": path.relative_to(ROOT).as_posix(),
            "content_sha256": digest(path),
        })
    if len(fairness_entries) != 2 or len({receipt["reviewer_id"] for receipt in fairness_receipts}) != 2:
        raise ValueError("two independently authored public fairness receipts are required")
    commitments = private["commitments"]
    value = {
        "schema_version": "holdout-manifest-v1",
        "corpus_version": "corpus-v0",
        "frozen_before_candidate_implementation": True,
        "counts": {"development": 24, "calibration": 12, "sealed": 48, "total": 84},
        "strata": [
            "brownfield_integration",
            "recurring_bug",
            "architecture_migration",
            "production_safety",
            "cross_platform_release",
            "agent_governance",
        ],
        "per_stratum": {"development": 4, "calibration": 2, "sealed": 8, "total": 14},
        "source_composition": expected_sources,
        "metamorphic": {
            "minimum": 20,
            "decision_equivalence_frozen": True,
            "anti_verbosity_controls": ["long_rule_stuffed_wrong", "concise_missing_rollback", "plausible_hallucinated_command"],
        },
        "public_cases": public_entries,
        "public_fairness_receipts": fairness_entries,
        "non_public_cases": sorted(non_public, key=lambda item: item["id"]),
        "private_bundle": {
            "controller": "external-private-store",
            "manifest_sha256": digest(private_manifest_path),
            "all_case_bytes_sha256": commitments["all_case_bytes_sha256"],
            "fairness_receipts_sha256": commitments["fairness_receipts_sha256"],
            "calibration_labels_sha256": commitments["calibration_labels_sha256"],
            "outcome_partitions_sha256": commitments["outcome_partitions_sha256"],
            "private_nonce_projection_sha256": commitments["private_nonce_projection_sha256"],
            "public_content_or_labels": False,
        },
        "policies": {
            "eval_case_schema": "spec/eval-case.schema.json",
            "fairness_receipt_schema": "spec/fairness-receipt.schema.json",
            "outcome_receipt_schema": "spec/outcome-receipt.schema.json",
            "quality_rubric": "spec/quality-rubric.json",
            "plan_quality_policy": "spec/plan-quality-policy.json",
            "promotion_policy": "spec/promotion-policy.json",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical(value)
    try:
        fd = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        if OUTPUT.read_bytes() != payload:
            raise ValueError("holdout manifest is already frozen with different authority")
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps({"ok": True, "output": OUTPUT.as_posix(), "public": 24, "non_public": 60}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
