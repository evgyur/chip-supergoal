from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ZERO_HASH = "0" * 64
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


def canonical_event_payload(event: dict[str, Any]) -> bytes:
    payload = {k: v for k, v in event.items() if k != "event_sha256"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_event_payload(event)).hexdigest()


def canonical_state_bytes(state: dict[str, Any]) -> bytes:
    return (
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _state_hash(state: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_state_bytes(state)).hexdigest()


def read_events(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    events = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def verify_event_chain(events: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    prev: str | None = None
    for idx, event in enumerate(events, 1):
        if set(event) != EVENT_FIELDS:
            errors.append(f"event {idx} fields mismatch")
            continue
        if event.get("prev_event_sha256") != prev:
            errors.append(f"event {idx} prev hash mismatch")
        expected = event_hash(event)
        if event.get("event_sha256") != expected:
            errors.append(f"event {idx} hash mismatch")
        state = event.get("state")
        if not isinstance(state, dict):
            errors.append(f"event {idx} target state is invalid")
        else:
            if event.get("state_sha256") != _state_hash(state):
                errors.append(f"event {idx} target state hash mismatch")
            expected_identity = {
                "goal_id": state.get("goal_id"),
                "contract_sha256": state.get("contract_sha256"),
                "contract_revision": state.get("contract_revision"),
                "state_revision": state.get("state_revision"),
                "phase_id": state.get("current_phase_id"),
            }
            if any(event.get(key) != value for key, value in expected_identity.items()):
                errors.append(f"event {idx} target state identity mismatch")
        prev = event.get("event_sha256", "")
    return errors


def append_event(
    path: str | Path,
    *,
    state: dict[str, Any],
    event_type: str,
    actor: str = "sgctl",
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    events = read_events(p)
    errors = verify_event_chain(events)
    if errors:
        raise ValueError("invalid existing event chain: " + "; ".join(errors))
    prev = events[-1]["event_sha256"] if events else None
    target_state = dict(state)
    event = {
        "event_id": f"EVT-{len(events)+1:06d}",
        "goal_id": target_state.get("goal_id"),
        "contract_sha256": target_state.get("contract_sha256"),
        "contract_revision": target_state.get("contract_revision"),
        "state_revision": target_state.get("state_revision"),
        "state_sha256": _state_hash(target_state),
        "state": target_state,
        "event_type": event_type,
        "phase_id": target_state.get("current_phase_id"),
        "actor": actor,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "evidence_ids": evidence_ids or [],
        "prev_event_sha256": prev,
    }
    event["event_sha256"] = event_hash(event)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return event
