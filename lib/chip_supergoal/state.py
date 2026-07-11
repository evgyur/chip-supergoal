from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .events import append_event, canonical_state_bytes, read_events, verify_event_chain
from .portable import package_lock, package_operation_lock, write_bytes_atomic, write_utf8_lf

ALLOWED_TRANSITIONS = {
    ("DRAFT", "COMPILED"), ("COMPILED", "PLAN_REVIEWED"), ("PLAN_REVIEWED", "PREFLIGHT_GREEN"),
    ("PREFLIGHT_GREEN", "READY_TO_DISPATCH"), ("READY_TO_DISPATCH", "RUNNING"),
    ("RUNNING", "RECOVERING"), ("RECOVERING", "RUNNING"), ("RUNNING", "WAITING_APPROVAL"),
    ("WAITING_APPROVAL", "RUNNING"), ("RUNNING", "WAITING_EXTERNAL"), ("WAITING_EXTERNAL", "RUNNING"),
    ("RUNNING", "AUDITING"), ("AUDITING", "RUNNING"), ("AUDITING", "DONE"),
    ("RUNNING", "HANDOFF"), ("RECOVERING", "HANDOFF"), ("AUDITING", "HANDOFF"),
    ("WAITING_APPROVAL", "HANDOFF"), ("WAITING_EXTERNAL", "HANDOFF"),
}
TERMINAL = {"DONE", "HANDOFF"}
LIFECYCLES = frozenset(
    {"DRAFT", *{source for source, _ in ALLOWED_TRANSITIONS}, *{target for _, target in ALLOWED_TRANSITIONS}}
)

@dataclass(frozen=True)
class State:
    goal_id: str
    contract_sha256: str
    contract_revision: int
    state_revision: int
    lifecycle: str
    current_phase_id: str | None
    phase_status: str | None
    blocker: dict[str, Any] | None = None
    attempt: int = 0
    audit_round: int = 0
    schema_version: str = "3.0"

    def __post_init__(self) -> None:
        if self.schema_version != "3.0":
            raise ValueError("state schema_version must be 3.0")
        if not isinstance(self.goal_id, str) or not self.goal_id:
            raise ValueError("state goal_id must be a nonempty string")
        if not isinstance(self.contract_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.contract_sha256):
            raise ValueError("state contract_sha256 must be a lowercase SHA-256")
        if type(self.contract_revision) is not int or self.contract_revision < 1:
            raise ValueError("contract_revision must be a positive integer")
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise ValueError("state_revision must be a nonnegative integer")
        if self.lifecycle not in LIFECYCLES:
            raise ValueError("state lifecycle is unsupported")
        if self.current_phase_id is not None and not isinstance(self.current_phase_id, str):
            raise ValueError("current_phase_id must be a string or null")
        if self.phase_status is not None and not isinstance(self.phase_status, str):
            raise ValueError("phase_status must be a string or null")
        if self.blocker is not None and not isinstance(self.blocker, dict):
            raise ValueError("blocker must be an object or null")
        if type(self.attempt) is not int or self.attempt < 0:
            raise ValueError("attempt must be a nonnegative integer")
        if type(self.audit_round) is not int or self.audit_round < 0:
            raise ValueError("audit_round must be a nonnegative integer")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "State":
        allowed = set(cls.__dataclass_fields__)
        extra = sorted(set(data) - allowed)
        if extra:
            raise ValueError(f"unknown state fields: {', '.join(extra)}")
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    def transition(self, to_lifecycle: str, *, phase_id: str | None = None, phase_status: str | None = None, blocker: dict[str, Any] | None = None) -> "State":
        if self.lifecycle in TERMINAL:
            raise ValueError("SGV-STATE-TERMINAL-REOPEN")
        if (self.lifecycle, to_lifecycle) not in ALLOWED_TRANSITIONS:
            raise ValueError("SGV-STATE-ILLEGAL-TRANSITION")
        return State(
            goal_id=self.goal_id,
            contract_sha256=self.contract_sha256,
            contract_revision=self.contract_revision,
            state_revision=self.state_revision + 1,
            lifecycle=to_lifecycle,
            current_phase_id=phase_id if phase_id is not None else self.current_phase_id,
            phase_status=phase_status if phase_status is not None else self.phase_status,
            blocker=blocker,
            attempt=self.attempt,
            audit_round=self.audit_round + (1 if to_lifecycle == "AUDITING" else 0),
        )


