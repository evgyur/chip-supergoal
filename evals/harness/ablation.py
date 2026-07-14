"""Fail-closed four-way ablation and no-candidate selection."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_VARIANTS = ["baseline", "prompt-only", "b-only", "b-plus-c"]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def compare_manifest(manifest: dict[str, Any], variants: list[str]) -> dict[str, Any]:
    if variants != EXPECTED_VARIANTS or manifest.get("variants") != EXPECTED_VARIANTS:
        raise ValueError("the frozen four variants are mandatory and ordered")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 36:
        raise ValueError("development/calibration manifest must contain 36 tasks")
    if manifest.get("sealed_tasks_included") is not False or manifest.get("private_content_included") is not False:
        raise ValueError("selection manifest crosses the holdout boundary")
    rows = []
    strata = Counter()
    for task in tasks:
        strata[task["stratum"]] += 1
        rows.append({
            "task_id": task["id"], "split": task["split"], "stratum": task["stratum"],
            "content_sha256": task["content_sha256"],
            "variants": {name: {
                "status": "not_observed", "hard_failures": None, "score": None,
                "pairwise_votes": None, "repeat_sd": None, "tokens": None,
                "latency_ms": None, "rendered_length": None, "execution_outcome": None,
            } for name in variants},
        })
    per_stratum = {name: {
        "tasks": count, "attributable": False, "score_delta": None,
        "hard_failure_delta": None, "execution_delta": None, "cost_delta": None,
    } for name, count in sorted(strata.items())}
    report = {
        "schema_version": "ablation-comparison-v1",
        "status": "complete_no_authoritative_observations",
        "promotion_capable": False,
        "variants": variants,
        "task_level": rows,
        "per_stratum": per_stratum,
        "aggregate": {
            name: {"observed_tasks": 0, "p0_p1": None, "quality_delta": None, "execution_delta": None, "cost_delta": None}
            for name in variants
        },
        "reasons": [
            "planner_variant_outputs_unavailable",
            "judge_calibration_non_authoritative",
            "sandbox_capabilities_import_only",
            "incremental_gain_not_attributable",
        ],
        "sealed_holdout_accessed": False,
        "private_content_exported": False,
    }
    report["report_sha256"] = _hash(report)
    return report


def select_candidate(report: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if report.get("promotion_capable") is not False:
        raise ValueError("this selector only handles fail-closed no-candidate evidence")
    if policy.get("frozen_before_candidate_scoring") is not True:
        raise ValueError("promotion policy is not frozen")
    decision = {
        "schema_version": "candidate-selection-v1",
        "decision": "no_candidate",
        "status": "no_go",
        "selected_variant": None,
        "retained_runtime_layers": [],
        "removed_from_runtime_candidate": ["prompt-only", "b-only", "b-plus-c", "critic-repair"],
        "report_sha256": report["report_sha256"],
        "policy_sha256": _hash(policy),
        "zero_p0_p1_proven": False,
        "attributable_incremental_gain": False,
        "sealed_holdout_accessed": False,
        "reason": "No variant has authoritative task-level observations, zero-P0/P1 proof, and attributable gain; forcing a candidate is forbidden.",
    }
    decision["decision_sha256"] = _hash(decision)
    adr = f"""# ADR-005 — quality candidate selection\n\n## Decision\n\n`no_candidate` / `no-go`. No runtime quality candidate is promoted.\n\n## Evidence\n\n- Ablation report SHA-256: `{decision['report_sha256']}`\n- Promotion policy SHA-256: `{decision['policy_sha256']}`\n- Decision SHA-256: `{decision['decision_sha256']}`\n- Sealed holdout accessed: `false`\n\n## Rationale\n\nNo variant has authoritative task-level observations, zero-P0/P1 proof, and attributable incremental gain. The P06 sandbox lanes remain `import_only` and judge calibration remains `non_authoritative`. Aggregate appearance cannot rescue missing authority.\n\n## Consequence\n\nThe critic/repair layer is not retained in the runtime candidate. Later rollout phases must produce no-op/no-go receipts and cannot claim promotion or live exposure.\n"""
    return decision, adr


def verify_holdout_secrecy(manifest: dict[str, Any]) -> dict[str, Any]:
    private_bundle = manifest.get("private_bundle", {})
    public_cases = manifest.get("public_cases", [])
    non_public = manifest.get("non_public_cases", [])
    checks = {
        "public_bundle_declares_no_private_content_or_labels": private_bundle.get("public_content_or_labels") is False,
        "public_cases_development_only": all(item.get("split") == "development" and str(item.get("id", "")).startswith("DEV-") for item in public_cases),
        "non_public_cases_commitment_only": all(set(item) == {"id", "content_sha256"} for item in non_public),
        "sealed_ids_have_no_paths": all("path" not in item for item in non_public if str(item.get("id", "")).startswith("SEA-")),
    }
    return {"schema_version": "holdout-secrecy-check-v1", "status": "pass" if all(checks.values()) else "fail", "checks": checks}
