from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .events import (
    ALLOWED_TRANSITIONS,
    LIFECYCLES,
    PHASE_STATUSES,
    PRE_RUN_LIFECYCLES,
    TERMINAL_LIFECYCLES,
    JournalCorruptionError,
    append_event,
    canonical_genesis_phase_id,
    canonical_json_value_bytes,
    canonical_state_bytes,
    read_events,
    strict_json_loads,
    validate_event_journal,
)
from .model import canonical_json, contract_from_dict
from .portable import (
    package_lock,
    package_operation_lock,
    read_regular_file_no_follow,
    unlink_regular_file_no_follow,
    verify_sealed_artifact,
    write_bytes_atomic,
    write_utf8_lf,
)


TERMINAL = TERMINAL_LIFECYCLES
_UNSET = object()


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
        if not isinstance(self.contract_sha256, str) or not re.fullmatch(
            r"[a-f0-9]{64}", self.contract_sha256
        ):
            raise ValueError("state contract_sha256 must be a lowercase SHA-256")
        if type(self.contract_revision) is not int or self.contract_revision < 1:
            raise ValueError("contract_revision must be a positive integer")
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise ValueError("state_revision must be a nonnegative integer")
        if self.lifecycle not in LIFECYCLES:
            raise ValueError("state lifecycle is unsupported")
        if self.current_phase_id is not None and (
            not isinstance(self.current_phase_id, str) or not self.current_phase_id
        ):
            raise ValueError("current_phase_id must be a nonempty string or null")
        if self.phase_status is not None and self.phase_status not in PHASE_STATUSES:
            raise ValueError("phase_status must be a declared status or null")
        if self.blocker is not None and not isinstance(self.blocker, dict):
            raise ValueError("blocker must be an object or null")
        if type(self.attempt) is not int or self.attempt < 0:
            raise ValueError("attempt must be a nonnegative integer")
        if type(self.audit_round) is not int or self.audit_round < 0:
            raise ValueError("audit_round must be a nonnegative integer")
        if self.lifecycle in {"AUDITING", "DONE"} and (
            self.phase_status != "COMPLETE" or self.blocker is not None
        ):
            raise ValueError(
                "SGV-STATE-ILLEGAL-UPDATE: phase must be complete and unblocked in AUDITING or DONE"
            )
        try:
            canonical_json_value_bytes(self.to_dict())
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "SGV-STATE-ILLEGAL-UPDATE: state must contain strict JSON values"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "State":
        if not isinstance(data, dict):
            raise ValueError("state must be an object")
        allowed = set(cls.__dataclass_fields__)
        extra = sorted(set(data) - allowed)
        missing = sorted(allowed - set(data))
        if extra:
            raise ValueError(f"unknown state fields: {', '.join(extra)}")
        if missing:
            raise ValueError(f"missing state fields: {', '.join(missing)}")
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def transition(
        self,
        to_lifecycle: str,
        *,
        phase_id: str | None = None,
        phase_status: str | None = None,
        blocker: dict[str, Any] | None = None,
    ) -> "State":
        if self.lifecycle in TERMINAL:
            raise ValueError("SGV-STATE-TERMINAL-REOPEN")
        if (self.lifecycle, to_lifecycle) not in ALLOWED_TRANSITIONS:
            raise ValueError("SGV-STATE-ILLEGAL-TRANSITION")
        target_phase = phase_id if phase_id is not None else self.current_phase_id
        target_status = phase_status if phase_status is not None else self.phase_status
        pre_run_ready_edge = (
            self.lifecycle in PRE_RUN_LIFECYCLES
            and to_lifecycle in PRE_RUN_LIFECYCLES
            and self.phase_status == "PENDING"
            and target_status == "READY"
        )
        audit_remediation_edge = (
            self.lifecycle == "AUDITING"
            and to_lifecycle == "RUNNING"
            and target_status in {"EXECUTING", "VERIFYING"}
        )
        if (target_phase != self.current_phase_id and not audit_remediation_edge) or (
            target_status != self.phase_status
            and to_lifecycle != "RUNNING"
            and not pre_run_ready_edge
        ):
            raise ValueError("SGV-STATE-ILLEGAL-TRANSITION")
        return State(
            goal_id=self.goal_id,
            contract_sha256=self.contract_sha256,
            contract_revision=self.contract_revision,
            state_revision=self.state_revision + 1,
            lifecycle=to_lifecycle,
            current_phase_id=target_phase,
            phase_status=target_status,
            blocker=blocker,
            attempt=self.attempt,
            audit_round=self.audit_round
            + (
                1
                if self.lifecycle != "AUDITING" and to_lifecycle == "AUDITING"
                else 0
            ),
        )

    def update(
        self,
        *,
        phase_id: str | None | object = _UNSET,
        phase_status: str | None | object = _UNSET,
        blocker: dict[str, Any] | None | object = _UNSET,
        attempt: int | object = _UNSET,
    ) -> "State":
        if self.lifecycle in TERMINAL:
            raise ValueError("SGV-STATE-TERMINAL-REOPEN")
        new_attempt = self.attempt if attempt is _UNSET else attempt
        if type(new_attempt) is not int or new_attempt not in {
            self.attempt,
            self.attempt + 1,
        }:
            raise ValueError("SGV-STATE-ILLEGAL-UPDATE")
        target_phase = self.current_phase_id if phase_id is _UNSET else phase_id
        target_status = self.phase_status if phase_status is _UNSET else phase_status
        pre_run_ready_edge = (
            self.lifecycle in PRE_RUN_LIFECYCLES
            and self.phase_status == "PENDING"
            and target_status == "READY"
            and target_phase == self.current_phase_id
            and new_attempt == self.attempt
        )
        if self.lifecycle != "RUNNING" and not pre_run_ready_edge and (
            target_phase != self.current_phase_id
            or target_status != self.phase_status
            or new_attempt != self.attempt
        ):
            raise ValueError("SGV-STATE-ILLEGAL-UPDATE")
        target_blocker = self.blocker if blocker is _UNSET else blocker
        current_semantic = self.to_dict()
        current_semantic.pop("state_revision")
        target_semantic = {
            **current_semantic,
            "current_phase_id": target_phase,
            "phase_status": target_status,
            "blocker": target_blocker,
            "attempt": new_attempt,
        }
        try:
            semantic_noop = canonical_json_value_bytes(
                target_semantic
            ) == canonical_json_value_bytes(current_semantic)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "SGV-STATE-ILLEGAL-UPDATE: state must contain strict JSON values"
            ) from exc
        if semantic_noop:
            raise ValueError("SGV-STATE-ILLEGAL-UPDATE: semantic no-op")
        return State(
            goal_id=self.goal_id,
            contract_sha256=self.contract_sha256,
            contract_revision=self.contract_revision,
            state_revision=self.state_revision + 1,
            lifecycle=self.lifecycle,
            current_phase_id=target_phase,
            phase_status=target_status,
            blocker=target_blocker,
            attempt=new_attempt,
            audit_round=self.audit_round,
        )