def read_state(path: str | Path) -> State:
    return State.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def state_json_bytes(state: State) -> bytes:
    return canonical_state_bytes(state.to_dict())


def state_sha256(state: State) -> str:
    return hashlib.sha256(state_json_bytes(state)).hexdigest()


def write_state_atomic(path: str | Path, state: State) -> None:
    write_bytes_atomic(path, state_json_bytes(state))


def render_state_md(state: State) -> str:
    return f"""# STATE\n\nGoal identity: `{state.goal_id}`\nLifecycle: {state.lifecycle}\nCurrent phase: {state.current_phase_id or 'none'}\nState revision: {state.state_revision}\nContract revision: {state.contract_revision}\nContract SHA-256: `{state.contract_sha256}`\nPhase status: {state.phase_status or 'none'}\nBlocker: {json.dumps(state.blocker, ensure_ascii=False, sort_keys=True) if state.blocker else 'none'}\n"""

class StateStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.runtime = self.root / "runtime"
        self.state_json = self.runtime / "STATE.json"
        self.state_md = self.root / "STATE.md"
        self.events = self.runtime / "events.jsonl"
        self.lock = self.runtime / "state.lock"

    def initialize(self, state: State) -> None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        append_event(
            self.events,
            state=state.to_dict(),
            event_type="state_initialized",
        )
        write_state_atomic(self.state_json, state)
        write_utf8_lf(self.state_md, render_state_md(state))

    def transition(self, to_lifecycle: str, *, expected_revision: int, phase_id: str | None = None, phase_status: str | None = None, blocker: dict[str, Any] | None = None) -> State:
        self.runtime.mkdir(parents=True, exist_ok=True)
        # Lock order is package operation first, then the runtime projection lock.
        # The compiler uses the same external lock for its final check and swap.
        with package_operation_lock(self.root):
            with package_lock(self.lock):
                current = read_state(self.state_json)
                if current.state_revision != expected_revision:
                    raise ValueError("SGV-STATE-STALE-WRITER")
                new = current.transition(to_lifecycle, phase_id=phase_id, phase_status=phase_status, blocker=blocker)
                append_event(
                    self.events,
                    state=new.to_dict(),
                    event_type=f"transition:{current.lifecycle}->{new.lifecycle}",
                )
                write_state_atomic(self.state_json, new)
                write_utf8_lf(self.state_md, render_state_md(new))
                reread = read_state(self.state_json)
                if reread.state_revision != new.state_revision:
                    raise ValueError("SGV-STATE-WRITE-VERIFY-FAILED")
                return reread


def validate_goal_identity(
    state: State,
    *,
    goal_id: str,
    contract_sha256: str,
    contract_revision: int,
) -> None:
    if (
        state.goal_id != goal_id
        or state.contract_sha256 != contract_sha256
        or state.contract_revision != contract_revision
    ):
        raise ValueError("SGV-STATE-CONTRACT-MISMATCH")


def recover_from_events(root: str | Path) -> State | None:
    store = StateStore(root)
    store.runtime.mkdir(parents=True, exist_ok=True)
    with package_operation_lock(store.root):
        with package_lock(store.lock):
            events = read_events(store.events)
            if not events or verify_event_chain(events):
                return None
            try:
                recovered = State.from_dict(events[-1]["state"])
            except Exception:
                return None
            write_state_atomic(store.state_json, recovered)
            write_utf8_lf(store.state_md, render_state_md(recovered))
            return recovered
