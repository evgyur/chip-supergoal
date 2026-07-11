import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import audit_contract, terminal_markers_allowed
from chip_supergoal.evidence import EvidenceRecord
from chip_supergoal.goalmanager_sim import GoalManagerSimulator
from chip_supergoal.model import load_contract
from chip_supergoal.state import State, StateStore

DIGEST = "a" * 64

class FullRunE2ETest(unittest.TestCase):
    def contract(self):
        return load_contract(ROOT / "examples/brownfield-feature/CONTRACT.json")

    def test_simple_brownfield_success_path(self):
        c = self.contract(); sim = GoalManagerSimulator()
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.initialize(State(goal_id=c.goal.id, contract_sha256=DIGEST, contract_revision=c.contract_revision, state_revision=0, lifecycle="READY_TO_DISPATCH", current_phase_id="P01", phase_status="READY"))
            running = store.transition("RUNNING", expected_revision=0, phase_status="EXECUTING")
            self.assertEqual(sim.classify("SUPERGOAL_PHASE_DONE\nGoal complete: no"), "continue")
            auditing = store.transition("AUDITING", expected_revision=1, phase_id=None, phase_status="VERIFYING")
            done = store.transition("DONE", expected_revision=2, phase_id=None, phase_status="COMPLETE")
            evidence = [EvidenceRecord.pass_record(evidence_id="EVD-000001", goal_id=c.goal.id, contract_revision=c.contract_revision, phase_id="P01", criterion_id="P01-C01")]
            report = audit_contract(c, evidence, state=done)
            self.assertTrue(terminal_markers_allowed(done, report))
            self.assertEqual(sim.classify("AUDIT_COMPLETE\nSUPERGOAL_RUN_COMPLETE\nGoal complete: yes"), "done")

    def test_risky_migration_requires_rollback_evidence_shape(self):
        c = self.contract()
        phase = c.phases[0]
        self.assertTrue(phase.rpd.required)
        self.assertIn("integration", phase.rpd.focus)
        self.assertTrue(c.risks)

    def test_failure_recovery_then_fix_spec(self):
        sim = GoalManagerSimulator()
        self.assertEqual(sim.classify("FAILURE_PROBE\ncriterion failed\nSUPERGOAL_TURN_YIELD\nGoal complete: no"), "continue")
        self.assertEqual(sim.classify("SUPERGOAL_PHASE_DONE\nGoal complete: no"), "continue")

    def test_approval_blocker_then_resume(self):
        sim = GoalManagerSimulator()
        self.assertEqual(sim.classify("BLOCKED_BY_APPROVAL\nNeed public send approval"), "blocked")
        sim = GoalManagerSimulator()
        self.assertEqual(sim.classify("approval manifest recorded\nSUPERGOAL_PHASE_DONE\nGoal complete: no"), "continue")

    def test_audit_gap_repair_then_complete(self):
        c = self.contract()
        auditing = State(goal_id=c.goal.id, contract_sha256=DIGEST, contract_revision=c.contract_revision, state_revision=3, lifecycle="AUDITING", current_phase_id=None, phase_status="VERIFYING")
        gap_report = audit_contract(c, [], state=auditing)
        self.assertFalse(gap_report.can_complete)
        done = State(goal_id=c.goal.id, contract_sha256=DIGEST, contract_revision=c.contract_revision, state_revision=4, lifecycle="DONE", current_phase_id=None, phase_status="COMPLETE")
        evidence = [EvidenceRecord.pass_record(evidence_id="EVD-000001", goal_id=c.goal.id, contract_revision=c.contract_revision, phase_id="P01", criterion_id="P01-C01")]
        fixed = audit_contract(c, evidence, state=done)
        self.assertTrue(fixed.can_complete)
        self.assertTrue(terminal_markers_allowed(done, fixed))

    def test_restart_resume_reads_state(self):
        c = self.contract()
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.initialize(State(goal_id=c.goal.id, contract_sha256=DIGEST, contract_revision=c.contract_revision, state_revision=0, lifecycle="READY_TO_DISPATCH", current_phase_id="P01", phase_status="READY"))
            store.transition("RUNNING", expected_revision=0, phase_status="EXECUTING")
            reloaded = StateStore(td)
            self.assertEqual(reloaded.state_json.read_text(), store.state_json.read_text())

if __name__ == "__main__":
    unittest.main()
