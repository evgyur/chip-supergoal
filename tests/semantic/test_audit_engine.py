import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import audit_contract, terminal_markers_allowed, write_final_audit
from chip_supergoal.evidence import EvidenceRecord
from chip_supergoal.model import load_contract
from chip_supergoal.state import State

DIGEST = "a" * 64

class AuditEngineTest(unittest.TestCase):
    def contract(self):
        return load_contract(ROOT / "examples/brownfield-feature/CONTRACT.json")

    def evidence(self):
        c = self.contract()
        return [EvidenceRecord.pass_record(evidence_id="EVD-000001", goal_id=c.goal.id, contract_revision=c.contract_revision, phase_id="P01", criterion_id="P01-C01", command="python3 -m unittest")]

    def test_blocking_criterion_without_evidence_is_gap(self):
        report = audit_contract(self.contract(), [])
        self.assertFalse(report.can_complete)
        self.assertIn("AUDIT_GAP", {i.issue_type for i in report.issues})
        self.assertEqual(report.coverage["unverified"], 1)

    def test_planner_review_missing_after_launch_is_warning_not_gap(self):
        report = audit_contract(self.contract(), self.evidence(), planner_review_missing_after_launch=True)
        self.assertTrue(report.can_complete)
        self.assertIn("AUDIT_WARNING", {i.issue_type for i in report.issues})

    def test_final_delivery_missing_blocks_completion(self):
        report = audit_contract(self.contract(), self.evidence(), final_delivery_required=True, delivery_verified=False)
        self.assertFalse(report.can_complete)
        self.assertIn("AUDIT_GAP", {i.issue_type for i in report.issues})

    def test_terminal_markers_require_done_state_and_clean_report(self):
        c = self.contract()
        done = State(goal_id=c.goal.id, contract_sha256=DIGEST, contract_revision=c.contract_revision, state_revision=7, lifecycle="DONE", current_phase_id=None, phase_status="COMPLETE")
        running = State(goal_id=c.goal.id, contract_sha256=DIGEST, contract_revision=c.contract_revision, state_revision=6, lifecycle="AUDITING", current_phase_id=None, phase_status="VERIFYING")
        done_report = audit_contract(c, self.evidence(), state=done)
        running_report = audit_contract(c, self.evidence(), state=running)
        self.assertTrue(terminal_markers_allowed(done, done_report))
        self.assertFalse(terminal_markers_allowed(running, running_report))

    def test_final_audit_files_are_written(self):
        report = audit_contract(self.contract(), self.evidence())
        with tempfile.TemporaryDirectory() as td:
            json_path, md_path = write_final_audit(report, td)
            self.assertTrue(json_path.is_file())
            self.assertTrue(md_path.is_file())
            self.assertEqual(json.loads(json_path.read_text())["goal_id"], self.contract().goal.id)
            self.assertIn("# Final audit", md_path.read_text())

if __name__ == "__main__":
    unittest.main()
