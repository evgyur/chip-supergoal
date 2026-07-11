import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.events import event_hash, read_events, verify_event_chain
import chip_supergoal.state as state_module
from chip_supergoal.state import State, StateStore, read_state, recover_from_events, state_sha256, validate_goal_identity

DIGEST = "a" * 64

class StateMachineTest(unittest.TestCase):
    def test_atomic_transition_and_event_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            initial = State(goal_id="sg-20260625-state-test", contract_sha256=DIGEST, contract_revision=1, state_revision=0, lifecycle="DRAFT", current_phase_id="P01", phase_status="PENDING")
            store.initialize(initial)
            new = store.transition("COMPILED", expected_revision=0, phase_status="READY")
            self.assertEqual(new.state_revision, 1)
            self.assertEqual(read_state(store.state_json).lifecycle, "COMPILED")
            events = read_events(store.events)
            self.assertEqual(verify_event_chain(events), [])
            self.assertEqual(events[-1]["state_revision"], 1)
            self.assertEqual(events[-1]["contract_revision"], 1)
            self.assertEqual(events[-1]["state"], new.to_dict())
            self.assertEqual(events[-1]["state_sha256"], state_sha256(new))
            self.assertIn("COMPILED", store.state_md.read_text())

    def test_illegal_transition_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.initialize(State(goal_id="sg-20260625-state-test", contract_sha256=DIGEST, contract_revision=1, state_revision=0, lifecycle="COMPILED", current_phase_id="P01", phase_status="READY"))
            with self.assertRaisesRegex(ValueError, "SGV-STATE-ILLEGAL-TRANSITION"):
                store.transition("DONE", expected_revision=0)

    def test_stale_writer_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.initialize(State(goal_id="sg-20260625-state-test", contract_sha256=DIGEST, contract_revision=1, state_revision=0, lifecycle="DRAFT", current_phase_id="P01", phase_status="PENDING"))
            store.transition("COMPILED", expected_revision=0)
            with self.assertRaisesRegex(ValueError, "SGV-STATE-STALE-WRITER"):
                store.transition("PLAN_REVIEWED", expected_revision=0)

    def test_goal_digest_mismatch_rejected(self):
        state = State(goal_id="sg-20260625-state-test", contract_sha256=DIGEST, contract_revision=3, state_revision=0, lifecycle="DRAFT", current_phase_id="P01", phase_status="PENDING")
        with self.assertRaisesRegex(ValueError, "SGV-STATE-CONTRACT-MISMATCH"):
            validate_goal_identity(state, goal_id="sg-20260625-other", contract_sha256=DIGEST, contract_revision=3)
        with self.assertRaisesRegex(ValueError, "SGV-STATE-CONTRACT-MISMATCH"):
            validate_goal_identity(state, goal_id="sg-20260625-state-test", contract_sha256="b" * 64, contract_revision=3)
        with self.assertRaisesRegex(ValueError, "SGV-STATE-CONTRACT-MISMATCH"):
            validate_goal_identity(state, goal_id="sg-20260625-state-test", contract_sha256=DIGEST, contract_revision=4)

    def test_recovery_from_corrupt_state_uses_valid_event_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            initial = State(goal_id="sg-20260625-state-test", contract_sha256=DIGEST, contract_revision=1, state_revision=0, lifecycle="DRAFT", current_phase_id="P01", phase_status="PENDING")
            store.initialize(initial)
            store.state_json.write_text("{broken", encoding="utf-8")
            recovered = recover_from_events(td)
            self.assertEqual(recovered, initial)
            self.assertEqual(read_state(store.state_json), initial)
            self.assertEqual(store.state_md.read_text(encoding="utf-8"), state_module.render_state_md(initial))
            store.events.write_text(store.events.read_text().replace('"event_id"', '"event_id_tampered"', 1), encoding="utf-8")
            self.assertIsNone(recover_from_events(td))

    def test_transition_journals_target_state_before_projection_and_recovery_replays_it(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            initial = State(
                goal_id="sg-20260625-state-test",
                contract_sha256=DIGEST,
                contract_revision=7,
                state_revision=0,
                lifecycle="DRAFT",
                current_phase_id="P01",
                phase_status="PENDING",
            )
            store.initialize(initial)
            target = initial.transition("COMPILED", phase_status="READY")

            with mock.patch.object(
                state_module,
                "write_state_atomic",
                side_effect=OSError("injected projection crash"),
            ):
                with self.assertRaisesRegex(OSError, "projection crash"):
                    store.transition("COMPILED", expected_revision=0, phase_status="READY")

            self.assertEqual(read_state(store.state_json), initial)
            events = read_events(store.events)
            self.assertEqual(len(events), 2)
            self.assertEqual(verify_event_chain(events), [])
            self.assertEqual(events[-1]["contract_revision"], 7)
            self.assertEqual(events[-1]["state"], target.to_dict())
            self.assertEqual(events[-1]["state_sha256"], state_sha256(target))

            recovered = recover_from_events(td)
            self.assertEqual(recovered, target)
            self.assertEqual(read_state(store.state_json), target)
            self.assertEqual(store.state_md.read_text(encoding="utf-8"), state_module.render_state_md(target))

    def test_recovery_replays_journal_after_markdown_projection_crash(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            initial = State(
                goal_id="sg-20260625-state-test",
                contract_sha256=DIGEST,
                contract_revision=2,
                state_revision=0,
                lifecycle="DRAFT",
                current_phase_id="P01",
                phase_status="PENDING",
            )
            store.initialize(initial)
            target = initial.transition("COMPILED", phase_status="READY")

            with mock.patch.object(
                state_module,
                "write_utf8_lf",
                side_effect=OSError("injected markdown crash"),
            ):
                with self.assertRaisesRegex(OSError, "markdown crash"):
                    store.transition("COMPILED", expected_revision=0, phase_status="READY")

            self.assertEqual(read_state(store.state_json), target)
            self.assertEqual(store.state_md.read_text(encoding="utf-8"), state_module.render_state_md(initial))
            self.assertEqual(recover_from_events(td), target)
            self.assertEqual(store.state_md.read_text(encoding="utf-8"), state_module.render_state_md(target))

    def test_recovery_refuses_tampered_embedded_state_without_mutating_projections(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            initial = State(
                goal_id="sg-20260625-state-test",
                contract_sha256=DIGEST,
                contract_revision=1,
                state_revision=0,
                lifecycle="DRAFT",
                current_phase_id="P01",
                phase_status="PENDING",
            )
            store.initialize(initial)
            state_before = store.state_json.read_bytes()
            markdown_before = store.state_md.read_bytes()
            events = read_events(store.events)
            events[0]["state"]["phase_status"] = "TAMPERED"
            events[0]["event_sha256"] = event_hash(events[0])
            store.events.write_text(
                json.dumps(events[0], ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            self.assertIsNone(recover_from_events(td))
            self.assertEqual(store.state_json.read_bytes(), state_before)
            self.assertEqual(store.state_md.read_bytes(), markdown_before)

if __name__ == "__main__":
    unittest.main()
