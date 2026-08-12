import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.model import contract_from_dict
from chip_supergoal.render import render_loop_design, render_phase
from chip_supergoal.validate import validate_loop_design


class OutcomeDefinitionAndShawlLunaTest(unittest.TestCase):
    def fixture(self):
        return json.loads((ROOT / "examples/brownfield-feature/CONTRACT.json").read_text())

    def test_rendered_loop_binds_outcome_and_authority(self):
        contract = contract_from_dict(self.fixture())
        rendered = render_loop_design(contract)
        self.assertIn("## Outcome definition", rendered)
        for value in contract.loop.data["outcome_definition"].values():
            values = value if isinstance(value, list) else [value]
            for item in values:
                self.assertIn(item, rendered)
        self.assertIn("Host/owner: Sol", rendered)
        self.assertIn("`gpt-5.6-luna` in `scout` mode", rendered)
        self.assertIn("3 parallel read-only scouts", rendered)
        self.assertIn("fresh exact-candidate review", rendered)

    def test_rendered_phase_exposes_shawl_route(self):
        rendered = render_phase(contract_from_dict(self.fixture()), 0)
        self.assertIn("Execution route: shawl", rendered)

    def test_loop_validator_fails_closed_without_outcome_section(self):
        rendered = render_loop_design(contract_from_dict(self.fixture()))
        broken = rendered.replace("## Outcome definition", "## Missing outcome", 1)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "LOOP_DESIGN.md"
            path.write_text(broken)
            diagnostics = validate_loop_design(path, instantiated=True)
        self.assertTrue(any(item.code == "SGV-LOOP-MISSING-SECTION" for item in diagnostics))


if __name__ == "__main__":
    unittest.main()
