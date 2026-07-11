from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .portable import append_regular_file_no_follow, read_regular_file_no_follow


ALLOWED_TRANSITIONS = frozenset(
    {
        ("DRAFT", "COMPILED"),
        ("COMPILED", "PLAN_REVIEWED"),
        ("PLAN_REVIEWED", "PREFLIGHT_GREEN"),
        ("PREFLIGHT_GREEN", "READY_TO_DISPATCH"),
        ("READY_TO_DISPATCH", "RUNNING"),
        ("RUNNING", "RECOVERING"),
        ("RECOVERING", "RUNNING"),
        ("RUNNING", "WAITING_APPROVAL"),
        ("WAITING_APPROVAL", "RUNNING"),
        ("RUNNING", "WAITING_EXTERNAL"),
        ("WAITING_EXTERNAL", "RUNNING"),
        ("RUNNING", "AUDITING"),
        ("AUDITING", "RUNNING"),
        ("AUDITING", "DONE"),
        ("RUNNING", "HANDOFF"),
        ("RECOVERING", "HANDOFF"),
        ("AUDITING", "HANDOFF"),
        ("WAITING_APPROVAL", "HANDOFF"),
        ("WAITING_EXTERNAL", "HANDOFF"),
    }
)
TERMINAL_LIFECYCLES = frozenset({"DONE", "HANDOFF"})
LIFECYCLES = frozenset(
    {
        "DRAFT",
        *{source for source, _ in ALLOWED_TRANSITIONS},
        *{target for _, target in ALLOWED_TRANSITIONS},
    }
)
PHASE_STATUSES = frozenset(
    {"PENDING", "READY", "EXECUTING", "VERIFYING", "BLOCKED", "COMPLETE"}
)
RUNNING_STATUS_EDGES = {
    "PENDING": {"PENDING", "READY", "EXECUTING"},
    "READY": {"READY", "EXECUTING"},
    "EXECUTING": {"EXECUTING", "VERIFYING", "BLOCKED", "COMPLETE"},
    "VERIFYING": {"VERIFYING", "EXECUTING", "BLOCKED", "COMPLETE"},
    "BLOCKED": {"BLOCKED", "EXECUTING"},
    "COMPLETE": {"COMPLETE"},
}
PRE_RUN_LIFECYCLES = frozenset(
    {"COMPILED", "PLAN_REVIEWED", "PREFLIGHT_GREEN", "READY_TO_DISPATCH"}
)

EVENT_FIELDS = frozenset(
    {
        "event_id",
        "goal_id",
        "contract_sha256",
        "contract_revision",
        "state_revision",
        "state_sha256",
        "state",
        "event_type",
        "phase_id",
        "actor",
        "timestamp",
        "evidence_ids",
        "prev_event_sha256",
        "event_sha256",
    }
)
STATE_FIELDS = frozenset(
    {
        "goal_id",
        "contract_sha256",
        "contract_revision",
        "state_revision",
        "lifecycle",
        "current_phase_id",
        "phase_status",
        "blocker",
        "attempt",
        "audit_round",
        "schema_version",
    }
)
_EVENT_ID = re.compile(r"EVT-[0-9]{6}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_RFC3339_Z_SECONDS = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z"
)


class JournalCorruptionError(ValueError):
    pass


def parse_rfc3339_z_seconds(value: object) -> datetime:
    if not isinstance(value, str) or not _RFC3339_Z_SECONDS.fullmatch(value):
        raise ValueError("timestamp must be exact RFC3339 UTC second precision")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ValueError("timestamp is not a real UTC date/time") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("timestamp is not canonical")
    return parsed


def now_rfc3339_z_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def canonical_event_payload(event: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in event.items() if key != "event_sha256"}
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_event_payload(event)).hexdigest()


