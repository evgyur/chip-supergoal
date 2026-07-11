import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.audit import audit_contract
from chip_supergoal.compile import compile_contract_file
from chip_supergoal.model import load_contract
from chip_supergoal.state import State, StateStore
from chip_supergoal.validate import validate_package

DIGEST = "a" * 64

class PrivateCanaryTest(unittest.TestCase):
    def contract(self):
        return load_contract(ROOT / "examples/brownfield-feature/CONTRACT.json")

    def test_safe_brownfield_canary_compile_validate(self):
        with tempfile.TemporaryDirectory() as td:
            out = compile_contract_file(ROOT / "examples/brownfield-feature/CONTRACT.json", Path(td) / "safe", template_protocol=ROOT / "templates/PROTOCOL.md")
            self.assertEqual(validate_package(out), [])

    def test_production_adjacent_canary_blocks_live_action_but_allows_safe_tests(self):
        c = self.contract()
        self.assertTrue(c.phases[0].rpd.required)
        self.assertIn("security", c.phases[0].rpd.focus)
        report = audit_contract(c, [])
        self.assertFalse(report.can_complete)

    def test_restart_recovery_heavy_canary(self):
        c = self.contract()
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            store.initialize(State(goal_id=c.goal.id, contract_sha256=DIGEST, contract_revision=c.contract_revision, state_revision=1, lifecycle="COMPILED", current_phase_id="P01", phase_status="PENDING"))
            revision = 1
            for lifecycle in ("PLAN_REVIEWED", "PREFLIGHT_GREEN", "READY_TO_DISPATCH", "RUNNING"):
                state = store.transition(lifecycle, expected_revision=revision)
                revision = state.state_revision
            reloaded = StateStore(td)
            state = State.from_dict(__import__('json').loads(reloaded.state_json.read_text()))
            self.assertEqual(state.lifecycle, "RUNNING")
            self.assertEqual(state.current_phase_id, "P01")

if __name__ == "__main__":
    unittest.main()
