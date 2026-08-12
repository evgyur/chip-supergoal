import json
import random
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.model import contract_from_dict
from chip_supergoal.normalize import semantic_errors
from chip_supergoal.policy import load_risk_policy

SEED = 20260625

class SeededGraphFuzzerTest(unittest.TestCase):
    def base(self):
        return json.loads((ROOT / "examples/brownfield-feature/CONTRACT.json").read_text())

    def make_contract(self, n):
        data = self.base()
        base_phase = data["phases"][0]
        phases = []
        for i in range(1, n + 1):
            p = deepcopy(base_phase)
            pid = f"P{i:02d}"
            p["id"] = pid; p["ordinal"] = i; p["depends_on"] = [] if i == 1 else [f"P{i-1:02d}"]
            p["name"] = f"Phase {i}"; p["task"] = f"Task {i}"
            p["criteria"][0]["id"] = f"{pid}-C01"; p["criteria"][0]["verifier"]["command_id"] = f"{pid}-CMD01"
            p["commands"][0]["id"] = f"{pid}-CMD01"; p["deliverables"][0]["id"] = f"{pid}-D01"
            phases.append(p)
        data["phases"] = phases
        data["loop"]["execution_profile"]["phase_routes"] = {phase["id"]: "shawl" for phase in phases}
        return data

    def test_seeded_valid_dags_pass_and_mutations_fail(self):
        rng = random.Random(SEED)
        policy = load_risk_policy(ROOT / "spec/risk-policy.json")
        for _ in range(20):
            n = rng.randint(1, 6)
            data = self.make_contract(n)
            self.assertEqual(semantic_errors(contract_from_dict(data), policy), [])
            mutated = deepcopy(data)
            if n > 1:
                mutated["phases"][0]["depends_on"] = [f"P{n:02d}"]
                mutated["phases"][-1]["depends_on"] = ["P01"]
                self.assertTrue(any("dependency cycle" in e for e in semantic_errors(contract_from_dict(mutated), policy)))

if __name__ == "__main__":
    unittest.main()
