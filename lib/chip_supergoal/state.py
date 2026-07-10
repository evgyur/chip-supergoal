from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from .events import append_event, read_events, verify_event_chain
from .portable import package_lock, write_utf8_lf

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

@dataclass(frozen=True)
class State:
    goal_id: str
    contract_sha256: str
    state_revision: int
    lifecycle: str
    current_phase_id: str | None
    phase_status: str | None
    blocker: dict[str, Any] | None = None
    attempt: int = 0
    audit_round: int = 0
    schema_version: str = "3.0"

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


def write_state_atomic(path: str | Path, state: State) -> None:
    content = json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_utf8_lf(path, content)


def render_state_md(state: State) -> str:
    return f"""# STATE\n\nGoal identity: `{state.goal_id}`\nLifecycle: {state.lifecycle}\nCurrent phase: {state.current_phase_id or 'none'}\nState revision: {state.state_revision}\nContract SHA-256: `{state.contract_sha256}`\nPhase status: {state.phase_status or 'none'}\nBlocker: {json.dumps(state.blocker, ensure_ascii=False, sort_keys=True) if state.blocker else 'none'}\n"""

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
        write_state_atomic(self.state_json, state)
        write_utf8_lf(self.state_md, render_state_md(state))
        append_event(self.events, goal_id=state.goal_id, contract_sha256=state.contract_sha256, state_revision=state.state_revision, event_type="state_initialized", phase_id=state.current_phase_id)

    def transition(self, to_lifecycle: str, *, expected_revision: int, phase_id: str | None = None, phase_status: str | None = None, blocker: dict[str, Any] | None = None) -> State:
        self.runtime.mkdir(parents=True, exist_ok=True)
        with package_lock(self.lock):
            current = read_state(self.state_json)
            if current.state_revision != expected_revision:
                raise ValueError("SGV-STATE-STALE-WRITER")
            new = current.transition(to_lifecycle, phase_id=phase_id, phase_status=phase_status, blocker=blocker)
            write_state_atomic(self.state_json, new)
            write_utf8_lf(self.state_md, render_state_md(new))
            append_event(self.events, goal_id=new.goal_id, contract_sha256=new.contract_sha256, state_revision=new.state_revision, event_type=f"transition:{current.lifecycle}->{new.lifecycle}", phase_id=new.current_phase_id)
            reread = read_state(self.state_json)
            if reread.state_revision != new.state_revision:
                raise ValueError("SGV-STATE-WRITE-VERIFY-FAILED")
            return reread


def validate_goal_identity(state: State, *, goal_id: str, contract_sha256: str) -> None:
    if state.goal_id != goal_id or state.contract_sha256 != contract_sha256:
        raise ValueError("SGV-STATE-CONTRACT-MISMATCH")


def recover_from_events(root: str | Path) -> State | None:
    store = StateStore(root)
    events = read_events(store.events)
    if verify_event_chain(events):
        return None
    if not events:
        return None
    try:
        state = read_state(store.state_json)
    except Exception:
        last = events[-1]
        return State(goal_id=last["goal_id"], contract_sha256=last["contract_sha256"], state_revision=last["state_revision"], lifecycle="RECOVERING", current_phase_id=last.get("phase_id"), phase_status="RECOVERED")
    if events[-1]["goal_id"] != state.goal_id or events[-1]["contract_sha256"] != state.contract_sha256:
        return None
    return state
