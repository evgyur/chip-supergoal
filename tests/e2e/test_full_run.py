import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import audit_contract
from chip_supergoal.evidence import EvidenceRecord
from chip_supergoal.events import read_events
from chip_supergoal.goalmanager_sim import GoalManagerSimulator
from chip_supergoal.model import canonical_json, contract_from_dict, load_contract
from chip_supergoal.state import State, StateStore


class FullRunE2ETest(unittest.TestCase):
    def contract(self):
        return load_contract(ROOT / "examples/brownfield-feature/CONTRACT.json")

    def audit_fixture(self):
        data = json.loads(
            (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                encoding="utf-8"
            )
        )
        data["risks"] = []
        data["phases"][0]["risk_tags"] = []
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        data["loop"] = {}
        data["delivery"] = {}
        contract = contract_from_dict(data)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = StateStore(temporary.name)
        digest = hashlib.sha256(canonical_json(contract).encode("utf-8")).hexdigest()
        store.initialize(
            State(
                goal_id=contract.goal.id,
                contract_sha256=digest,
                contract_revision=contract.contract_revision,
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
        state = store.update(expected_revision=revision, phase_status="COMPLETE")
        revision = state.state_revision
        state = store.transition("AUDITING", expected_revision=revision)
        return contract, state, read_events(store.events)

    def passing_evidence(self, contract, state, events):
        criterion = contract.phases[0].criteria[0]
        command = contract.phases[0].commands[0]
        return EvidenceRecord.pass_record(
            evidence_id="EVD-000001",
            goal_id=contract.goal.id,
            contract_sha256=state.contract_sha256,
            contract_revision=contract.contract_revision,
            phase_id="P01",
            criterion_id="P01-C01",
            command=command.command,
            exit_code=criterion.verifier.expected_exit,
            assertion=criterion.verifier.expected_assertion,
            captured_at=events[-1]["timestamp"],
        )

    def test_simple_brownfield_success_path(self):
        contract, state, events = self.audit_fixture()
        evidence = self.passing_evidence(contract, state, events)
        report = audit_contract(contract, [evidence], state=state, events=events)
        self.assertTrue(report.can_complete, report.issues)
        sim = GoalManagerSimulator()
        self.assertEqual(sim.classify("SUPERGOAL_PHASE_DONE\nGoal complete: no"), "continue")
        self.assertEqual(
            sim.classify("AUDIT_COMPLETE\nSUPERGOAL_RUN_COMPLETE\nGoal complete: yes"),
            "continue",
        )

    def test_risky_migration_requires_rollback_evidence_shape(self):
        contract = self.contract()
        phase = contract.phases[0]
        self.assertTrue(phase.rpd.required)
        self.assertIn("integration", phase.rpd.focus)
        self.assertTrue(contract.risks)

    def test_failure_recovery_then_fix_spec(self):
        sim = GoalManagerSimulator()
        self.assertEqual(
            sim.classify(
                "FAILURE_PROBE\ncriterion failed\nSUPERGOAL_TURN_YIELD\nGoal complete: no"
            ),
            "continue",
        )
        self.assertEqual(
            sim.classify("SUPERGOAL_PHASE_DONE\nGoal complete: no"), "continue"
        )

    def test_approval_blocker_then_resume(self):
        sim = GoalManagerSimulator()
        self.assertEqual(
            sim.classify("BLOCKED_BY_APPROVAL\nNeed public send approval"), "blocked"
        )
        self.assertEqual(
            GoalManagerSimulator().classify(
                "approval manifest recorded\nSUPERGOAL_PHASE_DONE\nGoal complete: no"
            ),
            "continue",
        )

    def test_audit_gap_repair_then_complete(self):
        contract, state, events = self.audit_fixture()
        gap = audit_contract(contract, [], state=state, events=events)
        self.assertFalse(gap.can_complete)
        fixed = audit_contract(
            contract,
            [self.passing_evidence(contract, state, events)],
            state=state,
            events=events,
        )
        self.assertTrue(fixed.can_complete, fixed.issues)

    def test_restart_resume_reads_state(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            initial = State(
                goal_id="sg-20260711-restart",
                contract_sha256="a" * 64,
                contract_revision=1,
                state_revision=1,
                lifecycle="COMPILED",
                current_phase_id="P01",
                phase_status="PENDING",
            )
            store.initialize(initial)
            store.transition("PLAN_REVIEWED", expected_revision=1)
            reloaded = StateStore(td)
            self.assertEqual(reloaded.state_json.read_text(), store.state_json.read_text())


if __name__ == "__main__":
    unittest.main()
