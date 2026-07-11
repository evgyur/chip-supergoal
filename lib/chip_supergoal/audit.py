from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .delivery import (
    REQUIRED_REVIEW_FILES,
    ReceiptValidationError,
    delivery_receipt_required,
    read_receipt,
    validate_final_receipt,
    validate_review_receipt,
)
from .events import (
    JournalCorruptionError,
    parse_rfc3339_z_seconds,
    validate_event_journal,
)
from .evidence import (
    EVIDENCE_TYPES,
    EvidenceRecord,
    evidence_json_bytes,
    evidence_satisfies_verifier,
    read_evidence,
    validate_evidence_records,
    validate_record_against_contract,
)
from .model import Contract, canonical_json, contract_from_dict
from .policy import mandatory_evidence_requirements
from .portable import (
    package_lock,
    package_operation_lock,
    read_regular_file_no_follow,
    verify_sealed_artifact,
    write_bytes_atomic,
    write_utf8_lf,
)
from .state import State, StateStore, assert_runtime_mutable, state_sha256


BLOCKING_ISSUES = frozenset({"AUDIT_GAP", "AUDIT_BLOCKER", "AUDIT_CORRUPTION"})
DEFAULT_MAX_AGE_SECONDS = 86400
MAX_FUTURE_SKEW_SECONDS = 300
_SHA256 = re.compile(r"[a-f0-9]{64}")
_ISSUE_TYPES = frozenset(
    {"AUDIT_GAP", "AUDIT_BLOCKER", "AUDIT_CORRUPTION", "AUDIT_WARNING"}
)
_COVERAGE_FIELDS = frozenset(
    {
        "blocking_criteria_total",
        "blocking_criteria_with_passing_evidence",
        "deterministic_coverage",
        "unverified",
    }
)


@dataclass(frozen=True)
class AuditIssue:
    issue_type: str
    message: str
    phase_id: str | None = None
    criterion_id: str | None = None
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if self.issue_type not in _ISSUE_TYPES:
            raise ValueError("audit issue type is invalid")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("audit issue message is required")
        for name in ("phase_id", "criterion_id", "evidence_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"audit issue {name} is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in self.__dict__.items()
            if value is not None
        }