@dataclass(frozen=True)
class RecoveryResult:
    status: str
    state: State

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "state": self.state.to_dict()}


def read_state(path: str | Path, *, root: str | Path | None = None) -> State:
    state_path = Path(path)
    trusted_root = Path(root) if root is not None else state_path.parent
    raw = read_regular_file_no_follow(state_path, trusted_root)
    try:
        data = strict_json_loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("state JSON is malformed") from exc
    state = State.from_dict(data)
    if raw != state_json_bytes(state):
        raise ValueError("state JSON bytes are not canonical")
    return state


def state_json_bytes(state: State) -> bytes:
    return canonical_state_bytes(state.to_dict())


def state_sha256(state: State) -> str:
    return hashlib.sha256(state_json_bytes(state)).hexdigest()


def write_state_atomic(
    path: str | Path,
    state: State,
    *,
    root: str | Path | None = None,
) -> None:
    write_bytes_atomic(path, state_json_bytes(state), root=root)


def render_state_md(state: State) -> str:
    return f"""# STATE

Schema version: {state.schema_version}
Goal identity: `{state.goal_id}`
Lifecycle: {state.lifecycle}
Current phase: {state.current_phase_id or 'none'}
State revision: {state.state_revision}
Contract revision: {state.contract_revision}
Contract SHA-256: `{state.contract_sha256}`
Phase status: {state.phase_status or 'none'}
Attempt: {state.attempt}
Audit round: {state.audit_round}
Blocker: {json.dumps(state.blocker, ensure_ascii=False, sort_keys=True) if state.blocker else 'none'}
"""


def _terminal_path(root: Path) -> Path:
    return root / "reports" / "terminal-record.txt"


def assert_runtime_mutable(root: str | Path) -> None:
    if os.path.lexists(_terminal_path(Path(root))):
        raise ValueError("SGV-STATE-TERMINAL-FROZEN")


def _invalidate_derived_audit(root: Path) -> None:
    for relative in ("reports/final-audit.json", "reports/final-audit.md"):
        path = root / relative
        if not os.path.lexists(path):
            continue
        try:
            unlink_regular_file_no_follow(path, root)
        except Exception as exc:
            raise ValueError("SGV-AUDIT-REPORT-INVALID") from exc


class StateStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.runtime = self.root / "runtime"
        self.state_json = self.runtime / "STATE.json"
        self.state_md = self.root / "STATE.md"
        self.events = self.runtime / "events.jsonl"
        self.lock = self.runtime / "state.lock"

    def _contract_context(
        self,
        *,
        require_sealed: bool = True,
    ) -> tuple[
        str | None,
        str | None,
        int | None,
        set[str] | None,
        dict[str, set[str]] | None,
        dict[str, int] | None,
    ]:
        contract_path = self.root / "CONTRACT.json"
        if not os.path.lexists(contract_path):
            if require_sealed and any(
                os.path.lexists(self.root / marker)
                for marker in (
                    "MANIFEST.json",
                    "THINKING.md",
                    "PROTOCOL.md",
                    "LAUNCH_GOAL.md",
                )
            ):
                raise ValueError("SGV-STATE-CONTRACT-MISMATCH")
            return None, None, None, None, None, None
        raw = read_regular_file_no_follow(contract_path, self.root)
        sealed = verify_sealed_artifact(self.root, "CONTRACT.json", data=raw)
        if require_sealed and not sealed:
            raise ValueError("SGV-PACKAGE-MISSING-MANIFEST")
        try:
            contract = contract_from_dict(json.loads(raw), strict=True)
        except Exception as exc:
            raise ValueError("SGV-STATE-CONTRACT-MISMATCH") from exc
        canonical = canonical_json(contract).encode("utf-8")
        if raw != canonical:
            raise ValueError("SGV-STATE-CONTRACT-MISMATCH")
        digest = hashlib.sha256(canonical).hexdigest()
        phase_ids = {phase.id for phase in contract.phases}
        dependencies = {
            phase.id: set(phase.depends_on) for phase in contract.phases
        }
        ordinals = {phase.id: phase.ordinal for phase in contract.phases}
        return (
            contract.goal.id,
            digest,
            contract.contract_revision,
            phase_ids,
            dependencies,
            ordinals,
        )

    def _validated_events(self) -> list[dict[str, Any]]:
        goal_id, digest, revision, phase_ids, dependencies, ordinals = (
            self._contract_context()
        )
        try:
            events = read_events(self.events, root=self.root)
            return validate_event_journal(
                events,
                goal_id=goal_id,
                contract_sha256=digest,
                contract_revision=revision,
                phase_ids=phase_ids,
                phase_dependencies=dependencies,
                phase_ordinals=ordinals,
            )
        except JournalCorruptionError:
            raise
        except Exception as exc:
            raise JournalCorruptionError(
                f"SGV-STATE-JOURNAL-CORRUPT: {exc}"
            ) from exc

    def _assert_projections_current(self, state: State) -> None:
        try:
            projected = read_state(self.state_json, root=self.root)
            markdown = read_regular_file_no_follow(self.state_md, self.root)
        except Exception as exc:
            raise ValueError("SGV-STATE-RECOVERY-REQUIRED") from exc
        if (
            state_json_bytes(projected) != state_json_bytes(state)
            or markdown != render_state_md(state).encode("utf-8")
        ):
            raise ValueError("SGV-STATE-RECOVERY-REQUIRED")

    def _assert_lock_safe(self) -> None:
        try:
            if not os.path.lexists(self.lock):
                write_bytes_atomic(self.lock, b"\0", root=self.root)
            content = read_regular_file_no_follow(self.lock, self.root)
        except Exception as exc:
            raise ValueError(
                "SGV-PACKAGE-MUTABLE-MALFORMED: runtime/state.lock is unsafe"
            ) from exc
        if content != b"\0":
            raise ValueError(
                "SGV-PACKAGE-MUTABLE-MALFORMED: runtime/state.lock is malformed"
            )

    def initialize(self, state: State) -> None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        if state.state_revision != 1 or state.lifecycle != "COMPILED":
            raise ValueError("SGV-STATE-GENESIS-INVALID")
        if state.current_phase_id is None:
            raise ValueError("SGV-STATE-GENESIS-INVALID")
        if any(
            os.path.lexists(path)
            for path in (self.events, self.state_json, self.state_md)
        ):
            raise ValueError("SGV-STATE-GENESIS-INVALID")
        goal_id, digest, revision, phase_ids, dependencies, ordinals = (
            self._contract_context(require_sealed=False)
        )
        canonical_genesis = canonical_genesis_phase_id(
            phase_ids, dependencies, ordinals
        )
        if phase_ids is not None and (
            canonical_genesis is None
            or state.current_phase_id != canonical_genesis
        ):
            raise ValueError("SGV-STATE-GENESIS-INVALID")
        validate_goal_identity(
            state,
            goal_id=goal_id or state.goal_id,
            contract_sha256=digest or state.contract_sha256,
            contract_revision=revision or state.contract_revision,
        )
        append_event(
            self.events,
            state=state.to_dict(),
            event_type="state_initialized",
            phase_ids=phase_ids,
            phase_dependencies=dependencies,
            phase_ordinals=ordinals,
        )
        write_state_atomic(self.state_json, state, root=self.root)
        write_utf8_lf(self.state_md, render_state_md(state), root=self.root)

    def _write_transition_locked(self, current: State, target: State, event_type: str) -> State:
        _, _, _, phase_ids, dependencies, ordinals = self._contract_context()
        append_event(
            self.events,
            state=target.to_dict(),
            event_type=event_type,
            phase_ids=phase_ids,
            phase_dependencies=dependencies,
            phase_ordinals=ordinals,
        )
        write_state_atomic(self.state_json, target, root=self.root)
        write_utf8_lf(self.state_md, render_state_md(target), root=self.root)
        reread = read_state(self.state_json, root=self.root)
        if state_json_bytes(reread) != state_json_bytes(target):
            raise ValueError("SGV-STATE-WRITE-VERIFY-FAILED")
        return reread

    def transition(
        self,
        to_lifecycle: str,
        *,
        expected_revision: int,
        phase_id: str | None = None,
        phase_status: str | None = None,
        blocker: dict[str, Any] | None = None,
    ) -> State:
        with package_operation_lock(self.root):
            self._assert_lock_safe()
            with package_lock(self.lock, root=self.root):
                assert_runtime_mutable(self.root)
                events = self._validated_events()
                current = State.from_dict(events[-1]["state"])
                self._assert_projections_current(current)
                if current.state_revision != expected_revision:
                    raise ValueError("SGV-STATE-STALE-WRITER")
                target = current.transition(
                    to_lifecycle,
                    phase_id=phase_id,
                    phase_status=phase_status,
                    blocker=blocker,
                )
                if to_lifecycle == "DONE":
                    from .audit import guard_done_transition

                    guard_done_transition(self.root, current)
                else:
                    _invalidate_derived_audit(self.root)
                written = self._write_transition_locked(
                    current,
                    target,
                    f"transition:{current.lifecycle}->{target.lifecycle}",
                )
                if to_lifecycle == "DONE":
                    from .audit import write_done_audit

                    write_done_audit(self.root)
                return written

    def update(
        self,
        *,
        expected_revision: int,
        phase_id: str | None | object = _UNSET,
        phase_status: str | None | object = _UNSET,
        blocker: dict[str, Any] | None | object = _UNSET,
        attempt: int | object = _UNSET,
    ) -> State:
        with package_operation_lock(self.root):
            self._assert_lock_safe()
            with package_lock(self.lock, root=self.root):
                assert_runtime_mutable(self.root)
                events = self._validated_events()
                current = State.from_dict(events[-1]["state"])
                self._assert_projections_current(current)
                if current.state_revision != expected_revision:
                    raise ValueError("SGV-STATE-STALE-WRITER")
                target = current.update(
                    phase_id=phase_id,
                    phase_status=phase_status,
                    blocker=blocker,
                    attempt=attempt,
                )
                _invalidate_derived_audit(self.root)
                written = self._write_transition_locked(current, target, "state_update")
                return written


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


def recover_from_events(root: str | Path) -> RecoveryResult:
    store = StateStore(root)
    with package_operation_lock(store.root):
        store._assert_lock_safe()
        with package_lock(store.lock, root=store.root):
            try:
                events = store._validated_events()
                recovered = State.from_dict(events[-1]["state"])
            except JournalCorruptionError:
                raise
            except Exception as exc:
                raise JournalCorruptionError(
                    f"SGV-STATE-JOURNAL-CORRUPT: {exc}"
                ) from exc
            state_matches = False
            markdown_matches = False
            try:
                state_matches = state_json_bytes(
                    read_state(store.state_json, root=store.root)
                ) == state_json_bytes(recovered)
            except Exception:
                pass
            try:
                markdown_matches = (
                    read_regular_file_no_follow(store.state_md, store.root)
                    == render_state_md(recovered).encode("utf-8")
                )
            except Exception:
                pass
            if state_matches and markdown_matches:
                return RecoveryResult("in_sync", recovered)
            assert_runtime_mutable(store.root)
            write_state_atomic(store.state_json, recovered, root=store.root)
            write_utf8_lf(
                store.state_md, render_state_md(recovered), root=store.root
            )
            return RecoveryResult("recovered", recovered)
