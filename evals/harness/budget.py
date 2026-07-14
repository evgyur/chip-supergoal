"""Deterministic prompt and repair-budget verifier."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any


def _git_blob(root: Path, revision: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=root,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"baseline blob unavailable: {path}")
    return result.stdout


def verify_canary_budget(root: Path, baseline_path: Path, *, max_prompt_growth: float, max_repair_rounds: int) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    selected_sha = baseline["foundation"]["selected_sha"]
    references = [item["path"] for item in baseline["prompt_reference_set"]]
    additions = ["references/planner-critic-repair-loop.md", "templates/PLAN_QUALITY.md"]
    baseline_bytes = sum(len(_git_blob(root, selected_sha, path)) for path in references)
    candidate_paths = references + additions
    candidate_bytes = sum(len((root / path).read_bytes()) for path in candidate_paths)
    growth = (candidate_bytes - baseline_bytes) / baseline_bytes if baseline_bytes else 1.0
    profile = json.loads((root / "profiles/quality-canary.json").read_text(encoding="utf-8"))
    planning = profile.get("quality", {}).get("planning_canary", {})
    checks = {
        "prompt_growth_within_limit": growth <= max_prompt_growth,
        "repair_round_limit_matches": planning.get("max_repair_rounds") == max_repair_rounds <= 2,
        "b_only_zero_semantic_calls": planning.get("b_only_semantic_calls") == 0,
        "no_progress_stop_enabled": planning.get("no_progress_stop") is True,
        "raw_chain_of_thought_disabled": planning.get("persist_raw_chain_of_thought") is False,
        "stage6_human_authority_preserved": planning.get("dispatch_authority") == "explicit_current_stage6_human_approval_only",
    }
    return {
        "schema_version": "critic-canary-budget-v1",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "prompt": {
            "baseline_bytes": baseline_bytes,
            "candidate_bytes": candidate_bytes,
            "baseline_token_estimate": math.ceil(baseline_bytes / 4),
            "candidate_token_estimate": math.ceil(candidate_bytes / 4),
            "growth_ratio": round(growth, 6),
            "max_growth_ratio": max_prompt_growth,
            "candidate_paths": candidate_paths,
        },
        "semantic_budget": {
            "b_only_max_calls": 0,
            "max_repair_rounds": max_repair_rounds,
            "no_progress_stop": True,
            "verifier_timeout_seconds": 900,
        },
    }
