#!/usr/bin/env python3
"""Build the public, deterministic development partition of corpus v0."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals/corpus/public"
SOURCE_ROOT = ROOT / "evals/corpus/sources"
CANONICAL_REMOTE = "https://github.com/evgyur/chip-supergoal.git"

STRATA = {
    "brownfield_integration": {
        "task": "Plan a backward-compatible webhook integration in an existing service without replacing its current transport layer.",
        "must": ["Preserve existing webhook behavior and public interfaces", "Bind every change to executable compatibility and failure-path checks"],
        "should": ["Prefer an adapter at the existing integration seam"],
        "non_goal": ["Do not redesign the entire service or transport stack"],
        "risk": "A locally clean integration can silently break retry or signature semantics.",
        "seam": "Choose the narrow adapter boundary and rollback switch.",
        "checks": ["Run the legacy integration suite unchanged", "Exercise signature, retry, and rollback fixtures"],
        "equivalence": ["thin_adapter", "feature_gated_extension"]
    },
    "recurring_bug": {
        "task": "Plan a root-cause repair for an intermittent duplicate event bug that survived an earlier symptom-only patch.",
        "must": ["Identify and falsify the causal concurrency hypothesis", "Add a regression test that fails on the unpatched race"],
        "should": ["Separate root-cause evidence from timing coincidence"],
        "non_goal": ["Do not suppress duplicates only at the presentation layer"],
        "risk": "A deterministic-looking test can miss the actual interleaving.",
        "seam": "Choose where ownership or idempotency becomes authoritative.",
        "checks": ["Reproduce the old interleaving under a bounded stress harness", "Verify exactly-once observable output across retries"],
        "equivalence": ["atomic_ownership", "idempotency_key"]
    },
    "architecture_migration": {
        "task": "Plan an incremental data-model migration while old and new readers must coexist and rollback remains possible.",
        "must": ["Define an ordered expand-migrate-contract sequence", "Prove rollback and mixed-version compatibility before destructive cleanup"],
        "should": ["Make the cutover authority explicit and observable"],
        "non_goal": ["Do not perform a one-shot replacement of production data"],
        "risk": "Dual writes can drift and make rollback lossy.",
        "seam": "Choose the authoritative read/write transition and reconciliation point.",
        "checks": ["Replay mixed-version reads and writes on a snapshot", "Verify rollback before contract-phase deletion"],
        "equivalence": ["dual_write_with_reconcile", "shadow_copy_with_cutover"]
    },
    "production_safety": {
        "task": "Plan a production authentication routing change without exposing secrets, bypassing approval, or losing a safe rollback path.",
        "must": ["Require explicit authority before any production mutation", "Keep credentials and private traces out of plans and evidence"],
        "should": ["Use a staged canary with a predeclared abort signal"],
        "non_goal": ["Do not rotate unrelated credentials or redesign authentication"],
        "risk": "A routing error can lock out users or leak authentication context.",
        "seam": "Choose the smallest approved canary and deterministic rollback trigger.",
        "checks": ["Prove default-deny behavior without real credentials", "Verify rollback on a synthetic canary failure"],
        "equivalence": ["weighted_route_canary", "allowlisted_tenant_canary"]
    },
    "cross_platform_release": {
        "task": "Plan a release that must preserve byte-stable packaging and pass both Linux and native Windows behavior gates.",
        "must": ["Run clean native checks on Linux and supported Windows Python versions", "Bind package identity and release artifacts to immutable hashes"],
        "should": ["Keep platform-specific behavior behind a tested adapter"],
        "non_goal": ["Do not claim Windows support from a Linux compatibility layer"],
        "risk": "Path, locking, and archive semantics can diverge by platform.",
        "seam": "Choose the platform-neutral contract and native evidence boundary.",
        "checks": ["Compare clean package fingerprints across repeated builds", "Run path, lock, and archive fixtures on native Windows"],
        "equivalence": ["native_matrix_gate", "signed_platform_receipts"]
    },
    "agent_governance": {
        "task": "Plan an agent workflow policy change while preserving one runtime authority and preventing unbounded self-repair loops.",
        "must": ["Keep one canonical state and policy authority", "Bound critique and repair with explicit no-progress and cost stops"],
        "should": ["Record derived reports without creating a second writable state"],
        "non_goal": ["Do not add a new orchestrator or hidden runtime loop"],
        "risk": "Competing state stores can authorize stale or repeated actions.",
        "seam": "Choose the canonical policy recomputation point and stop owner.",
        "checks": ["Reject forged derived lane state", "Stop after the frozen no-progress threshold"],
        "equivalence": ["single_controller_policy", "derived_report_recomputation"]
    }
}

TRANSFORMS = [
    ("direct", ["express the class objective directly"]),
    ("renamed_entities", ["rename entities and files"]),
    ("reordered_context", ["reorder non-authoritative context"]),
    ("irrelevant_distractor", ["add an irrelevant but plausible distractor", "express one constraint indirectly"])
]


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def atomic_bytes(path: Path, payload: bytes) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def build() -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    built = []
    for stratum, scenario in STRATA.items():
        source_path = SOURCE_ROOT / f"{stratum}.txt"
        source_relative = source_path.relative_to(ROOT).as_posix()
        snapshot_content = source_path.read_text(encoding="utf-8").rstrip("\n")
        source_commit = subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", source_relative], cwd=ROOT, text=True
        ).strip()
        committed_content = subprocess.check_output(
            ["git", "show", f"{source_commit}:{source_relative}"], cwd=ROOT, text=True
        ).rstrip("\n")
        if not source_commit or committed_content != snapshot_content:
            raise ValueError(f"source fixture is not bound to immutable commit: {source_relative}")
        source_locator = f"git+{CANONICAL_REMOTE}@{source_commit}:{source_relative}"
        for variant_index, (variant_name, transforms) in enumerate(TRANSFORMS, start=1):
            case_id = f"DEV-{stratum.replace('_', '-')}-{variant_index:02d}"
            task = scenario["task"]
            context = [
                {"kind": "request", "content": task, "authority": "authoritative"},
                {"kind": "repository_fact", "content": snapshot_content, "authority": "authoritative"},
                {"kind": "constraint", "content": scenario["non_goal"][0], "authority": "authoritative"}
            ]
            if variant_name == "renamed_entities":
                task = task.replace("existing", "brownfield").replace("Plan", "Design a plan for")
            elif variant_name == "reordered_context":
                context = [context[2], context[0], context[1]]
            elif variant_name == "irrelevant_distractor":
                context.append({"kind": "distractor", "content": "A newer example uses a visually different naming convention but is not authoritative.", "authority": "non_authoritative"})
            case = {
                "schema_version": "eval-case-v2",
                "id": case_id,
                "split": "development",
                "stratum": stratum,
                "difficulty": "adversarial" if variant_name == "irrelevant_distractor" else "standard",
                "source_class": "public_repo",
                "privacy_class": "public_repository",
                "planner_input": {
                    "task": task,
                    "context_bundle": context,
                    "source_snapshots": [{"locator": source_locator, "content": snapshot_content, "sha256": hashlib.sha256(snapshot_content.encode("utf-8")).hexdigest(), "immutable": True}],
                    "clarification_oracle": {"required": False, "question": None, "allowed_answer_hash": None},
                    "budget": {"planner_tokens": 8000, "time_seconds": 900, "tool_calls": 20}
                },
                "controller_truth": {
                    "truth_set": {"must": scenario["must"], "should": scenario["should"], "non_goals": scenario["non_goal"]},
                    "acceptable_assumptions": ["Only the committed public repository fixture is authoritative."],
                    "decision_seams": [scenario["seam"]],
                    "risks": [scenario["risk"]],
                    "forbidden_actions": [scenario["non_goal"][0], "Do not invent unavailable private context or credentials."],
                    "deterministic_checks": {"checks": scenario["checks"], "strategy_flexible": True, "valid_strategy_ids": scenario["equivalence"]},
                    "rubric_anchors": {
                        "intent_fidelity": "Preserves the authoritative task and non-goal.",
                        "evidence_grounding": "Separates snapshot facts from assumptions.",
                        "executability": "Orders checks before irreversible action.",
                        "risk_and_rollback": "Names the causal risk and a verified rollback."
                    },
                    "metamorphic": {"variant_of": f"GROUP-{stratum}", "transforms": transforms, "acceptable_decision_equivalence_set": scenario["equivalence"]}
                }
            }
            path = OUT / f"{case_id}.json"
            payload = canonical(case)
            atomic_bytes(path, payload)
            built.append({"id": case_id, "path": path.relative_to(ROOT).as_posix(), "content_sha256": hashlib.sha256(payload).hexdigest(), "stratum": stratum})
    return built


if __name__ == "__main__":
    cases = build()
    print(json.dumps({"ok": True, "development_cases": len(cases), "output": OUT.as_posix()}, sort_keys=True))
