import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.model import canonical_json, contract_from_dict, load_contract
from chip_supergoal.normalize import semantic_errors
from chip_supergoal.policy import load_risk_policy

class ContractModelTest(unittest.TestCase):
    def fixture(self):
        return json.loads((ROOT / "examples/brownfield-feature/CONTRACT.json").read_text())

    def test_contract_loads_and_serializes_canonically(self):
        contract = load_contract(ROOT / "examples/brownfield-feature/CONTRACT.json")
        encoded = canonical_json(contract)
        self.assertTrue(encoded.endswith("\n"))
        self.assertEqual(encoded, canonical_json(contract))
        self.assertEqual(contract.goal.id, "sg-20260625-brownfield-feature")

    def test_unknown_fields_are_rejected_in_strict_mode(self):
        data = self.fixture()
        data["unexpected"] = True
        with self.assertRaises(ValueError):
            contract_from_dict(data, strict=True)

    def test_duplicate_phase_id_is_rejected(self):
        data = self.fixture()
        data["phases"].append(deepcopy(data["phases"][0]))
        data["phases"][1]["ordinal"] = 2
        contract = contract_from_dict(data)
        self.assertTrue(any("duplicate phase id" in e or "duplicate id" in e for e in semantic_errors(contract, load_risk_policy(ROOT / "spec/risk-policy.json"))))

    def test_missing_dependency_is_rejected(self):
        data = self.fixture()
        data["phases"][0]["depends_on"] = ["P99"]
        contract = contract_from_dict(data)
        self.assertIn("P01 depends on missing phase P99", semantic_errors(contract, load_risk_policy(ROOT / "spec/risk-policy.json")))

    def test_missing_outcome_definition_is_rejected(self):
        data = self.fixture()
        del data["loop"]["outcome_definition"]
        errors = semantic_errors(contract_from_dict(data), load_risk_policy(ROOT / "spec/risk-policy.json"))
        self.assertIn("loop.outcome_definition must be an object", errors)

    def test_luna_is_bounded_and_never_owns_the_loop(self):
        data = self.fixture()
        data["loop"]["execution_profile"]["owner"] = "Luna"
        data["loop"]["execution_profile"]["max_parallel_scouts"] = 4
        errors = semantic_errors(contract_from_dict(data), load_risk_policy(ROOT / "spec/risk-policy.json"))
        self.assertIn("loop.execution_profile.owner must equal 'Sol'", errors)
        self.assertIn("loop.execution_profile.max_parallel_scouts must be an integer from 1 to 3", errors)

    def test_risky_phase_must_route_through_shawl(self):
        data = self.fixture()
        data["loop"]["execution_profile"]["phase_routes"]["P01"] = "direct"
        errors = semantic_errors(contract_from_dict(data), load_risk_policy(ROOT / "spec/risk-policy.json"))
        self.assertIn("P01 is risky/RPD-required and must route through shawl", errors)

    def test_execution_profile_rejects_wrong_model_mode_and_bounds(self):
        data = self.fixture()
        profile = data["loop"]["execution_profile"]
        profile["worker_model"] = "gpt-other"
        profile["worker_mode"] = "write"
        profile["max_review_rounds"] = 0
        profile["phase_routes"] = {}
        errors = semantic_errors(contract_from_dict(data), load_risk_policy(ROOT / "spec/risk-policy.json"))
        self.assertIn("loop.execution_profile.worker_model must equal 'gpt-5.6-luna'", errors)
        self.assertIn("loop.execution_profile.worker_mode must equal 'scout'", errors)
        self.assertIn("loop.execution_profile.max_review_rounds must be an integer from 1 to 3", errors)
        self.assertIn("loop.execution_profile.phase_routes must cover every phase exactly", errors)

    def test_outcome_definition_rejects_extra_and_empty_fields(self):
        data = self.fixture()
        outcome = data["loop"]["outcome_definition"]
        outcome["extra"] = "not allowed"
        outcome["evidence"] = []
        errors = semantic_errors(contract_from_dict(data), load_risk_policy(ROOT / "spec/risk-policy.json"))
        self.assertIn("loop.outcome_definition has unknown fields: extra", errors)
        self.assertIn("loop.outcome_definition.evidence must be a non-empty string array", errors)

    def test_dependency_cycle_is_rejected(self):
        data = self.fixture()
        second = deepcopy(data["phases"][0])
        second["id"] = "P02"; second["ordinal"] = 2; second["depends_on"] = ["P01"]
        second["criteria"][0]["id"] = "P02-C01"; second["criteria"][0]["verifier"]["command_id"] = "P02-CMD01"
        second["commands"][0]["id"] = "P02-CMD01"; second["deliverables"][0]["id"] = "P02-D01"
        data["phases"][0]["depends_on"] = ["P02"]
        data["phases"].append(second)
        contract = contract_from_dict(data)
        self.assertTrue(any("dependency cycle" in e for e in semantic_errors(contract, load_risk_policy(ROOT / "spec/risk-policy.json"))))

    def test_risky_phase_without_required_rpd_focus_is_rejected(self):
        data = self.fixture()
        data["phases"][0]["rpd"] = {"required": False, "focus": []}
        contract = contract_from_dict(data)
        errors = semantic_errors(contract, load_risk_policy(ROOT / "spec/risk-policy.json"))
        self.assertTrue(any("requires RPD" in e for e in errors))
        self.assertTrue(any("missing RPD focus" in e for e in errors))

if __name__ == "__main__":
    unittest.main()
