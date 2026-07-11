from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from .audit import (
    audit_json_bytes,
    read_final_audit,
    recompute_package_audit,
    terminal_markers_allowed,
)
from .portable import (
    assert_no_pending_delivery_reservations,
    package_lock,
    package_operation_lock,
    read_regular_file_no_follow,
    write_bytes_atomic,
)
from .state import State, StateStore


_GOAL_ID = re.compile(r"[^\s=]+")


class TerminalRecordError(ValueError):
    pass


def _validated_audit(state: State, audit_bytes: bytes):
    from .audit import AuditReport

    try:
        value = json.loads(audit_bytes)
        report = AuditReport.from_dict(value)
    except Exception as exc:
        raise TerminalRecordError("SGV-TERMINAL-AUDIT-MISMATCH") from exc
    if audit_bytes != audit_json_bytes(report):
        raise TerminalRecordError("SGV-TERMINAL-AUDIT-MISMATCH")
    if not terminal_markers_allowed(state, report):
        raise TerminalRecordError("SGV-TERMINAL-AUDIT-MISMATCH")
    return report


def render_terminal_record(state: State, audit_bytes: bytes) -> bytes:
    if state.lifecycle != "DONE" or not _GOAL_ID.fullmatch(state.goal_id):
        raise TerminalRecordError("SGV-TERMINAL-STATE-MISMATCH")
    _validated_audit(state, audit_bytes)
    audit_sha256 = hashlib.sha256(audit_bytes).hexdigest()
    return (
        f"SUPERGOAL_TERMINAL v1 goal={state.goal_id} "
        f"contract_sha256={state.contract_sha256} "
        f"contract_revision={state.contract_revision} "
        f"state_revision={state.state_revision} "
        f"audit_sha256={audit_sha256}\n"
        "AUDIT_COMPLETE\n"
        "SUPERGOAL_RUN_COMPLETE\n"
        "Goal complete: yes\n"
        "END_SUPERGOAL_TERMINAL\n"
    ).encode("utf-8")


def validate_terminal_record(
    data: bytes,
    *,
    state: State,
    audit_bytes: bytes,
) -> None:
    if not isinstance(data, bytes):
        raise TerminalRecordError("SGV-TERMINAL-GRAMMAR")
    if data.startswith(b"\xef\xbb\xbf") or b"\r" in data:
        raise TerminalRecordError("SGV-TERMINAL-GRAMMAR")
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise TerminalRecordError("SGV-TERMINAL-GRAMMAR") from exc
    expected = render_terminal_record(state, audit_bytes)
    if data != expected:
        raise TerminalRecordError("SGV-TERMINAL-GRAMMAR")


def _load_current_state(root: Path) -> tuple[StateStore, State]:
    store = StateStore(root)
    events = store._validated_events()
    state = State.from_dict(events[-1]["state"])
    store._assert_projections_current(state)
    return store, state


def validate_terminal_package(root: str | Path) -> bytes:
    package_root = Path(root)
    from .archive import assert_no_archive_recovery_required

    assert_no_archive_recovery_required(package_root)
    assert_no_pending_delivery_reservations(package_root)
    _, state = _load_current_state(package_root)
    stored_report = read_final_audit(package_root)
    recomputed = recompute_package_audit(package_root)
    if audit_json_bytes(stored_report) != audit_json_bytes(recomputed):
        raise TerminalRecordError("SGV-TERMINAL-AUDIT-MISMATCH")
    audit_bytes = audit_json_bytes(stored_report)
    record = read_regular_file_no_follow(
        package_root / "reports/terminal-record.txt", package_root
    )
    validate_terminal_record(record, state=state, audit_bytes=audit_bytes)
    return record


def finalize_package(root: str | Path) -> bytes:
    package_root = Path(root)
    store = StateStore(package_root)
    with package_operation_lock(package_root):
        from .archive import assert_no_archive_recovery_required

        assert_no_archive_recovery_required(package_root)
        assert_no_pending_delivery_reservations(package_root)
        store._assert_lock_safe()
        with package_lock(store.lock, root=package_root):
            _, state = _load_current_state(package_root)
            try:
                report = read_final_audit(package_root)
            except (OSError, ValueError) as exc:
                raise TerminalRecordError("SGV-TERMINAL-AUDIT-MISMATCH") from exc
            recomputed = recompute_package_audit(package_root)
            if audit_json_bytes(report) != audit_json_bytes(recomputed):
                raise TerminalRecordError("SGV-TERMINAL-AUDIT-MISMATCH")
            audit_bytes = audit_json_bytes(report)
            record = render_terminal_record(state, audit_bytes)
            path = package_root / "reports/terminal-record.txt"
            if os.path.lexists(path):
                existing = read_regular_file_no_follow(path, package_root)
                validate_terminal_record(
                    existing, state=state, audit_bytes=audit_bytes
                )
                return existing
            write_bytes_atomic(path, record, root=package_root)
            written = read_regular_file_no_follow(path, package_root)
            validate_terminal_record(written, state=state, audit_bytes=audit_bytes)
            return written
