from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any


@dataclass(frozen=True)
class QualityFinding:
    code: str
    message: str
    pointer: str
    blocking: bool = True


def _finding(code: str, message: str, pointer: str) -> QualityFinding:
    return QualityFinding(code=code, message=message, pointer=pointer)


def quality_status(contract: dict[str, Any]) -> str:
    compatibility = contract.get("compatibility", {})
    if not isinstance(compatibility, dict) or "quality_gate_v1" not in compatibility:
        return "not_applicable"
    gate = compatibility["quality_gate_v1"]
    if not isinstance(gate, dict):
        return "red"
    attestation = gate.get("attestation")
    if not isinstance(attestation, dict):
        return "required"
    status = attestation.get("status")
    return status if status in {"required", "green", "red"} else "red"


def plan_subject_projection(contract: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(contract)
    try:
        gate = projected["compatibility"]["quality_gate_v1"]
    except (KeyError, TypeError) as exc:
        raise ValueError("quality_gate_v1 attestation is missing") from exc
    if not isinstance(gate, dict) or "attestation" not in gate:
        raise ValueError("quality_gate_v1 attestation is missing")
    del gate["attestation"]
    return projected


def _closed_object(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, dict) and not (set(value) - allowed)


def _recomputed_lane(contract: dict[str, Any]) -> tuple[str, str, bool, str]:
    gate = contract.get("compatibility", {}).get("quality_gate_v1", {}) if isinstance(contract.get("compatibility"), dict) else {}
    subject = gate.get("subject", {}) if isinstance(gate, dict) else {}
    failure_modes = subject.get("failure_modes", []) if isinstance(subject, dict) else []
    high_risk = any(
        isinstance(item, dict) and item.get("severity") in {"P0", "P1"}
        for item in [*contract.get("risks", []), *failure_modes]
    )
    risky_mutations = {
        "production_mutation", "destructive", "public_send", "money",
        "dns", "secrets", "grants", "private_data",
    }
    has_risky_command = any(
        isinstance(command, dict) and command.get("mutation_class") in risky_mutations
        for phase in contract.get("phases", []) if isinstance(phase, dict)
        for command in phase.get("commands", []) if isinstance(phase.get("commands", []), list)
    )
    if high_risk:
        return "b_plus_c", "QG-LANE-HIGH-RISK", True, "QG-JUDGE-HIGH-RISK"
    if has_risky_command:
        return "b_plus_c", "QG-LANE-RISKY-MUTATION", False, "QG-JUDGE-NOT-HIGH-RISK"
    return "b_only", "QG-LANE-STANDARD", False, "QG-JUDGE-NOT-REQUIRED"


def lint_quality_gate(
    contract: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    rubric: dict[str, Any] | None = None,
    _verify_report_hash: bool = True,
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    compatibility = contract.get("compatibility", {})
    gate = compatibility.get("quality_gate_v1") if isinstance(compatibility, dict) else None
    if gate is None:
        return findings
    if not _closed_object(gate, {"subject", "attestation"}) or set(gate) != {"subject", "attestation"}:
        return [_finding("QG-SCHEMA", "quality_gate_v1 must contain exactly subject and attestation", "/compatibility/quality_gate_v1")]

    subject = gate["subject"]
    subject_keys = {
        "intent", "requirements", "constraints", "source_set", "assumptions", "options",
        "traceability", "failure_modes", "permissions", "overengineering", "budgets",
    }
    if not _closed_object(subject, subject_keys) or set(subject) != subject_keys:
        return [_finding("QG-SCHEMA", "quality subject has missing or unknown fields", "/compatibility/quality_gate_v1/subject")]

    attestation = gate["attestation"]
    attestation_keys = {
        "quality_contract_version", "quality_policy_version", "rubric_version", "status",
        "semantic_review_lane", "semantic_review_lane_reason", "plan_subject_sha256",
        "report_path", "report_sha256", "semantic_judge_required",
        "semantic_judge_status", "semantic_judge_reason",
    }
    if not _closed_object(attestation, attestation_keys) or set(attestation) != attestation_keys:
        findings.append(_finding("QG-SCHEMA", "quality attestation has missing or unknown fields", "/compatibility/quality_gate_v1/attestation"))
        if not isinstance(attestation, dict):
            return findings

    if policy is not None:
        expected_policy = policy.get("schema_version")
        if attestation.get("quality_policy_version") != expected_policy:
            findings.append(_finding("QG-POLICY-VERSION", "attestation quality policy version is stale or forged", "/compatibility/quality_gate_v1/attestation/quality_policy_version"))
    if rubric is not None:
        expected_rubric = rubric.get("schema_version")
        if attestation.get("rubric_version") != expected_rubric:
            findings.append(_finding("QG-RUBRIC-VERSION", "attestation rubric version is stale or forged", "/compatibility/quality_gate_v1/attestation/rubric_version"))
    expected_lane, lane_reason, judge_required, judge_reason = _recomputed_lane(contract)
    if attestation.get("semantic_review_lane") != expected_lane or attestation.get("semantic_review_lane_reason") != lane_reason:
        findings.append(_finding("QG-LANE-MISMATCH", "declared semantic review lane does not match normalized risk and action inputs", "/compatibility/quality_gate_v1/attestation/semantic_review_lane"))
    expected_judge_status = "passed" if judge_required else "not_required"
    if (
        attestation.get("semantic_judge_required") is not judge_required
        or attestation.get("semantic_judge_reason") != judge_reason
        or attestation.get("semantic_judge_status") != expected_judge_status
    ):
        findings.append(_finding("QG-JUDGE-MISMATCH", "declared semantic judge requirement does not match the recomputed lane policy", "/compatibility/quality_gate_v1/attestation/semantic_judge_required"))

    list_fields = ("requirements", "assumptions", "options", "traceability", "failure_modes", "overengineering")
    if any(not isinstance(subject.get(name), list) for name in list_fields):
        findings.append(_finding("QG-SCHEMA", "quality subject record collections must be arrays", "/compatibility/quality_gate_v1/subject"))
        return findings

    traces = [item for item in subject["traceability"] if isinstance(item, dict)]
    for requirement in subject["requirements"]:
        if not isinstance(requirement, dict):
            findings.append(_finding("QG-SCHEMA", "requirement must be an object", "/compatibility/quality_gate_v1/subject/requirements"))
            continue
        if requirement.get("priority") != "must" or requirement.get("non_goal") is True:
            continue
        criterion_ids = requirement.get("criterion_ids")
        bound = {
            item.get("criterion_id")
            for item in traces
            if item.get("requirement_id") == requirement.get("id")
            and item.get("verifier_command_id")
        }
        if not isinstance(criterion_ids, list) or not criterion_ids or not set(criterion_ids).issubset(bound):
            findings.append(_finding("QG-MISSING-TRACE", "must requirement lacks a blocking criterion and verifier trace", "/compatibility/quality_gate_v1/subject/requirements"))

    target_ids = {
        item.get("id")
        for collection in (subject["requirements"], contract.get("phases", []))
        for item in collection
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    valid_source_ids: set[str] = set()
    for source in subject["source_set"]:
        if not isinstance(source, dict):
            continue
        used_by = source.get("used_by")
        valid = (
            isinstance(source.get("id"), str)
            and isinstance(source.get("locator"), str) and bool(source["locator"].strip())
            and isinstance(source.get("freshness"), str) and bool(source["freshness"].strip())
            and isinstance(source.get("sha256"), str) and bool(re.fullmatch(r"[0-9a-f]{64}", source["sha256"]))
            and isinstance(used_by, list) and bool(used_by)
            and all(isinstance(item, str) and item in target_ids for item in used_by)
        )
        if valid:
            valid_source_ids.add(source["id"])
    for assumption in subject["assumptions"]:
        if not isinstance(assumption, dict):
            findings.append(_finding("QG-SCHEMA", "assumption must be an object", "/compatibility/quality_gate_v1/subject/assumptions"))
            continue
        if assumption.get("critical") is True:
            source_id = assumption.get("evidence_source_id")
            if source_id is not None and source_id not in valid_source_ids:
                findings.append(_finding("QG-UNBOUND-SOURCE", "assumption evidence source is missing, stale, unhashed, or linked to no valid target", "/compatibility/quality_gate_v1/subject/assumptions"))
            if source_id not in valid_source_ids and not assumption.get("falsifier_command_id"):
                findings.append(_finding("QG-UNBOUND-ASSUMPTION", "critical assumption lacks direct evidence or a scheduled falsifier", "/compatibility/quality_gate_v1/subject/assumptions"))

    intent = subject.get("intent")
    architecture_affecting = isinstance(intent, dict) and intent.get("architecture_affecting") is True
    options = [item for item in subject["options"] if isinstance(item, dict)]
    if architecture_affecting and len(options) < 2:
        findings.append(_finding("QG-NO-ALTERNATIVE", "architecture-affecting plan lacks a credible alternative", "/compatibility/quality_gate_v1/subject/options"))
    if options and sum(item.get("selected") is True for item in options) != 1:
        findings.append(_finding("QG-SCHEMA", "quality subject must select exactly one option", "/compatibility/quality_gate_v1/subject/options"))

    for failure in subject["failure_modes"]:
        if not isinstance(failure, dict):
            findings.append(_finding("QG-SCHEMA", "failure mode must be an object", "/compatibility/quality_gate_v1/subject/failure_modes"))
            continue
        if failure.get("severity") in {"P0", "P1"} and (
            not all(
            isinstance(failure.get(key), str) and failure[key].strip()
            for key in ("mitigation", "rollback", "verifier_command_id")
            ) or len(failure.get("rollback", "").strip()) < 8
        ):
            findings.append(_finding("QG-RISK-NO-ROLLBACK", "P0/P1 failure mode lacks mitigation, rollback, or verifier", "/compatibility/quality_gate_v1/subject/failure_modes"))

    for layer in subject["overengineering"]:
        if not isinstance(layer, dict) or not all(
            isinstance(layer.get(key), str) and layer[key].strip()
            for key in ("necessity", "simpler_alternative", "removal_condition")
        ):
            findings.append(_finding("QG-LAYER-NO-REMOVAL", "new layer lacks necessity, simpler alternative, or removal condition", "/compatibility/quality_gate_v1/subject/overengineering"))

    declared_risk_tags = {
        item.get("tag") for item in contract.get("risks", []) if isinstance(item, dict)
    }
    typed_fields = {
        "cwd", "mutation_class", "availability_dependencies", "expected_output",
        "risk_tags", "risk_waiver",
    }
    risky_mutations = {
        "production_mutation", "destructive", "public_send", "money",
        "dns", "secrets", "grants", "private_data",
    }
    for phase_index, phase in enumerate(contract.get("phases", [])):
        if not isinstance(phase, dict):
            continue
        for command_index, command_spec in enumerate(phase.get("commands", [])):
            if not isinstance(command_spec, dict):
                continue
            pointer = f"/phases/{phase_index}/commands/{command_index}"
            missing = typed_fields - set(command_spec)
            bindings_valid = (
                isinstance(command_spec.get("cwd"), str) and bool(command_spec.get("cwd", "").strip())
                and isinstance(command_spec.get("mutation_class"), str) and bool(command_spec.get("mutation_class", "").strip())
                and isinstance(command_spec.get("availability_dependencies"), list) and bool(command_spec.get("availability_dependencies"))
                and isinstance(command_spec.get("expected_output"), dict)
                and set(command_spec.get("expected_output", {})) == {"kind", "value"}
                and isinstance(command_spec.get("risk_tags"), list)
            )
            if missing or not bindings_valid:
                findings.append(_finding("QG-COMMAND-TYPE", "quality command lacks cwd, mutation, availability, output, or risk bindings", pointer))
            command_text = str(command_spec.get("command", "")).strip()
            if re.fullmatch(r"(?:echo\s+(?:ok|pass)|python3?\s+-c\s+['\"]pass['\"])", command_text, re.IGNORECASE):
                findings.append(_finding("QG-FAKE-COMMAND", "command is a non-evidentiary placeholder", pointer + "/command"))
            if command_spec.get("mutation_class") in risky_mutations:
                tags = set(command_spec.get("risk_tags", [])) if isinstance(command_spec.get("risk_tags"), list) else set()
                waiver = command_spec.get("risk_waiver")
                waiver_valid = (
                    isinstance(waiver, dict)
                    and set(waiver) == {"reason", "evidence_source_id"}
                    and isinstance(waiver.get("reason"), str)
                    and len(waiver["reason"].strip()) >= 10
                    and waiver.get("evidence_source_id") in valid_source_ids
                )
                if not (tags & declared_risk_tags) and not waiver_valid:
                    findings.append(_finding("QG-UNDECLARED-RISK", "risky command mutation has no matching declared risk or evidence-backed waiver", pointer + "/risk_tags"))

    subject_bytes = _subject_bytes(contract)
    if attestation.get("plan_subject_sha256") != hashlib.sha256(subject_bytes).hexdigest():
        findings.append(_finding("QG-SUBJECT-HASH", "attestation subject hash does not bind the normalized plan subject", "/compatibility/quality_gate_v1/attestation/plan_subject_sha256"))
    findings = sorted(findings, key=lambda item: (item.code, item.pointer, item.message))
    if _verify_report_hash and policy is not None and rubric is not None:
        expected_report_hash = hashlib.sha256(_render_quality_report(contract, policy, rubric, findings)).hexdigest()
        if attestation.get("report_sha256") != expected_report_hash:
            findings.append(_finding("QG-REPORT-HASH", "attestation report hash does not bind the deterministic quality report", "/compatibility/quality_gate_v1/attestation/report_sha256"))
            findings.sort(key=lambda item: (item.code, item.pointer, item.message))
    return findings


def _subject_bytes(contract: dict[str, Any]) -> bytes:
    return json.dumps(
        plan_subject_projection(contract), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _render_quality_report(
    contract: dict[str, Any],
    policy: dict[str, Any],
    rubric: dict[str, Any],
    findings: list[QualityFinding],
) -> bytes:
    lane, lane_reason, judge_required, judge_reason = _recomputed_lane(contract)
    report = {
        "schema_version": "plan-quality-lint-v1",
        "quality_policy_version": policy.get("schema_version"),
        "rubric_version": rubric.get("schema_version"),
        "plan_subject_sha256": hashlib.sha256(_subject_bytes(contract)).hexdigest(),
        "status": "red" if any(item.blocking for item in findings) else "green",
        "semantic_review_lane": lane,
        "semantic_review_lane_reason": lane_reason,
        "semantic_judge_required": judge_required,
        "semantic_judge_reason": judge_reason,
        "findings": [asdict(item) for item in findings],
    }
    return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def quality_report_bytes(
    contract: dict[str, Any],
    policy: dict[str, Any],
    rubric: dict[str, Any],
) -> bytes:
    findings = lint_quality_gate(contract, policy=policy, rubric=rubric)
    return _render_quality_report(contract, policy, rubric, findings)


def seal_quality_attestation(
    contract: dict[str, Any], policy: dict[str, Any], rubric: dict[str, Any]
) -> dict[str, Any]:
    sealed = deepcopy(contract)
    attestation = sealed["compatibility"]["quality_gate_v1"]["attestation"]
    attestation["plan_subject_sha256"] = hashlib.sha256(_subject_bytes(sealed)).hexdigest()
    core_findings = lint_quality_gate(
        sealed, policy=policy, rubric=rubric, _verify_report_hash=False
    )
    attestation["report_sha256"] = hashlib.sha256(
        _render_quality_report(sealed, policy, rubric, core_findings)
    ).hexdigest()
    return sealed


def lint_false_green_fragment(fragment: dict[str, Any]) -> list[QualityFinding]:
    findings: list[QualityFinding] = []

    acceptance = fragment.get("acceptance")
    commands = fragment.get("commands")
    if isinstance(acceptance, list) and isinstance(commands, list):
        obligation_count = sum(
            len(re.split(r",\s*|\s+and\s+", item, flags=re.IGNORECASE))
            for item in acceptance
            if isinstance(item, str)
        )
        if obligation_count > len(commands):
            findings.append(_finding(
                "QG-MISSING-TRACE",
                "acceptance obligations are not individually bound to blocking verifiers",
                "/acceptance",
            ))

    if "fact" in fragment:
        locator = fragment.get("source_locator")
        freshness = fragment.get("freshness")
        mutable_locators = {None, "", "current chat context", "current context"}
        if locator in mutable_locators or freshness in {None, "", "unspecified"}:
            findings.append(_finding(
                "QG-UNBOUND-SOURCE",
                "decision-critical fact lacks an immutable locator and freshness binding",
                "/source_locator",
            ))

    phase_match = re.fullmatch(r"P(\d{2})", str(fragment.get("phase", "")))
    if phase_match and isinstance(fragment.get("command"), str):
        current = int(phase_match.group(1))
        referenced = [int(value) for value in re.findall(r"(?:^|[/_-])P(\d{2})(?:[/_.-]|$)", fragment["command"])]
        if any(value > current for value in referenced):
            findings.append(_finding(
                "QG-FUTURE-DEPENDENCY",
                "command consumes an artifact that cannot exist in the declared phase order",
                "/command",
            ))

    command = str(fragment.get("command", ""))
    if re.search(r"(?:--target\s+production|\bprod(?:uction)?\b)", command, re.IGNORECASE):
        scope = str(fragment.get("approval_scope", ""))
        if scope not in {"production-mutation", "live-production-mutation"}:
            findings.append(_finding(
                "QG-APPROVAL-SCOPE",
                "declared approval does not authorize the live production mutation",
                "/approval_scope",
            ))

    runtime_state = fragment.get("runtime_state")
    projection_state = fragment.get("projection_state")
    if projection_state in {"DONE", "COMPLETE"} and runtime_state not in {"DONE", "COMPLETE"}:
        findings.append(_finding(
            "QG-RUNTIME-AUTHORITY",
            "derived projection or markers cannot override authoritative runtime state",
            "/runtime_state",
        ))

    return findings
