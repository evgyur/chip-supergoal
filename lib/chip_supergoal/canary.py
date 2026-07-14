"""Bounded host-side critic/repair canary with sealed public ledgers."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

MAX_REPAIR_ROUNDS = 2
_BLOCKING = frozenset({"P0", "P1"})
_FINDING_KEYS = frozenset({"code", "severity", "message", "pointer", "evidence_pointer"})


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _findings(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("findings", [])
    if not isinstance(value, list):
        return []
    clean = []
    for item in value:
        if not isinstance(item, dict):
            continue
        projected = {key: copy.deepcopy(item[key]) for key in sorted(_FINDING_KEYS) if key in item}
        if isinstance(projected.get("code"), str) and isinstance(projected.get("severity"), str):
            clean.append(projected)
    return clean


def _pointers(value: Any, findings: list[dict[str, Any]]) -> list[str]:
    declared = value.get("evidence_pointers", []) if isinstance(value, dict) else []
    pointers = [item for item in declared if isinstance(item, str) and item.startswith("/")]
    for finding in findings:
        pointer = finding.get("evidence_pointer") or finding.get("pointer")
        if isinstance(pointer, str) and pointer.startswith("/"):
            pointers.append(pointer)
    return sorted(set(pointers))


def _blocking(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in findings if item.get("severity") in _BLOCKING]


def _signature(findings: list[dict[str, Any]]) -> str:
    values = sorted((str(item.get("code")), str(item.get("pointer") or item.get("evidence_pointer") or "")) for item in _blocking(findings))
    return _digest(values)


def _ledger_entry(
    ledger: list[dict[str, Any]], *, stage: str, round_number: int,
    before: dict[str, Any], after: dict[str, Any], payload: Any,
) -> None:
    findings = _findings(payload)
    entry = {
        "stage": stage,
        "round": round_number,
        "subject_before_sha256": _digest(before),
        "subject_after_sha256": _digest(after),
        "finding_codes": [item["code"] for item in findings],
        "evidence_pointers": _pointers(payload, findings),
        "prev_entry_sha256": ledger[-1]["entry_sha256"] if ledger else None,
    }
    entry["entry_sha256"] = _digest(entry)
    ledger.append(entry)


def run_quality_canary(
    subject: dict[str, Any], *, route: str,
    lint: Callable[[dict[str, Any]], Any],
    critic: Callable[[dict[str, Any]], Any] | None = None,
    repair: Callable[[dict[str, Any], list[dict[str, Any]]], Any] | None = None,
    judge: Callable[[dict[str, Any]], Any] | None = None,
    judge_required: bool = False,
    max_repair_rounds: int = MAX_REPAIR_ROUNDS,
) -> dict[str, Any]:
    if route not in {"b_only", "b_plus_c"}:
        raise ValueError("route must be b_only or b_plus_c")
    if type(max_repair_rounds) is not int or not 0 <= max_repair_rounds <= MAX_REPAIR_ROUNDS:
        raise ValueError("max_repair_rounds must be between zero and two")
    if route == "b_plus_c" and critic is None:
        raise ValueError("b_plus_c requires a critic")
    if judge_required and (route != "b_plus_c" or judge is None):
        raise ValueError("policy-required judge is unavailable")

    current = copy.deepcopy(subject)
    ledger: list[dict[str, Any]] = []
    calls = {"critic": 0, "judge": 0, "repair": 0, "lint": 0}
    calls["lint"] += 1
    lint_findings = _findings(lint(copy.deepcopy(current)))
    stop_reason = "complete"

    if route == "b_plus_c":
        assert critic is not None
        calls["critic"] += 1
        critic_payload = critic(copy.deepcopy(current))
        critic_findings = _findings(critic_payload)
        _ledger_entry(ledger, stage="critic", round_number=0, before=current, after=current, payload=critic_payload)
        pending = _blocking(lint_findings + critic_findings)
        rounds = 0
        while pending and rounds < max_repair_rounds:
            if repair is None:
                stop_reason = "repair_unavailable"
                break
            before = copy.deepcopy(current)
            repair_payload = repair(copy.deepcopy(current), copy.deepcopy(pending))
            calls["repair"] += 1
            rounds += 1
            candidate = repair_payload.get("subject") if isinstance(repair_payload, dict) else None
            if not isinstance(candidate, dict):
                stop_reason = "invalid_repair"
                break
            current = copy.deepcopy(candidate)
            _ledger_entry(ledger, stage="repair", round_number=rounds, before=before, after=current, payload=repair_payload)
            calls["lint"] += 1
            next_lint = _findings(lint(copy.deepcopy(current)))
            if _blocking(next_lint) and _signature(next_lint) == _signature(lint_findings):
                lint_findings = next_lint
                stop_reason = "no_progress"
                break
            lint_findings = next_lint
            pending = _blocking(lint_findings)
        if pending and rounds >= max_repair_rounds and stop_reason == "complete":
            stop_reason = "round_limit"

        judge_findings: list[dict[str, Any]] = []
        if judge_required:
            assert judge is not None
            calls["judge"] += 1
            judge_payload = judge(copy.deepcopy(current))
            judge_findings = _findings(judge_payload)
            _ledger_entry(ledger, stage="judge", round_number=rounds, before=current, after=current, payload=judge_payload)
            if isinstance(judge_payload, dict) and judge_payload.get("status") != "passed":
                judge_findings.append({"code": "QG-JUDGE-FAILED", "severity": "P1"})
        unresolved = _blocking(lint_findings + judge_findings)
    else:
        unresolved = _blocking(lint_findings)

    report = {
        "schema_version": "quality-canary-run-v1",
        "route": route,
        "status": "blocked" if unresolved else "green",
        "stop_reason": stop_reason,
        "repair_rounds": calls["repair"],
        "semantic_calls": calls,
        "re_lint_after_every_repair": calls["lint"] == calls["repair"] + 1,
        "unresolved_findings": unresolved,
        "mutation_ledger": ledger,
        "plan_subject_sha256": _digest(current),
        "dispatch_authorized": False,
        "dispatch_authority": "explicit_current_stage6_human_approval_only",
    }
    report["report_sha256"] = _digest(report)
    return report


def stage6_dispatch_authorized(report: dict[str, Any], approval: dict[str, Any] | None) -> bool:
    if report.get("status") != "green" or not isinstance(approval, dict):
        return False
    required = {
        "schema_version", "human_approved", "current", "plan_subject_sha256",
        "report_sha256", "approval_sha256",
    }
    if set(approval) != required:
        return False
    unsigned = {key: approval[key] for key in sorted(approval) if key != "approval_sha256"}
    return (
        approval.get("schema_version") == "stage6-approval-v1"
        and approval.get("human_approved") is True
        and approval.get("current") is True
        and approval.get("plan_subject_sha256") == report.get("plan_subject_sha256")
        and approval.get("report_sha256") == report.get("report_sha256")
        and approval.get("approval_sha256") == _digest(unsigned)
    )
