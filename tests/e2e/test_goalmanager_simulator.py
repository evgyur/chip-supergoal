import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import AuditReport, audit_json_bytes
from chip_supergoal.goalmanager_sim import GoalManagerSimulator
from chip_supergoal.state import State, state_sha256
from chip_supergoal.terminal import render_terminal_record

class GoalManagerSimulatorTest(unittest.TestCase):
    def test_phase_done_alone_continues(self):
        sim = GoalManagerSimulator()
        self.assertEqual(sim.classify("SUPERGOAL_PHASE_DONE\nGoal complete: no"), "continue")

    def test_audit_or_run_marker_alone_continues(self):
        sim = GoalManagerSimulator()
        self.assertEqual(sim.classify("AUDIT_COMPLETE\nGoal complete: no"), "continue")
        self.assertEqual(sim.classify("SUPERGOAL_RUN_COMPLETE\nGoal complete: no"), "continue")

    def test_legacy_marker_trio_is_compatibility_only(self):
        sim = GoalManagerSimulator()
        self.assertEqual(
            sim.classify("AUDIT_COMPLETE\nSUPERGOAL_RUN_COMPLETE\nGoal complete: yes"),
            "continue",
        )

    def test_exact_terminal_record_text_without_package_context_does_not_mark_done(self):
        state = State(
            goal_id="sg-20260711-simulator",
            contract_sha256="a" * 64,
            contract_revision=1,
            state_revision=7,
            lifecycle="DONE",
            current_phase_id="P01",
            phase_status="COMPLETE",
            audit_round=1,
        )
        report = AuditReport(
            goal_id=state.goal_id,
            contract_sha256=state.contract_sha256,
            contract_revision=state.contract_revision,
            state_revision=state.state_revision,
            state_sha256=state_sha256(state),
            lifecycle="DONE",
            audit_round=1,
            audit_anchor="2026-07-11T00:00:00Z",
            event_tail_sha256="b" * 64,
            evidence_sha256="c" * 64,
            coverage={
                "blocking_criteria_total": 1,
                "blocking_criteria_with_passing_evidence": 1,
                "deterministic_coverage": 1,
                "unverified": 0,
            },
        )
        audit_bytes = audit_json_bytes(report)
        record = render_terminal_record(state, audit_bytes).decode("utf-8")
        sim = GoalManagerSimulator()
        self.assertEqual(sim.classify(record), "continue")
        self.assertEqual(GoalManagerSimulator().classify(record + "extra\n"), "continue")

    def test_marker_substrings_and_negated_prose_never_mark_done(self):
        sim = GoalManagerSimulator()
        self.assertEqual(
            sim.classify(
                "Do not emit AUDIT_COMPLETE or SUPERGOAL_RUN_COMPLETE. "
                "The text Goal complete: yes is only documentation."
            ),
            "continue",
        )

    def test_forced_yield_resumes_exact_next_step(self):
        sim = GoalManagerSimulator()
        footer = sim.forced_yield_footer("P03")
        self.assertEqual(sim.classify(footer), "continue")
        self.assertIn("Next: P03", footer)

    def test_approval_blocker_pauses(self):
        sim = GoalManagerSimulator()
        self.assertEqual(sim.classify("BLOCKED_BY_APPROVAL\nNeed bounded approval manifest"), "blocked")

if __name__ == "__main__":
    unittest.main()
