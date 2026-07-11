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
        "state_revision",
        "state_sha256",
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
        if event.get("prev_event_sha256") != prev:
            errors.append(f"event {idx} prev hash mismatch")
        expected = event_hash(event)
        if event.get("event_sha256") != expected:
            errors.append(f"event {idx} hash mismatch")
        prev = event.get("event_sha256", "")
    return errors


def append_event(
    path: str | Path,
    *,
    goal_id: str,
    contract_sha256: str,
    state_revision: int,
    event_type: str,
    phase_id: str | None = None,
    actor: str = "sgctl",
    evidence_ids: list[str] | None = None,
    state_sha256: str | None = None,
) -> dict[str, Any]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    events = read_events(p)
    errors = verify_event_chain(events)
    if errors:
        raise ValueError("invalid existing event chain: " + "; ".join(errors))
    prev = events[-1]["event_sha256"] if events else None
    event = {
        "event_id": f"EVT-{len(events)+1:06d}",
        "goal_id": goal_id,
        "contract_sha256": contract_sha256,
        "state_revision": state_revision,
        "state_sha256": state_sha256,
        "event_type": event_type,
        "phase_id": phase_id,
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
