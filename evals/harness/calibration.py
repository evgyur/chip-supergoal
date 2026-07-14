"""Aggregate-only calibration verifier for judges and outcome adjudicators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

JUDGE_THRESHOLDS = {
    "agreement_with_expert": (">=", 0.8),
    "position_swap_consistency": (">=", 0.9),
    "kappa": (">=", 0.67),
    "icc": (">=", 0.75),
    "condition_guess_balanced_accuracy": ("<=", 0.6),
}
OUTCOME_THRESHOLDS = {
    "planner_miss_precision": 0.8,
    "planner_miss_recall": 0.8,
    "macro_f1": 0.75,
    "label_kappa": 0.67,
}


def _passes_judge(row: dict[str, Any]) -> bool:
    for key, (operator, threshold) in JUDGE_THRESHOLDS.items():
        value = row.get(key)
        if not isinstance(value, (int, float)):
            return False
        if operator == ">=" and value < threshold:
            return False
        if operator == "<=" and value > threshold:
            return False
    return True


def _passes_outcome(row: dict[str, Any]) -> bool:
    return all(isinstance(row.get(key), (int, float)) and row[key] >= threshold for key, threshold in OUTCOME_THRESHOLDS.items())


def calibrate(
    private_root: Path,
    *,
    cases: int,
    judges: int,
    outcome_adjudicators: int,
    observations: Path | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    report_path = private_root / "validation_report.json"
    if not report_path.is_file():
        reasons.append("private_calibration_bundle_unavailable")
        return {
            "schema_version": "judge-calibration-v1",
            "status": "non_authoritative",
            "authoritative": False,
            "cases_requested": cases,
            "judge_families_required": judges,
            "outcome_adjudicators_required": outcome_adjudicators,
            "reasons": reasons,
            "private_content_exported": False,
        }
    private_report = json.loads(report_path.read_text(encoding="utf-8"))
    counts, coverage = private_report.get("counts", {}), private_report.get("calibration_coverage", {})
    commitments = private_report.get("commitments", {})
    if private_report.get("status") != "pass" or counts.get("calibration") != cases:
        reasons.append("private_calibration_bundle_invalid")
    if coverage.get("expert_episodes", 0) < 12 or coverage.get("multi_manifest_episodes", 0) < 6 or coverage.get("positive_planner_miss_manifestations", 0) < 30:
        reasons.append("expert_coverage_below_frozen_minimum")
    judge_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    if observations is None or not observations.is_file():
        reasons.append("independent_observations_unavailable")
    else:
        imported = json.loads(observations.read_text(encoding="utf-8"))
        if imported.get("schema_version") != "calibration-observations-v1":
            reasons.append("observation_schema_invalid")
        if imported.get("calibration_labels_sha256") != commitments.get("calibration_labels_sha256") or imported.get("outcome_partitions_sha256") != commitments.get("outcome_partitions_sha256"):
            reasons.append("observation_commitment_mismatch")
        judge_rows = imported.get("judge_families", [])
        outcome_rows = imported.get("outcome_adjudicators", [])
    if len({row.get("id") for row in judge_rows}) < judges:
        reasons.append("independent_judge_families_missing")
    elif not all(_passes_judge(row) for row in judge_rows):
        reasons.append("judge_threshold_failure")
    if len({row.get("id") for row in outcome_rows}) < outcome_adjudicators:
        reasons.append("independent_outcome_adjudicators_missing")
    elif not all(_passes_outcome(row) for row in outcome_rows):
        reasons.append("outcome_threshold_failure")
    authoritative = not reasons
    return {
        "schema_version": "judge-calibration-v1",
        "status": "pass" if authoritative else "non_authoritative",
        "authoritative": authoritative,
        "cases_requested": cases,
        "judge_families_required": judges,
        "judge_families_observed": len({row.get("id") for row in judge_rows}),
        "outcome_adjudicators_required": outcome_adjudicators,
        "outcome_adjudicators_observed": len({row.get("id") for row in outcome_rows}),
        "coverage": {
            "expert_episodes": coverage.get("expert_episodes", 0),
            "multi_manifest_episodes": coverage.get("multi_manifest_episodes", 0),
            "positive_planner_miss_manifestations": coverage.get("positive_planner_miss_manifestations", 0),
        },
        "commitments": {
            "calibration_labels_sha256": commitments.get("calibration_labels_sha256"),
            "outcome_partitions_sha256": commitments.get("outcome_partitions_sha256"),
        },
        "reasons": sorted(set(reasons)),
        "private_content_exported": False,
    }
