from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .events import now_rfc3339_z_seconds, parse_rfc3339_z_seconds
from .model import canonical_json, contract_from_dict
from .portable import (
    package_lock,
    package_operation_lock,
    read_regular_file_no_follow,
    unlink_regular_file_no_follow,
    write_bytes_atomic,
)
from .state import State, StateStore, assert_runtime_mutable


EVIDENCE_TYPES = frozenset(
    {
        "command_result",
        "file_hash",
        "git_diff",
        "api_response",
        "log_excerpt",
        "screenshot",
        "manual_observation",
        "external_source_snapshot",
        "delivery_ack",
        "approval_manifest",
    }
)
RESULTS = frozenset({"pass", "fail", "stale", "unverified"})
REDACTIONS = frozenset({"passed", "redacted"})
ARTIFACT_TYPES = EVIDENCE_TYPES - {"command_result", "manual_observation"}
AUXILIARY_EVIDENCE_TYPES = frozenset({"approval_manifest", "delivery_ack"})
AUXILIARY_CRITERION_ID = "__phase__"
METADATA_FIELDS = frozenset(
    {
        "policy_evidence",
        "rpd_focus",
        "approval_ids",
        "delivery_kind",
        "notes",
    }
)
_SHA256 = re.compile(r"[a-f0-9]{64}")


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    goal_id: str
    contract_sha256: str
    contract_revision: int
    phase_id: str
    criterion_id: str
    type: str
    producer: str
    captured_at: str
    fresh_until: str
    replayable: bool
    result: str
    redaction: str
    command: str | None = None
    exit_code: int | None = None
    assertion: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    artifact_sha256: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "goal_id",
            "contract_sha256",
            "phase_id",
            "criterion_id",
            "type",
            "producer",
            "captured_at",
            "fresh_until",
            "result",
            "redaction",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
                raise ValueError(f"{name} is required and must be one line")
        if not _SHA256.fullmatch(self.contract_sha256):
            raise ValueError("contract_sha256 must be a lowercase SHA-256")
        if type(self.contract_revision) is not int or self.contract_revision < 1:
            raise ValueError("contract_revision must be a positive integer")
        if self.type not in EVIDENCE_TYPES:
            raise ValueError(f"unsupported evidence type: {self.type}")
        if self.result not in RESULTS:
            raise ValueError(f"unsupported evidence result: {self.result}")
        if self.redaction not in REDACTIONS:
            raise ValueError("evidence redaction must be passed or redacted")
        if type(self.replayable) is not bool:
            raise ValueError("replayable must be a boolean")
        if self.replayable != (self.type == "command_result"):
            raise ValueError(
                "only command_result evidence is replayable and it must be replayable"
            )
        parse_rfc3339_z_seconds(self.captured_at)
        if self.fresh_until != "audit_end":
            parse_rfc3339_z_seconds(self.fresh_until)
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")
        unknown_metadata = sorted(set(self.metadata) - METADATA_FIELDS)
        if unknown_metadata:
            raise ValueError(
                f"unknown evidence metadata fields: {', '.join(unknown_metadata)}"
            )
        for name in ("policy_evidence", "rpd_focus", "approval_ids"):
            if name in self.metadata:
                value = self.metadata[name]
                if (
                    not isinstance(value, list)
                    or not all(isinstance(item, str) and item for item in value)
                    or len(value) != len(set(value))
                ):
                    raise ValueError(f"metadata.{name} must be a unique string list")
        for name in ("delivery_kind", "notes"):
            if name in self.metadata and (
                not isinstance(self.metadata[name], str) or not self.metadata[name]
            ):
                raise ValueError(f"metadata.{name} must be a nonempty string")
        if self.type == "command_result":
            if not isinstance(self.command, str) or not self.command:
                raise ValueError("command_result requires command")
            if type(self.exit_code) is not int:
                raise ValueError("command_result requires an integer exit_code")
        elif self.command is not None or self.exit_code is not None:
            raise ValueError("non-command evidence cannot carry command metadata")
        if self.assertion is not None and (
            not isinstance(self.assertion, str) or not self.assertion
        ):
            raise ValueError("assertion must be a nonempty string or null")
        if self.type in ARTIFACT_TYPES and (
            not isinstance(self.artifact_sha256, str)
            or not _SHA256.fullmatch(self.artifact_sha256)
        ):
            raise ValueError(f"{self.type} evidence requires artifact_sha256")
        if self.artifact_sha256 is not None and not _SHA256.fullmatch(
            self.artifact_sha256
        ):
            raise ValueError("artifact_sha256 must be a lowercase SHA-256")
        for path_name in ("stdout_path", "stderr_path"):
            value = getattr(self, path_name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{path_name} must be a nonempty string")
        if self.type == "approval_manifest" and not self.metadata.get(
            "approval_ids"
        ):
            raise ValueError("approval_manifest requires metadata.approval_ids")
        if self.type == "delivery_ack" and not self.metadata.get("delivery_kind"):
            raise ValueError("delivery_ack requires metadata.delivery_kind")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRecord":
        if not isinstance(data, dict):
            raise ValueError("evidence record must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - allowed)
        required = {
            "evidence_id",
            "goal_id",
            "contract_sha256",
            "contract_revision",
            "phase_id",
            "criterion_id",
            "type",
            "producer",
            "captured_at",
            "fresh_until",
            "replayable",
            "result",
            "redaction",
        }
        missing = sorted(required - set(data))
        if unknown:
            raise ValueError(f"unknown evidence fields: {', '.join(unknown)}")
        if missing:
            raise ValueError(f"missing evidence fields: {', '.join(missing)}")
        return cls(**data)

    @classmethod
    def pass_record(
        cls,
        *,
        evidence_id: str,
        goal_id: str,
        contract_sha256: str,
        contract_revision: int,
        phase_id: str,
        criterion_id: str,
        type: str = "command_result",
        producer: str = "goal_executor",
        command: str | None = None,
        exit_code: int | None = 0,
        assertion: str | None = None,
        captured_at: str | None = None,
        fresh_until: str = "audit_end",
        artifact_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "EvidenceRecord":
        return cls(
            evidence_id=evidence_id,
            goal_id=goal_id,
            contract_sha256=contract_sha256,
            contract_revision=contract_revision,
            phase_id=phase_id,
            criterion_id=criterion_id,
            type=type,
            producer=producer,
            captured_at=captured_at or now_rfc3339_z_seconds(),
            fresh_until=fresh_until,
            replayable=type == "command_result",
            result="pass",
            redaction="passed",
            command=command,
            exit_code=exit_code if type == "command_result" else None,
            assertion=assertion,
            artifact_sha256=artifact_sha256,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: value
            for name, value in self.__dict__.items()
            if value is not None and (name != "metadata" or value)
        }
        if "metadata" in result:
            result["metadata"] = {
                name: sorted(value)
                if name in {"policy_evidence", "rpd_focus", "approval_ids"}
                else value
                for name, value in result["metadata"].items()
            }
        return result


def validate_evidence_records(records: list[EvidenceRecord]) -> None:
    if not isinstance(records, list):
        raise ValueError("evidence must be a list")
    identifiers: set[str] = set()
    for record in records:
        if not isinstance(record, EvidenceRecord):
            raise ValueError("evidence list contains a non-record")
        if record.evidence_id in identifiers:
            raise ValueError(f"duplicate evidence id: {record.evidence_id}")
        identifiers.add(record.evidence_id)


def evidence_json_bytes(records: list[EvidenceRecord]) -> bytes:
    validate_evidence_records(records)
    ordered = sorted(records, key=lambda record: record.evidence_id)
    return (
        json.dumps(
            [record.to_dict() for record in ordered],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def evidence_sha256(records: list[EvidenceRecord]) -> str:
    return hashlib.sha256(evidence_json_bytes(records)).hexdigest()


def read_evidence(path: str | Path, *, root: str | Path | None = None) -> list[EvidenceRecord]:
    evidence_path = Path(path)
    trusted_root = Path(root) if root is not None else evidence_path.parent
    raw = read_regular_file_no_follow(evidence_path, trusted_root)
    try:
        data = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("evidence JSON is malformed") from exc
    if not isinstance(data, list):
        raise ValueError("evidence must be a JSON array")
    records = [EvidenceRecord.from_dict(item) for item in data]
    validate_evidence_records(records)
    if raw != evidence_json_bytes(records):
        raise ValueError("evidence bytes are not canonical")
    return records


def write_evidence(
    path: str | Path,
    records: list[EvidenceRecord],
    *,
    root: str | Path | None = None,
) -> None:
    write_bytes_atomic(path, evidence_json_bytes(records), root=root)


def _load_contract_and_state(root: Path) -> tuple[Any, State, StateStore]:
    store = StateStore(root)
    events = store._validated_events()
    state = State.from_dict(events[-1]["state"])
    store._assert_projections_current(state)
    raw = read_regular_file_no_follow(root / "CONTRACT.json", root)
    contract = contract_from_dict(json.loads(raw), strict=True)
    if raw != canonical_json(contract).encode("utf-8"):
        raise ValueError("SGV-EVIDENCE-CONTRACT-MISMATCH")
    return contract, state, store


def expected_evidence_type(verifier: Any) -> str | None:
    if verifier.command_id is not None:
        return "command_result"
    if verifier.type == "assertion":
        return "manual_observation"
    if verifier.type in EVIDENCE_TYPES - AUXILIARY_EVIDENCE_TYPES - {
        "command_result"
    }:
        return verifier.type
    return None


def evidence_satisfies_verifier(record: EvidenceRecord, verifier: Any) -> bool:
    return (
        record.type not in AUXILIARY_EVIDENCE_TYPES
        and record.type == expected_evidence_type(verifier)
    )


def validate_record_against_contract(record: EvidenceRecord, contract: Any, state: State) -> None:
    if (
        record.goal_id != state.goal_id
        or record.contract_sha256 != state.contract_sha256
        or record.contract_revision != state.contract_revision
    ):
        raise ValueError("SGV-EVIDENCE-CONTRACT-MISMATCH")
    phases = {phase.id: phase for phase in contract.phases}
    phase = phases.get(record.phase_id)
    if phase is None:
        raise ValueError("SGV-EVIDENCE-PHASE-MISMATCH")
    criteria = {criterion.id: criterion for criterion in phase.criteria}
    if record.type in AUXILIARY_EVIDENCE_TYPES:
        if record.criterion_id != AUXILIARY_CRITERION_ID:
            raise ValueError("SGV-EVIDENCE-CRITERION-MISMATCH")
        if record.assertion is not None:
            raise ValueError("SGV-EVIDENCE-ASSERTION-MISMATCH")
        return
    criterion = criteria.get(record.criterion_id)
    if criterion is None:
        raise ValueError("SGV-EVIDENCE-CRITERION-MISMATCH")
    verifier = criterion.verifier
    expected_type = expected_evidence_type(verifier)
    if expected_type is None or record.type != expected_type:
        raise ValueError("SGV-EVIDENCE-TYPE-MISMATCH")
    if record.type == "command_result":
        commands = {command.id: command for command in phase.commands}
        declared = commands.get(verifier.command_id)
        if declared is None or record.command != declared.command:
            raise ValueError("SGV-EVIDENCE-COMMAND-MISMATCH")
        if record.result == "pass" and record.exit_code != verifier.expected_exit:
            raise ValueError("SGV-EVIDENCE-EXIT-MISMATCH")
    elif verifier.expected_exit is not None:
        raise ValueError("SGV-EVIDENCE-EXIT-MISMATCH")
    if record.result == "pass" and record.assertion != verifier.expected_assertion:
        raise ValueError("SGV-EVIDENCE-ASSERTION-MISMATCH")


def _invalidate_derived_audit(root: Path) -> None:
    for relative in ("reports/final-audit.json", "reports/final-audit.md"):
        path = root / relative
        if not os.path.lexists(path):
            continue
        try:
            unlink_regular_file_no_follow(path, root)
        except Exception as exc:
            raise ValueError("SGV-EVIDENCE-AUDIT-INVALIDATION") from exc


class EvidenceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / "runtime" / "evidence.json"

    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        with package_operation_lock(self.root):
            store = StateStore(self.root)
            store._assert_lock_safe()
            with package_lock(store.lock, root=self.root):
                assert_runtime_mutable(self.root)
                contract, state, _ = _load_contract_and_state(self.root)
                if state.lifecycle not in {"RUNNING", "AUDITING"}:
                    raise ValueError("SGV-EVIDENCE-STATE-MISMATCH")
                validate_record_against_contract(record, contract, state)
                records = read_evidence(self.path, root=self.root)
                if any(item.evidence_id == record.evidence_id for item in records):
                    raise ValueError("SGV-EVIDENCE-DUPLICATE-ID")
                updated = [*records, record]
                _invalidate_derived_audit(self.root)
                write_evidence(self.path, updated, root=self.root)
                return record


def record_evidence(root: str | Path, record: EvidenceRecord) -> EvidenceRecord:
    return EvidenceStore(root).append(record)