@dataclass(frozen=True)
class AuditReport:
    goal_id: str
    contract_sha256: str
    contract_revision: int
    state_revision: int
    state_sha256: str
    lifecycle: str
    audit_round: int
    audit_anchor: str
    event_tail_sha256: str
    evidence_sha256: str
    coverage: dict[str, int]
    issues: list[AuditIssue] = field(default_factory=list)
    delivery_status: str = "not_required"
    rpd_decision: str = "not_required"
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("final audit schema version is invalid")
        if not isinstance(self.goal_id, str) or not self.goal_id or any(
            marker in self.goal_id for marker in ("\r", "\n")
        ):
            raise ValueError("final audit goal id is invalid")
        for name in (
            "contract_sha256",
            "state_sha256",
            "event_tail_sha256",
            "evidence_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError(f"final audit {name} is invalid")
        for name in ("contract_revision", "state_revision", "audit_round"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"final audit {name} is invalid")
        if self.lifecycle not in {"AUDITING", "DONE"}:
            raise ValueError("final audit lifecycle is invalid")
        parse_rfc3339_z_seconds(self.audit_anchor)
        if not isinstance(self.coverage, dict) or set(self.coverage) != _COVERAGE_FIELDS:
            raise ValueError("final audit coverage fields mismatch")
        if not all(type(value) is int and value >= 0 for value in self.coverage.values()):
            raise ValueError("final audit coverage values are invalid")
        total = self.coverage["blocking_criteria_total"]
        passing = self.coverage["blocking_criteria_with_passing_evidence"]
        deterministic = self.coverage["deterministic_coverage"]
        if (
            passing > total
            or deterministic > passing
            or self.coverage["unverified"] != total - passing
        ):
            raise ValueError("final audit coverage is inconsistent")
        if not isinstance(self.issues, list) or not all(
            isinstance(issue, AuditIssue) for issue in self.issues
        ):
            raise ValueError("final audit issues are invalid")
        if self.issues != sorted(self.issues, key=_issue_sort_key):
            raise ValueError("final audit issues are not canonically ordered")
        if self.delivery_status not in {
            "not_required",
            "verified",
            "missing",
            "invalid",
        }:
            raise ValueError("final audit delivery status is invalid")
        if self.rpd_decision not in {"not_required", "verified", "missing"}:
            raise ValueError("final audit RPD decision is invalid")

    @property
    def blocking_count(self) -> int:
        return sum(
            1 for issue in self.issues if issue.issue_type in BLOCKING_ISSUES
        )

    @property
    def can_complete(self) -> bool:
        return self.blocking_count == 0

    @property
    def terminal_state_revision(self) -> int:
        return self.state_revision

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_anchor": self.audit_anchor,
            "audit_round": self.audit_round,
            "can_complete": self.can_complete,
            "contract_revision": self.contract_revision,
            "contract_sha256": self.contract_sha256,
            "coverage": dict(self.coverage),
            "delivery_status": self.delivery_status,
            "event_tail_sha256": self.event_tail_sha256,
            "evidence_sha256": self.evidence_sha256,
            "goal_id": self.goal_id,
            "issues": [issue.to_dict() for issue in self.issues],
            "lifecycle": self.lifecycle,
            "rpd_decision": self.rpd_decision,
            "schema_version": self.schema_version,
            "state_revision": self.state_revision,
            "state_sha256": self.state_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditReport":
        if not isinstance(data, dict):
            raise ValueError("final audit must be an object")
        expected = {
            "audit_anchor",
            "audit_round",
            "can_complete",
            "contract_revision",
            "contract_sha256",
            "coverage",
            "delivery_status",
            "event_tail_sha256",
            "evidence_sha256",
            "goal_id",
            "issues",
            "lifecycle",
            "rpd_decision",
            "schema_version",
            "state_revision",
            "state_sha256",
        }
        if set(data) != expected:
            raise ValueError("final audit fields mismatch")
        issues_data = data["issues"]
        if not isinstance(issues_data, list):
            raise ValueError("final audit issues must be an array")
        issues: list[AuditIssue] = []
        allowed_issue = set(AuditIssue.__dataclass_fields__)
        for item in issues_data:
            if not isinstance(item, dict) or not set(item).issubset(allowed_issue):
                raise ValueError("final audit issue is malformed")
            if "issue_type" not in item or "message" not in item:
                raise ValueError("final audit issue is incomplete")
            issues.append(AuditIssue(**item))
        report = cls(
            goal_id=data["goal_id"],
            contract_sha256=data["contract_sha256"],
            contract_revision=data["contract_revision"],
            state_revision=data["state_revision"],
            state_sha256=data["state_sha256"],
            lifecycle=data["lifecycle"],
            audit_round=data["audit_round"],
            audit_anchor=data["audit_anchor"],
            event_tail_sha256=data["event_tail_sha256"],
            evidence_sha256=data["evidence_sha256"],
            coverage=data["coverage"],
            issues=issues,
            delivery_status=data["delivery_status"],
            rpd_decision=data["rpd_decision"],
            schema_version=data["schema_version"],
        )
        if data["can_complete"] is not report.can_complete:
            raise ValueError("final audit completion flag is inconsistent")
        return report


def _issue_sort_key(issue: AuditIssue) -> tuple[str, str, str, str, str]:
    return (
        issue.issue_type,
        issue.phase_id or "",
        issue.criterion_id or "",
        issue.evidence_id or "",
        issue.message,
    )


def _freshness_policy(contract: Contract) -> tuple[int, dict[str, int]]:
    default = contract.loop.data.get(
        "evidence_max_age_seconds", DEFAULT_MAX_AGE_SECONDS
    )
    if type(default) is not int or default <= 0:
        raise ValueError("loop.evidence_max_age_seconds must be a positive integer")
    overrides = contract.loop.data.get("evidence_max_age_by_type", {})
    if not isinstance(overrides, dict):
        raise ValueError("loop.evidence_max_age_by_type must be an object")
    normalized: dict[str, int] = {}
    for evidence_type, max_age in overrides.items():
        if evidence_type not in EVIDENCE_TYPES:
            raise ValueError(f"unknown evidence freshness type {evidence_type}")
        if type(max_age) is not int or max_age <= 0:
            raise ValueError(
                f"freshness override for {evidence_type} must be a positive integer"
            )
        normalized[evidence_type] = max_age
    return default, normalized


def _audit_anchor(state: State, events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        target = event.get("state")
        if (
            isinstance(target, dict)
            and target.get("audit_round") == state.audit_round
            and event.get("event_type", "").endswith("->AUDITING")
        ):
            return event["timestamp"]
    raise ValueError("current audit round has no transition into AUDITING")


def _record_freshness_issue(
    record: EvidenceRecord,
    *,
    anchor: str,
    default_max_age: int,
    overrides: dict[str, int],
) -> str | None:
    anchor_time = parse_rfc3339_z_seconds(anchor)
    captured = parse_rfc3339_z_seconds(record.captured_at)
    if captured > anchor_time + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        return "captured_at exceeds the 300-second future-skew allowance"
    effective_captured = min(captured, anchor_time)
    max_age = overrides.get(record.type, default_max_age)
    if (anchor_time - effective_captured).total_seconds() > max_age:
        return f"evidence exceeds its {max_age}-second maximum age"
    if record.fresh_until != "audit_end":
        fresh_until = parse_rfc3339_z_seconds(record.fresh_until)
        if fresh_until < anchor_time:
            return "fresh_until expires before the audit anchor"
    return None


def _receipt_freshness_issue(
    sent_at: str, *, anchor: str, max_age: int
) -> str | None:
    anchor_time = parse_rfc3339_z_seconds(anchor)
    sent = parse_rfc3339_z_seconds(sent_at)
    if sent > anchor_time + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        return "sent_at exceeds the 300-second future-skew allowance"
    effective_sent = min(sent, anchor_time)
    if (anchor_time - effective_sent).total_seconds() > max_age:
        return f"sent_at exceeds the {max_age}-second maximum age"
    return None


def _delivery_status(
    contract: Contract,
    state: State,
    package_root: Path | None,
    *,
    audit_anchor: str,
    default_max_age: int,
) -> tuple[str, list[AuditIssue]]:
    delivery = contract.delivery.data
    try:
        receipts_required = delivery_receipt_required(delivery)
    except ReceiptValidationError as exc:
        return "invalid", [
            AuditIssue("AUDIT_CORRUPTION", f"delivery receipt policy is invalid: {exc}")
        ]
    if not receipts_required:
        return "not_required", []
    review_required = delivery.get("review_pack_required") is True
    final_required = bool(delivery.get("items"))
    if not review_required and not final_required:
        return "invalid", [
            AuditIssue(
                "AUDIT_CORRUPTION",
                "required delivery receipt policy has no review pack or final items",
            )
        ]
    if package_root is None:
        return "missing", [
            AuditIssue("AUDIT_GAP", "required delivery cannot be verified without package artifacts")
        ]
    target = delivery.get("target")
    if not isinstance(target, str) or not target:
        return "invalid", [
            AuditIssue("AUDIT_CORRUPTION", "required delivery target is not declared")
        ]
    issues: list[AuditIssue] = []
    if review_required:
        path = package_root / "out/review-md-files-delivery-receipt.json"
        if not os.path.lexists(path):
            path = None
        try:
            if path is None:
                raise FileNotFoundError
            declared = delivery.get("files", [])
            if not isinstance(declared, list) or not all(
                isinstance(item, str) and item for item in declared
            ) or len(declared) != len(set(declared)) or not REQUIRED_REVIEW_FILES.issubset(
                declared
            ):
                raise ReceiptValidationError("delivery.files is invalid")
            files = sorted(
                item
                for item in declared
                if item != "RESEARCH.md"
                or os.path.lexists(package_root / item)
            )
            hashes = {
                item: hashlib.sha256(
                    read_regular_file_no_follow(package_root / item, package_root)
                ).hexdigest()
                for item in files
            }
            receipt = read_receipt(path, package_root)
            validate_review_receipt(
                receipt, state=state, target=target, hashes=hashes
            )
            if receipt["files"] != files:
                raise ReceiptValidationError(
                    "receipt file order is not the canonical full set"
                )
            freshness = _receipt_freshness_issue(
                receipt["sent_at"],
                anchor=audit_anchor,
                max_age=default_max_age,
            )
            if freshness is not None:
                raise ReceiptValidationError(freshness)
        except FileNotFoundError:
            issues.append(AuditIssue("AUDIT_GAP", "required review delivery receipt is missing"))
        except (OSError, ValueError, ReceiptValidationError) as exc:
            issues.append(
                AuditIssue("AUDIT_CORRUPTION", f"review delivery receipt is invalid: {exc}")
            )
    if final_required:
        path = package_root / "out/final-artifacts-delivery-receipt.json"
        if not os.path.lexists(path):
            path = None
        try:
            if path is None:
                raise FileNotFoundError
            receipt = read_receipt(path, package_root)
            validate_final_receipt(receipt, state=state, target=target)
        except FileNotFoundError:
            issues.append(AuditIssue("AUDIT_GAP", "required final delivery receipt is missing"))
        except (OSError, ValueError, ReceiptValidationError) as exc:
            issues.append(
                AuditIssue("AUDIT_CORRUPTION", f"final delivery receipt is invalid: {exc}")
            )
    if issues:
        status = (
            "invalid"
            if any(issue.issue_type == "AUDIT_CORRUPTION" for issue in issues)
            else "missing"
        )
        return status, issues
    return "verified", []


def audit_contract(
    contract: Contract,
    evidence: list[EvidenceRecord],
    *,
    state: State | None = None,
    events: list[dict[str, Any]] | None = None,
    risk_policy: dict[str, Any] | None = None,
    package_root: str | Path | None = None,
    evidence_digest: str | None = None,
    pre_issues: list[AuditIssue] | None = None,
) -> AuditReport:
    issues = list(pre_issues or [])
    canonical_hash = hashlib.sha256(canonical_json(contract).encode("utf-8")).hexdigest()
    if state is None:
        state = State(
            goal_id=contract.goal.id,
            contract_sha256=canonical_hash,
            contract_revision=contract.contract_revision,
            state_revision=1,
            lifecycle="AUDITING",
            current_phase_id=contract.phases[0].id,
            phase_status="COMPLETE",
            audit_round=1,
        )
        issues.append(AuditIssue("AUDIT_CORRUPTION", "authoritative runtime state is missing"))
    if events is None:
        events = []
        issues.append(AuditIssue("AUDIT_CORRUPTION", "authoritative event journal is missing"))
    if (
        state.goal_id != contract.goal.id
        or state.contract_sha256 != canonical_hash
        or state.contract_revision != contract.contract_revision
    ):
        issues.append(AuditIssue("AUDIT_CORRUPTION", "state identity does not match contract"))
    if state.lifecycle in {"AUDITING", "DONE"} and (
        state.phase_status != "COMPLETE" or state.blocker is not None
    ):
        issues.append(
            AuditIssue(
                "AUDIT_CORRUPTION",
                "AUDITING and DONE require an unblocked COMPLETE phase",
                state.current_phase_id,
            )
        )
    try:
        phase_ids = {phase.id for phase in contract.phases}
        dependencies = {phase.id: set(phase.depends_on) for phase in contract.phases}
        ordinals = {phase.id: phase.ordinal for phase in contract.phases}
        validate_event_journal(
            events,
            goal_id=contract.goal.id,
            contract_sha256=canonical_hash,
            contract_revision=contract.contract_revision,
            phase_ids=phase_ids,
            phase_dependencies=dependencies,
            phase_ordinals=ordinals,
        )
    except (JournalCorruptionError, ValueError) as exc:
        issues.append(AuditIssue("AUDIT_CORRUPTION", f"event journal is invalid: {exc}"))
    anchor = "1970-01-01T00:00:00Z"
    try:
        if state.lifecycle not in {"AUDITING", "DONE"}:
            raise ValueError("state is not in AUDITING or DONE")
        anchor = _audit_anchor(state, events)
    except ValueError as exc:
        issues.append(AuditIssue("AUDIT_CORRUPTION", f"audit anchor is invalid: {exc}"))

    try:
        default_max_age, overrides = _freshness_policy(contract)
    except ValueError as exc:
        default_max_age, overrides = DEFAULT_MAX_AGE_SECONDS, {}
        issues.append(AuditIssue("AUDIT_CORRUPTION", f"freshness policy is invalid: {exc}"))

    phases_with_policy = any(phase.risk_tags for phase in contract.phases)
    policy_requirements: dict[str, list[str]] = {}
    if phases_with_policy and risk_policy is None:
        issues.append(AuditIssue("AUDIT_CORRUPTION", "risk policy is unavailable"))
    elif risk_policy is not None:
        try:
            policy_requirements = mandatory_evidence_requirements(contract, risk_policy)
        except Exception as exc:
            issues.append(AuditIssue("AUDIT_CORRUPTION", f"risk policy is invalid: {exc}"))

    valid_by_criterion: dict[tuple[str, str], list[EvidenceRecord]] = {}
    criteria_by_key = {
        (phase.id, criterion.id): criterion
        for phase in contract.phases
        for criterion in phase.criteria
    }
    valid_records: list[EvidenceRecord] = []
    try:
        validate_evidence_records(evidence)
    except ValueError as exc:
        issues.append(AuditIssue("AUDIT_CORRUPTION", str(exc)))
    seen_ids: set[str] = set()
    for record in evidence:
        if not isinstance(record, EvidenceRecord):
            issues.append(AuditIssue("AUDIT_CORRUPTION", "evidence contains an arbitrary record shape"))
            continue
        if record.evidence_id in seen_ids:
            issues.append(
                AuditIssue(
                    "AUDIT_CORRUPTION",
                    "duplicate evidence id",
                    record.phase_id,
                    record.criterion_id,
                    record.evidence_id,
                )
            )
            continue
        seen_ids.add(record.evidence_id)
        try:
            validate_record_against_contract(
                record,
                contract,
                state,
                policy_requirements=policy_requirements,
            )
        except ValueError as exc:
            issues.append(
                AuditIssue(
                    "AUDIT_CORRUPTION",
                    str(exc),
                    record.phase_id,
                    record.criterion_id,
                    record.evidence_id,
                )
            )
            continue
        try:
            freshness = _record_freshness_issue(
                record,
                anchor=anchor,
                default_max_age=default_max_age,
                overrides=overrides,
            )
        except ValueError as exc:
            freshness = f"freshness metadata is invalid: {exc}"
        if freshness is not None:
            issues.append(
                AuditIssue(
                    "AUDIT_GAP",
                    freshness,
                    record.phase_id,
                    record.criterion_id,
                    record.evidence_id,
                )
            )
            continue
        if record.result != "pass":
            continue
        valid_records.append(record)
        key = (record.phase_id, record.criterion_id)
        criterion = criteria_by_key.get(key)
        if criterion is not None and evidence_satisfies_verifier(
            record, criterion.verifier
        ):
            valid_by_criterion.setdefault(key, []).append(record)

    total_blocking = 0
    deterministic = 0
    passing_blocking = 0
    for phase in sorted(contract.phases, key=lambda item: (item.ordinal, item.id)):
        for criterion in sorted(phase.criteria, key=lambda item: item.id):
            if not criterion.blocking:
                continue
            total_blocking += 1
            records = valid_by_criterion.get((phase.id, criterion.id), [])
            if not records:
                issues.append(
                    AuditIssue(
                        "AUDIT_GAP",
                        "blocking criterion has no fully valid fresh passing evidence",
                        phase.id,
                        criterion.id,
                    )
                )
                continue
            passing_blocking += 1
            if any(record.type == "command_result" and record.replayable for record in records):
                deterministic += 1

    policy_by_phase: dict[str, set[str]] = {}
    rpd_by_phase: dict[str, set[str]] = {}
    approval_ids: set[str] = set()
    for record in valid_records:
        policy_by_phase.setdefault(record.phase_id, set()).update(
            record.metadata.get("policy_evidence", [])
        )
        rpd_by_phase.setdefault(record.phase_id, set()).update(
            record.metadata.get("rpd_focus", [])
        )
        if record.type == "approval_manifest":
            approval_ids.update(record.metadata.get("approval_ids", []))
    for phase in sorted(contract.phases, key=lambda item: (item.ordinal, item.id)):
        for label in policy_requirements.get(phase.id, []):
            if label not in policy_by_phase.get(phase.id, set()):
                issues.append(
                    AuditIssue(
                        "AUDIT_GAP",
                        f"mandatory policy evidence is missing: {label}",
                        phase.id,
                    )
                )
        if phase.rpd.required:
            for focus in sorted(set(phase.rpd.focus)):
                if focus not in rpd_by_phase.get(phase.id, set()):
                    issues.append(
                        AuditIssue(
                            "AUDIT_GAP",
                            f"RPD focus evidence is missing: {focus}",
                            phase.id,
                        )
                    )
    for approval in sorted(contract.approvals, key=lambda item: item.id):
        if approval.required and approval.id not in approval_ids:
            issues.append(
                AuditIssue(
                    "AUDIT_GAP", f"required approval evidence is missing: {approval.id}"
                )
            )

    delivery_status, delivery_issues = _delivery_status(
        contract,
        state,
        Path(package_root) if package_root is not None else None,
        audit_anchor=anchor,
        default_max_age=default_max_age,
    )
    issues.extend(delivery_issues)
    rpd_required = any(phase.rpd.required for phase in contract.phases)
    rpd_missing = any(
        issue.issue_type in BLOCKING_ISSUES and "RPD focus" in issue.message
        for issue in issues
    )
    rpd_decision = (
        "not_required" if not rpd_required else ("missing" if rpd_missing else "verified")
    )
    ordered_issues = sorted(issues, key=_issue_sort_key)
    coverage = {
        "blocking_criteria_total": total_blocking,
        "blocking_criteria_with_passing_evidence": passing_blocking,
        "deterministic_coverage": deterministic,
        "unverified": total_blocking - passing_blocking,
    }
    digest = evidence_digest
    if digest is None:
        try:
            digest = hashlib.sha256(evidence_json_bytes(evidence)).hexdigest()
        except Exception:
            digest = "0" * 64
    event_tail = events[-1].get("event_sha256", "0" * 64) if events else "0" * 64
    return AuditReport(
        goal_id=contract.goal.id,
        contract_sha256=state.contract_sha256,
        contract_revision=contract.contract_revision,
        state_revision=state.state_revision,
        state_sha256=state_sha256(state),
        lifecycle=state.lifecycle,
        audit_round=state.audit_round,
        audit_anchor=anchor,
        event_tail_sha256=event_tail,
        evidence_sha256=digest,
        coverage=coverage,
        issues=ordered_issues,
        delivery_status=delivery_status,
        rpd_decision=rpd_decision,
    )


def audit_json_bytes(report: AuditReport) -> bytes:
    return (
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def render_final_audit_md(report: AuditReport) -> str:
    lines = [
        "# Final audit",
        "",
        f"Goal: `{report.goal_id}`",
        f"Contract SHA-256: `{report.contract_sha256}`",
        f"Contract revision: `{report.contract_revision}`",
        f"State revision: `{report.state_revision}`",
        f"State SHA-256: `{report.state_sha256}`",
        f"Lifecycle: `{report.lifecycle}`",
        f"Audit round: `{report.audit_round}`",
        f"Audit anchor: `{report.audit_anchor}`",
        f"Event tail SHA-256: `{report.event_tail_sha256}`",
        f"Evidence SHA-256: `{report.evidence_sha256}`",
        f"Delivery: `{report.delivery_status}`",
        f"RPD: `{report.rpd_decision}`",
        f"Can complete: {'yes' if report.can_complete else 'no'}",
        "",
        "## Coverage",
    ]
    lines.extend(
        f"- {name}: {value}" for name, value in sorted(report.coverage.items())
    )
    lines.extend(["", "## Issues"])
    if report.issues:
        for issue in report.issues:
            location = "/".join(
                value
                for value in (issue.phase_id, issue.criterion_id, issue.evidence_id)
                if value
            )
            lines.append(
                f"- {issue.issue_type}: {issue.message}"
                + (f" ({location})" if location else "")
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_final_audit(
    report: AuditReport,
    out_dir: str | Path,
    *,
    root: str | Path | None = None,
) -> tuple[Path, Path]:
    out = Path(out_dir)
    if root is None:
        out.mkdir(parents=True, exist_ok=True)
    json_path = out / "final-audit.json"
    markdown_path = out / "final-audit.md"
    write_bytes_atomic(json_path, audit_json_bytes(report), root=root)
    write_utf8_lf(
        markdown_path, render_final_audit_md(report), root=root
    )
    return json_path, markdown_path


def read_final_audit(root: str | Path) -> AuditReport:
    package_root = Path(root)
    path = package_root / "reports/final-audit.json"
    raw = read_regular_file_no_follow(path, package_root)
    try:
        report = AuditReport.from_dict(json.loads(raw))
    except Exception as exc:
        raise ValueError("SGV-AUDIT-REPORT-INVALID") from exc
    if raw != audit_json_bytes(report):
        raise ValueError("SGV-AUDIT-REPORT-INVALID")
    markdown = read_regular_file_no_follow(
        package_root / "reports/final-audit.md", package_root
    )
    if markdown != render_final_audit_md(report).encode("utf-8"):
        raise ValueError("SGV-AUDIT-REPORT-INVALID")
    return report


def _load_package_inputs(
    root: Path,
) -> tuple[Contract, State, list[dict[str, Any]], list[EvidenceRecord], dict[str, Any], str, list[AuditIssue]]:
    from .validate import validate_sealed_package

    store = StateStore(root)
    events = store._validated_events()
    state = State.from_dict(events[-1]["state"])
    store._assert_projections_current(state)
    contract_raw = read_regular_file_no_follow(root / "CONTRACT.json", root)
    contract = contract_from_dict(json.loads(contract_raw), strict=True)
    if contract_raw != canonical_json(contract).encode("utf-8"):
        raise ValueError("SGV-AUDIT-CONTRACT-MISMATCH")
    evidence_path = root / "runtime/evidence.json"
    evidence_raw = read_regular_file_no_follow(evidence_path, root)
    pre_issues: list[AuditIssue] = [
        AuditIssue(
            "AUDIT_CORRUPTION",
            f"sealed package is invalid: {diagnostic.code} {diagnostic.pointer}",
        )
        for diagnostic in validate_sealed_package(root)
    ]
    try:
        evidence = read_evidence(evidence_path, root=root)
    except Exception as exc:
        evidence = []
        pre_issues.append(
            AuditIssue("AUDIT_CORRUPTION", f"evidence store is malformed: {exc}")
        )
    policy_path = root / "spec/risk-policy.json"
    policy_bytes = read_regular_file_no_follow(policy_path, root)
    if not verify_sealed_artifact(root, "spec/risk-policy.json", data=policy_bytes):
        raise ValueError("SGV-PACKAGE-MISSING-MANIFEST")
    policy = json.loads(policy_bytes)
    if not isinstance(policy, dict) or not isinstance(policy.get("risk_tags"), dict):
        raise ValueError("sealed artifact risk policy is malformed")
    return (
        contract,
        state,
        events,
        evidence,
        policy,
        hashlib.sha256(evidence_raw).hexdigest(),
        pre_issues,
    )


def recompute_package_audit(root: str | Path) -> AuditReport:
    package_root = Path(root)
    contract, state, events, evidence, policy, digest, pre_issues = _load_package_inputs(
        package_root
    )
    return audit_contract(
        contract,
        evidence,
        state=state,
        events=events,
        risk_policy=policy,
        package_root=package_root,
        evidence_digest=digest,
        pre_issues=pre_issues,
    )


def audit_package(root: str | Path) -> AuditReport:
    package_root = Path(root)
    store = StateStore(package_root)
    with package_operation_lock(package_root):
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            assert_runtime_mutable(package_root)
            report = recompute_package_audit(package_root)
            write_final_audit(
                report, package_root / "reports", root=package_root
            )
            return report


def guard_done_transition(root: Path, state: State) -> AuditReport:
    if (
        state.lifecycle != "AUDITING"
        or state.phase_status != "COMPLETE"
        or state.blocker is not None
    ):
        raise ValueError("SGV-STATE-DONE-REQUIRES-AUDIT")
    stored = read_final_audit(root)
    recomputed = recompute_package_audit(root)
    if (
        not stored.can_complete
        or audit_json_bytes(stored) != audit_json_bytes(recomputed)
        or stored.state_revision != state.state_revision
        or stored.state_sha256 != state_sha256(state)
    ):
        raise ValueError("SGV-STATE-DONE-REQUIRES-AUDIT")
    return stored


def write_done_audit(root: Path) -> AuditReport:
    report = recompute_package_audit(root)
    if not report.can_complete or report.lifecycle != "DONE":
        raise ValueError("SGV-STATE-DONE-REQUIRES-AUDIT")
    write_final_audit(report, root / "reports", root=root)
    return report


def terminal_markers_allowed(state: State, report: AuditReport) -> bool:
    return (
        state.lifecycle == "DONE"
        and state.phase_status == "COMPLETE"
        and state.blocker is None
        and report.lifecycle == "DONE"
        and report.can_complete
        and report.state_revision == state.state_revision
        and report.state_sha256 == state_sha256(state)
        and report.goal_id == state.goal_id
        and report.contract_sha256 == state.contract_sha256
        and report.contract_revision == state.contract_revision
    )
