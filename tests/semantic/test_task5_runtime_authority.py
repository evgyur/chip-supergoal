import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import audit_contract
from chip_supergoal.events import canonical_state_bytes, event_hash, read_events, verify_event_chain
from chip_supergoal.evidence import EvidenceRecord
from chip_supergoal.model import contract_from_dict, load_contract
from chip_supergoal.state import State, StateStore, recover_from_events, render_state_md


DIGEST = "a" * 64


def _rehash(event):
    event["state_sha256"] = hashlib.sha256(
        canonical_state_bytes(event["state"])
    ).hexdigest()
    event["event_sha256"] = event_hash(event)


class JournalAuthorityRegressionTest(unittest.TestCase):
    def _two_event_journal(self, root: Path):
        store = StateStore(root)
        store.initialize(
            State(
                goal_id="sg-20260625-state-test",
                contract_sha256=DIGEST,
                contract_revision=1,
                state_revision=1,
                lifecycle="COMPILED",
                current_phase_id="P01",
                phase_status="PENDING",
            )
        )
        store.transition("PLAN_REVIEWED", expected_revision=1)
        return store, read_events(store.events)

    def test_rehashed_illegal_transition_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _, events = self._two_event_journal(Path(td))
            events[1]["state"]["lifecycle"] = "DONE"
            events[1]["event_type"] = "transition:COMPILED->DONE"
            _rehash(events[1])
            self.assertTrue(verify_event_chain(events))

    def test_equal_skipped_revision_and_forged_event_type_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _, events = self._two_event_journal(Path(td))
            cases = {
                "equal revision": ("state_revision", 1),
                "skipped revision": ("state_revision", 3),
                "forged event type": ("event_type", "transition:RUNNING->DONE"),
            }
            for label, (field, value) in cases.items():
                with self.subTest(label=label):
                    mutated = json.loads(json.dumps(events))
                    mutated[1][field] = value
                    if field == "state_revision":
                        mutated[1]["state"]["state_revision"] = value
                    _rehash(mutated[1])
                    self.assertTrue(verify_event_chain(mutated))

    def test_recovery_raises_on_semantically_corrupt_but_rehashed_journal(self):
        with tempfile.TemporaryDirectory() as td:
            store, events = self._two_event_journal(Path(td))
            events[1]["state"]["lifecycle"] = "DONE"
            events[1]["event_type"] = "transition:COMPILED->DONE"
            _rehash(events[1])
            store.events.write_bytes(
                b"".join(
                    json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    + b"\n"
                    for item in events
                )
            )
            with self.assertRaisesRegex(ValueError, "SGV-STATE-JOURNAL-CORRUPT"):
                recover_from_events(td)

    def test_event_timestamp_requires_exact_real_rfc3339_z_seconds(self):
        with tempfile.TemporaryDirectory() as td:
            _, events = self._two_event_journal(Path(td))
            for timestamp in (
                "2026-07-11T00:00:00.1Z",
                "2026-07-11T00:00:00+00:00",
                "2026-02-31T00:00:00Z",
                "2000-01-01T00:00:00Z",
            ):
                with self.subTest(timestamp=timestamp):
                    mutated = json.loads(json.dumps(events))
                    mutated[1]["timestamp"] = timestamp
                    _rehash(mutated[1])
                    self.assertTrue(verify_event_chain(mutated))

    def test_state_projection_includes_all_runtime_counters(self):
        state = State(
            goal_id="sg-20260625-state-test",
            contract_sha256=DIGEST,
            contract_revision=3,
            state_revision=7,
            lifecycle="RUNNING",
            current_phase_id="P02",
            phase_status="EXECUTING",
            attempt=4,
            audit_round=2,
        )
        projection = render_state_md(state)
        for expected in (
            "Schema version: 3.0",
            "State revision: 7",
            "Attempt: 4",
            "Audit round: 2",
        ):
            self.assertIn(expected, projection)

    def test_same_lifecycle_update_is_journalled(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.initialize(
                State(
                    goal_id="sg-20260625-state-test",
                    contract_sha256=DIGEST,
                    contract_revision=1,
                    state_revision=1,
                    lifecycle="COMPILED",
                    current_phase_id="P01",
                    phase_status="PENDING",
                )
            )
            revision = 1
            for lifecycle in (
                "PLAN_REVIEWED",
                "PREFLIGHT_GREEN",
                "READY_TO_DISPATCH",
                "RUNNING",
            ):
                state = store.transition(
                    lifecycle,
                    expected_revision=revision,
                    phase_status="EXECUTING" if lifecycle == "RUNNING" else None,
                )
                revision = state.state_revision
            updated = store.update(
                expected_revision=revision,
                phase_status="VERIFYING",
                attempt=1,
            )
            self.assertEqual(updated.state_revision, revision + 1)
            self.assertEqual(updated.lifecycle, "RUNNING")
            self.assertEqual(updated.attempt, 1)
            self.assertEqual(read_events(store.events)[-1]["event_type"], "state_update")

    def test_json_type_change_is_not_misclassified_as_semantic_noop(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.initialize(
                State(
                    goal_id="sg-20260625-state-test",
                    contract_sha256=DIGEST,
                    contract_revision=1,
                    state_revision=1,
                    lifecycle="COMPILED",
                    current_phase_id="P01",
                    phase_status="PENDING",
                )
            )
            revision = 1
            for lifecycle in (
                "PLAN_REVIEWED",
                "PREFLIGHT_GREEN",
                "READY_TO_DISPATCH",
                "RUNNING",
            ):
                state = store.transition(
                    lifecycle,
                    expected_revision=revision,
                    phase_status="EXECUTING" if lifecycle == "RUNNING" else None,
                )
                revision = state.state_revision
            numbered = store.update(
                expected_revision=revision,
                blocker={"retryable": 1},
            )
            boolean = store.update(
                expected_revision=numbered.state_revision,
                blocker={"retryable": True},
            )
            self.assertIs(boolean.blocker["retryable"], True)
            self.assertEqual(verify_event_chain(read_events(store.events)), [])

    def test_nonfinite_blocker_is_rejected_without_committing_journal(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.initialize(
                State(
                    goal_id="sg-20260625-state-test",
                    contract_sha256=DIGEST,
                    contract_revision=1,
                    state_revision=1,
                    lifecycle="COMPILED",
                    current_phase_id="P01",
                    phase_status="PENDING",
                )
            )
            before_events = store.events.read_bytes()
            before_state = store.state_json.read_bytes()
            for label, value in (
                ("NaN", float("nan")),
                ("positive infinity", float("inf")),
                ("negative infinity", float("-inf")),
            ):
                with self.subTest(label=label), self.assertRaises(ValueError):
                    store.update(
                        expected_revision=1,
                        blocker={"value": value},
                    )
                self.assertEqual(store.events.read_bytes(), before_events)
                self.assertEqual(store.state_json.read_bytes(), before_state)


class EvidenceAuditAuthorityRegressionTest(unittest.TestCase):
    def contract(self):
        return load_contract(ROOT / "examples/brownfield-feature/CONTRACT.json")

    def test_wrong_goal_revision_command_and_exit_are_corruption(self):
        contract = self.contract()
        bad = EvidenceRecord.pass_record(
            evidence_id="EVD-000001",
            goal_id="wrong-goal",
            contract_sha256=DIGEST,
            contract_revision=999,
            phase_id="P01",
            criterion_id="P01-C01",
            command="false",
            exit_code=17,
            assertion="test passes",
        )
        report = audit_contract(contract, [bad])
        self.assertFalse(report.can_complete)
        self.assertIn("AUDIT_CORRUPTION", {issue.issue_type for issue in report.issues})

    def test_evidence_record_rejects_unknown_fields_and_requires_contract_hash(self):
        payload = {
            "evidence_id": "EVD-000001",
            "goal_id": "sg-20260625-state-test",
            "contract_sha256": DIGEST,
            "contract_revision": 1,
            "phase_id": "P01",
            "criterion_id": "P01-C01",
            "type": "command_result",
            "producer": "test",
            "captured_at": "2026-07-11T00:00:00Z",
            "fresh_until": "audit_end",
            "replayable": True,
            "result": "pass",
            "redaction": "passed",
            "command": "python -m unittest",
            "exit_code": 0,
            "unexpected": True,
        }
        with self.assertRaisesRegex(ValueError, "unknown evidence fields"):
            EvidenceRecord.from_dict(payload)
        payload.pop("unexpected")
        record = EvidenceRecord.from_dict(payload)
        self.assertEqual(record.contract_sha256, DIGEST)

    def test_verifier_and_evidence_assertion_exit_types_are_exact(self):
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["phases"][0]["criteria"][0]["verifier"][
            "expected_assertion"
        ] = {"structured": "forged"}
        with self.assertRaisesRegex(ValueError, "expected_assertion"):
            contract_from_dict(data)

        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["phases"][0]["criteria"][0]["verifier"]["expected_exit"] = True
        with self.assertRaisesRegex(ValueError, "expected_exit"):
            contract_from_dict(data)

        payload = EvidenceRecord.pass_record(
            evidence_id="EVD-ASSERTION-TYPE",
            goal_id="sg-20260625-state-test",
            contract_sha256=DIGEST,
            contract_revision=1,
            phase_id="P01",
            criterion_id="P01-C01",
            command="python -m unittest",
            assertion="valid",
        ).to_dict()
        payload["assertion"] = {"structured": "forged"}
        with self.assertRaisesRegex(ValueError, "assertion"):
            EvidenceRecord.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
