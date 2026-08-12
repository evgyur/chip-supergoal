import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.compile import compile_contract
from chip_supergoal.model import contract_from_dict


class ShawlLunaCompiledArtifactsTest(unittest.TestCase):
    def fixture(self):
        return json.loads((ROOT / "examples/brownfield-feature/CONTRACT.json").read_text())

    def test_compiled_package_binds_route_and_protocol_authority(self):
        data = self.fixture()
        first = data["phases"][0]
        first["risk_tags"] = []
        first["rpd"] = {"required": False, "focus": []}
        data["loop"]["execution_profile"]["phase_routes"]["P01"] = "direct"

        second = deepcopy(first)
        second["id"] = "P02"
        second["ordinal"] = 2
        second["name"] = "Risky phase"
        second["task"] = "Review a risky candidate"
        second["depends_on"] = ["P01"]
        second["criteria"][0]["id"] = "P02-C01"
        second["criteria"][0]["verifier"]["command_id"] = "P02-CMD01"
        second["commands"][0]["id"] = "P02-CMD01"
        second["deliverables"][0]["id"] = "P02-D01"
        second["risk_tags"] = ["auth"]
        second["rpd"] = {"required": True, "focus": ["security"]}
        data["phases"].append(second)
        data["loop"]["execution_profile"]["phase_routes"]["P02"] = "shawl"

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "package"
            compile_contract(contract_from_dict(data), out, template_protocol=ROOT / "templates/PROTOCOL.md")
            self.assertIn("Execution route: direct", (out / "phases/phase-01.md").read_text())
            self.assertIn("Execution route: shawl", (out / "phases/phase-02.md").read_text())
            loop = (out / "LOOP_DESIGN.md").read_text()
            self.assertIn("P01=direct", loop)
            self.assertIn("P02=shawl", loop)
            protocol = (out / "PROTOCOL.md").read_text()
            self.assertIn("Resolve and fail-close the phase execution route", protocol)
            self.assertIn("only Sol/GoalManager may reproduce, write/integrate", protocol)
            self.assertIn("Every code-affecting fix creates a new candidate identity", protocol)
            launch = (out / "LAUNCH_GOAL.md").read_text()
            self.assertIn("standard Hermes /goal remains the executor", launch)


if __name__ == "__main__":
    unittest.main()