def canonical_event_line(event: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def canonical_state_bytes(state: dict[str, Any]) -> bytes:
    return (
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _state_hash(state: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_state_bytes(state)).hexdigest()


def read_events(
    path: str | Path,
    *,
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    event_path = Path(path)
    if not os.path.lexists(event_path):
        return []
    trusted_root = Path(root) if root is not None else event_path.parent
    data = read_regular_file_no_follow(event_path, trusted_root)
    if not data:
        return []
    if b"\r" in data or not data.endswith(b"\n"):
        raise ValueError("event journal must use canonical UTF-8 LF JSONL")
    raw_lines = data[:-1].split(b"\n")
    if any(not line for line in raw_lines):
        raise ValueError("event journal must not contain blank lines")
    events: list[dict[str, Any]] = []
    for raw_line in raw_lines:
        try:
            event = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("event journal contains malformed JSON") from exc
        if not isinstance(event, dict) or canonical_event_line(event) != raw_line + b"\n":
            raise ValueError("event journal line is not canonical JSON")
        events.append(event)
    return events


def _basic_state_errors(state: object, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(state, dict):
        return [f"{label} target state is invalid"]
    if set(state) != STATE_FIELDS:
        errors.append(f"{label} target state fields mismatch")
        return errors
    if state.get("schema_version") != "3.0":
        errors.append(f"{label} state schema mismatch")
    if not isinstance(state.get("goal_id"), str) or not state["goal_id"]:
        errors.append(f"{label} state goal id invalid")
    if not isinstance(state.get("contract_sha256"), str) or not _SHA256.fullmatch(
        state["contract_sha256"]
    ):
        errors.append(f"{label} state contract hash invalid")
    for field, minimum in (
        ("contract_revision", 1),
        ("state_revision", 1),
        ("attempt", 0),
        ("audit_round", 0),
    ):
        value = state.get(field)
        if type(value) is not int or value < minimum:
            errors.append(f"{label} state {field} invalid")
    if state.get("lifecycle") not in LIFECYCLES:
        errors.append(f"{label} state lifecycle invalid")
    if not isinstance(state.get("current_phase_id"), str) or not state[
        "current_phase_id"
    ]:
        errors.append(f"{label} current phase invalid")
    if state.get("phase_status") not in PHASE_STATUSES:
        errors.append(f"{label} phase status invalid")
    if state.get("blocker") is not None and not isinstance(state.get("blocker"), dict):
        errors.append(f"{label} blocker invalid")
    if state.get("lifecycle") in {"AUDITING", "DONE"} and (
        state.get("phase_status") != "COMPLETE" or state.get("blocker") is not None
    ):
        errors.append(f"{label} auditing/terminal state must be unblocked and complete")
    return errors


def verify_event_chain(
    events: list[dict[str, Any]],
    *,
    goal_id: str | None = None,
    contract_sha256: str | None = None,
    contract_revision: int | None = None,
    phase_ids: set[str] | None = None,
    phase_dependencies: dict[str, set[str]] | None = None,
) -> list[str]:
    """Validate hashes and all journal semantics through one fail-closed path."""

    errors: list[str] = []
    previous_hash: str | None = None
    previous_timestamp: datetime | None = None
    previous_state: dict[str, Any] | None = None
    completed_phases: set[str] = set()
    genesis_identity: tuple[object, object, object] | None = None

    for index, event in enumerate(events, 1):
        label = f"event {index}"
        if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
            errors.append(f"{label} fields mismatch")
            previous_hash = event.get("event_sha256") if isinstance(event, dict) else ""
            continue
        if event.get("event_id") != f"EVT-{index:06d}" or not _EVENT_ID.fullmatch(
            str(event.get("event_id", ""))
        ):
            errors.append(f"{label} id is not sequential")
        if event.get("prev_event_sha256") != previous_hash:
            errors.append(f"{label} prev hash mismatch")
        if event.get("event_sha256") != event_hash(event):
            errors.append(f"{label} hash mismatch")
        if not isinstance(event.get("event_sha256"), str) or not _SHA256.fullmatch(
            event["event_sha256"]
        ):
            errors.append(f"{label} event hash invalid")
        try:
            timestamp = parse_rfc3339_z_seconds(event.get("timestamp"))
            if previous_timestamp is not None and timestamp < previous_timestamp:
                errors.append(f"{label} timestamp moved backwards")
            previous_timestamp = timestamp
        except ValueError:
            errors.append(f"{label} timestamp invalid")
        if not isinstance(event.get("actor"), str) or not event["actor"].strip():
            errors.append(f"{label} actor invalid")
        evidence_ids = event.get("evidence_ids")
        if (
            not isinstance(evidence_ids, list)
            or not all(isinstance(item, str) and item for item in evidence_ids)
            or len(evidence_ids) != len(set(evidence_ids))
        ):
            errors.append(f"{label} evidence ids invalid")

        state = event.get("state")
        errors.extend(_basic_state_errors(state, label))
        if not isinstance(state, dict) or set(state) != STATE_FIELDS:
            previous_hash = event.get("event_sha256", "")
            continue
        expected_identity = {
            "goal_id": state.get("goal_id"),
            "contract_sha256": state.get("contract_sha256"),
            "contract_revision": state.get("contract_revision"),
            "state_revision": state.get("state_revision"),
            "phase_id": state.get("current_phase_id"),
        }
        if any(event.get(key) != value for key, value in expected_identity.items()):
            errors.append(f"{label} target state identity mismatch")
        if event.get("state_sha256") != _state_hash(state):
            errors.append(f"{label} target state hash mismatch")
        if not isinstance(event.get("state_sha256"), str) or not _SHA256.fullmatch(
            event["state_sha256"]
        ):
            errors.append(f"{label} target state hash invalid")

        identity = (
            state.get("goal_id"),
            state.get("contract_sha256"),
            state.get("contract_revision"),
        )
        if genesis_identity is None:
            genesis_identity = identity
        elif identity != genesis_identity:
            errors.append(f"{label} state identity changed")
        if goal_id is not None and state.get("goal_id") != goal_id:
            errors.append(f"{label} goal identity mismatch")
        if contract_sha256 is not None and state.get("contract_sha256") != contract_sha256:
            errors.append(f"{label} contract hash mismatch")
        if contract_revision is not None and state.get("contract_revision") != contract_revision:
            errors.append(f"{label} contract revision mismatch")
        phase = state.get("current_phase_id")
        if phase_ids is not None and phase not in phase_ids:
            errors.append(f"{label} phase is not declared")

        if index == 1:
            if event.get("event_type") != "state_initialized":
                errors.append("event 1 is not the unique genesis event")
            if state.get("state_revision") != 1:
                errors.append("event 1 genesis revision must be 1")
            if state.get("lifecycle") != "COMPILED":
                errors.append("event 1 genesis lifecycle must be COMPILED")
            if state.get("phase_status") != "PENDING":
                errors.append("event 1 genesis phase status must be PENDING")
            if state.get("attempt") != 0:
                errors.append("event 1 genesis attempt must be 0")
            if state.get("audit_round") != 0:
                errors.append("event 1 genesis audit round must be 0")
        elif previous_state is not None:
            expected_revision = previous_state.get("state_revision", 0) + 1
            if state.get("state_revision") != expected_revision:
                errors.append(f"{label} state revision must advance by exactly one")
            old_lifecycle = previous_state.get("lifecycle")
            new_lifecycle = state.get("lifecycle")
            if old_lifecycle in TERMINAL_LIFECYCLES:
                errors.append(f"{label} mutates terminal state")
            if old_lifecycle == new_lifecycle:
                if event.get("event_type") != "state_update":
                    errors.append(f"{label} forged same-lifecycle event type")
            else:
                if (old_lifecycle, new_lifecycle) not in ALLOWED_TRANSITIONS:
                    errors.append(f"{label} illegal lifecycle transition")
                expected_type = f"transition:{old_lifecycle}->{new_lifecycle}"
                if event.get("event_type") != expected_type:
                    errors.append(f"{label} transition event type mismatch")
            expected_audit_round = previous_state.get("audit_round", 0) + (
                1 if old_lifecycle != "AUDITING" and new_lifecycle == "AUDITING" else 0
            )
            if state.get("audit_round") != expected_audit_round:
                errors.append(f"{label} audit round edge mismatch")
            old_attempt = previous_state.get("attempt")
            if state.get("attempt") not in {old_attempt, old_attempt + 1}:
                errors.append(f"{label} attempt must remain or advance by one")
            if state.get("attempt") != old_attempt and not (
                old_lifecycle == "RUNNING" and new_lifecycle == "RUNNING"
            ):
                errors.append(f"{label} attempt may advance only inside RUNNING")
            old_phase = previous_state.get("current_phase_id")
            old_status = previous_state.get("phase_status")
            new_status = state.get("phase_status")
            if new_status == "COMPLETE" and new_lifecycle not in {
                "RUNNING",
                "AUDITING",
                "DONE",
            }:
                errors.append(f"{label} phase cannot complete before RUNNING")
            if old_phase == phase and old_status != new_status:
                if (
                    old_lifecycle in PRE_RUN_LIFECYCLES
                    and new_lifecycle in PRE_RUN_LIFECYCLES
                    and old_status == "PENDING"
                    and new_status == "READY"
                ):
                    pass
                elif new_lifecycle != "RUNNING":
                    errors.append(
                        f"{label} phase status may change only while entering or inside RUNNING"
                    )
                elif (
                    old_lifecycle == "AUDITING"
                    and old_status == "COMPLETE"
                    and new_status in {"EXECUTING", "VERIFYING"}
                ):
                    pass
                elif new_status not in RUNNING_STATUS_EDGES.get(
                    str(old_status), set()
                ):
                    errors.append(f"{label} phase status edge is illegal")
            if old_phase != phase:
                audit_remediation = (
                    old_lifecycle == "AUDITING"
                    and new_lifecycle == "RUNNING"
                    and phase in completed_phases
                    and new_status in {"EXECUTING", "VERIFYING"}
                )
                if not audit_remediation and (
                    old_lifecycle != "RUNNING" or new_lifecycle != "RUNNING"
                ):
                    errors.append(f"{label} phase may advance only inside RUNNING")
                if not audit_remediation and old_status != "COMPLETE":
                    errors.append(f"{label} previous phase is not complete")
                if not audit_remediation and new_status not in {
                    "PENDING",
                    "READY",
                    "EXECUTING",
                }:
                    errors.append(f"{label} advanced phase status is invalid")
                dependencies = (phase_dependencies or {}).get(str(phase), set())
                if not audit_remediation and not dependencies.issubset(
                    completed_phases
                ):
                    errors.append(f"{label} phase dependencies are not complete")
            if old_lifecycle == "RUNNING" and new_lifecycle == "AUDITING":
                if old_status != "COMPLETE":
                    errors.append(f"{label} current phase is not complete")
                if phase_ids is not None and not phase_ids.issubset(completed_phases):
                    errors.append(
                        f"{label} all declared phases must be complete before AUDITING"
                    )

        if state.get("phase_status") == "COMPLETE" and isinstance(phase, str):
            completed_phases.add(phase)
        previous_state = state
        previous_hash = event.get("event_sha256", "")
    return errors


def validate_event_journal(
    events: list[dict[str, Any]],
    **expected: Any,
) -> list[dict[str, Any]]:
    if not events:
        raise JournalCorruptionError("SGV-STATE-JOURNAL-CORRUPT: journal is empty")
    errors = verify_event_chain(events, **expected)
    if errors:
        raise JournalCorruptionError(
            "SGV-STATE-JOURNAL-CORRUPT: " + "; ".join(errors)
        )
    return events


def append_event(
    path: str | Path,
    *,
    state: dict[str, Any],
    event_type: str,
    actor: str = "sgctl",
    evidence_ids: list[str] | None = None,
    timestamp: str | None = None,
    phase_ids: set[str] | None = None,
    phase_dependencies: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    event_path = Path(path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    events = read_events(event_path) if os.path.lexists(event_path) else []
    if events:
        validate_event_journal(
            events,
            phase_ids=phase_ids,
            phase_dependencies=phase_dependencies,
        )
    previous = events[-1]["event_sha256"] if events else None
    target_state = dict(state)
    event = {
        "event_id": f"EVT-{len(events) + 1:06d}",
        "goal_id": target_state.get("goal_id"),
        "contract_sha256": target_state.get("contract_sha256"),
        "contract_revision": target_state.get("contract_revision"),
        "state_revision": target_state.get("state_revision"),
        "state_sha256": _state_hash(target_state),
        "state": target_state,
        "event_type": event_type,
        "phase_id": target_state.get("current_phase_id"),
        "actor": actor,
        "timestamp": timestamp or now_rfc3339_z_seconds(),
        "evidence_ids": list(evidence_ids or []),
        "prev_event_sha256": previous,
    }
    event["event_sha256"] = event_hash(event)
    validate_event_journal(
        [*events, event],
        phase_ids=phase_ids,
        phase_dependencies=phase_dependencies,
    )
    line = canonical_event_line(event)
    if not events:
        from .portable import write_bytes_atomic

        write_bytes_atomic(event_path, line, root=event_path.parent)
    else:
        append_regular_file_no_follow(event_path, event_path.parent, line)
    return event
