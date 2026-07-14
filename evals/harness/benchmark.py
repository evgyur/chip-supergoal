"""Deterministic blind paired-comparison primitives."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan.get("text"), str) or not plan["text"].strip():
        raise ValueError("plan text is required")
    return {"text": "\n".join(line.rstrip() for line in plan["text"].strip().splitlines())}


def blind_pair(task_id: str, seed_id: int, left: dict[str, Any], right: dict[str, Any], policy_sha256: str) -> dict[str, Any]:
    """Remove condition identities and deterministically assign presentation slots."""
    if not task_id or not isinstance(seed_id, int):
        raise ValueError("task_id and integer seed_id are required")
    if len(policy_sha256) != 64:
        raise ValueError("policy_sha256 must be a 64-character commitment")
    left_payload, right_payload = _plan_payload(left), _plan_payload(right)
    selector = hashlib.sha256(canonical([task_id, seed_id, policy_sha256])).digest()[0] & 1
    ordered = (left_payload, right_payload) if selector == 0 else (right_payload, left_payload)
    assignment = {
        "A": hashlib.sha256(canonical(left_payload if selector == 0 else right_payload)).hexdigest(),
        "B": hashlib.sha256(canonical(right_payload if selector == 0 else left_payload)).hexdigest(),
    }
    return {
        "schema_version": "blind-pair-v1",
        "task_id": task_id,
        "seed_id": seed_id,
        "plans": {"A": ordered[0], "B": ordered[1]},
        "assignment_commitment_sha256": hashlib.sha256(canonical(assignment)).hexdigest(),
        "policy_sha256": policy_sha256,
    }


def aggregate_task_votes(votes: list[dict[str, str]]) -> dict[str, Any]:
    """Collapse judge/seed votes before aggregation; tasks are the only samples."""
    by_task: dict[str, Counter[str]] = defaultdict(Counter)
    for vote in votes:
        task_id, winner = vote.get("task_id"), vote.get("winner")
        if not task_id or winner not in {"baseline", "candidate", "tie", "invalid"}:
            raise ValueError("invalid vote")
        by_task[task_id][winner] += 1
    task_results: dict[str, str] = {}
    for task_id, counts in sorted(by_task.items()):
        valid = {key: value for key, value in counts.items() if key not in {"invalid", "tie"}}
        if not valid:
            task_results[task_id] = "invalid"
            continue
        top = max(valid.values())
        winners = sorted(key for key, value in valid.items() if value == top)
        task_results[task_id] = winners[0] if len(winners) == 1 else "tie"
    return {
        "schema_version": "task-aggregate-v1",
        "statistical_unit": "task",
        "independent_sample_size": len(task_results),
        "task_results": task_results,
        "counts": dict(sorted(Counter(task_results.values()).items())),
    }


def evaluate_bias_controls(observations: list[dict[str, str]]) -> dict[str, Any]:
    failures: set[str] = set()
    swaps: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in observations:
        control = row.get("control")
        if control == "position_swap":
            swaps[row.get("pair_id", "")].append(row)
        elif control == "verbosity_trap" and row.get("winner") != row.get("expected"):
            failures.add("verbosity_bias")
        else:
            if control not in {"position_swap", "verbosity_trap"}:
                failures.add("unknown_control")
    for pair_id, rows in swaps.items():
        if not pair_id or len(rows) != 2 or {row.get("order") for row in rows} != {"AB", "BA"}:
            failures.add("position_control_incomplete")
            continue
        if len({row.get("winner_content_sha256") for row in rows}) != 1:
            failures.add("position_bias")
    return {
        "schema_version": "judge-bias-controls-v1",
        "authoritative": not failures,
        "failures": sorted(failures),
        "observations": len(observations),
    }


def immutable_write(path: Path, value: Any) -> str:
    payload = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return hashlib.sha256(payload).hexdigest()
