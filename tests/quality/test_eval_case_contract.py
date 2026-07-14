import copy
import hashlib
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("quality_eval_run", ROOT / "evals/run.py")
assert SPEC and SPEC.loader
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class EvalCaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = sorted((ROOT / "evals/corpus/public").glob("*.json"))
        cls.cases = [json.loads(path.read_text(encoding="utf-8")) for path in cls.paths]

    def test_exact_public_development_partition_validates(self):
        self.assertEqual(len(self.cases), 24)
        self.assertEqual(len({case["id"] for case in self.cases}), 24)
        schema = json.loads((ROOT / "spec/eval-case.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for case in self.cases:
            self.assertEqual(list(validator.iter_errors(case)), [], case["id"])
            self.assertEqual(RUN.validate_case(case, public=True), [], case["id"])

    def test_eval_case_schema_is_closed_and_hash_bound(self):
        schema = json.loads((ROOT / "spec/eval-case.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema_version"]["const"], "eval-case-v2")
        self.assertIn("planner_input", schema["required"])
        self.assertIn("controller_truth", schema["required"])
        self.assertNotIn("fairness", schema["properties"])
        outcome = json.loads((ROOT / "spec/outcome-receipt.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(outcome)
        self.assertFalse(outcome["additionalProperties"])
        self.assertEqual(outcome["properties"]["initial_adjudications"]["minItems"], 2)
        self.assertIn("signature", outcome["$defs"])
        fairness = json.loads((ROOT / "spec/fairness-receipt.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(fairness)
        self.assertFalse(fairness["additionalProperties"])
        self.assertEqual(fairness["properties"]["case_author_independent"]["const"], True)
        self.assertEqual(fairness["properties"]["candidate_implementation_independent"]["const"], True)

    def test_non_public_id_encodes_only_required_distribution_metadata(self):
        self.assertEqual(RUN.private_metadata("CAL-01-99"), ("calibration", "brownfield_integration"))
        self.assertEqual(RUN.private_metadata("SEA-06-99"), ("sealed", "agent_governance"))
        with self.assertRaisesRegex(ValueError, "invalid non-public"):
            RUN.private_metadata("SEA-secret-name-99")

    def test_public_repository_snapshots_bind_committed_source_fixtures(self):
        for case in self.cases:
            self.assertEqual(case["source_class"], "public_repo")
            self.assertEqual(case["privacy_class"], "public_repository")
            for snapshot in case["planner_input"]["source_snapshots"]:
                prefix = f"git+{RUN.CANONICAL_REMOTE}@"
                self.assertTrue(snapshot["locator"].startswith(prefix))
                revision, relative = snapshot["locator"].removeprefix(prefix).split(":", 1)
                self.assertEqual(len(revision), 40)
                committed = subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=ROOT, text=True).rstrip("\n")
                self.assertEqual(snapshot["content"], committed)

    def test_public_snapshot_cannot_rebind_to_worktree_content(self):
        case = copy.deepcopy(self.cases[0])
        snapshot = case["planner_input"]["source_snapshots"][0]
        snapshot["content"] += " local drift"
        snapshot["sha256"] = hashlib.sha256(snapshot["content"].encode("utf-8")).hexdigest()
        errors = RUN.validate_case(case, public=True)
        self.assertTrue(any("immutable committed source fixture" in error for error in errors), errors)

    def test_public_snapshot_rejects_repository_escape_path(self):
        case = copy.deepcopy(self.cases[0])
        locator = case["planner_input"]["source_snapshots"][0]["locator"]
        prefix, _ = locator.rsplit(":", 1)
        case["planner_input"]["source_snapshots"][0]["locator"] = f"{prefix}:../outside.txt"
        errors = RUN.validate_case(case, public=True)
        self.assertTrue(any("path is unsafe" in error for error in errors), errors)

    def test_secret_shaped_case_is_rejected(self):
        case = copy.deepcopy(self.cases[0])
        secret_shaped = "_".join(("api", "key")) + "=" + "live-looking-" + "secret-value"
        case["planner_input"]["context_bundle"].append({"kind": "constraint", "content": secret_shaped, "authority": "authoritative"})
        errors = RUN.validate_case(case, public=True)
        self.assertTrue(any("secret/private-trace" in error for error in errors), errors)

    def test_source_snapshot_hash_tamper_is_rejected(self):
        case = copy.deepcopy(self.cases[0])
        case["planner_input"]["source_snapshots"][0]["content"] += " tampered"
        errors = RUN.validate_case(case, public=True)
        self.assertTrue(any("content-hash-bound" in error for error in errors), errors)

    def test_deceptive_green_case_without_checks_is_rejected(self):
        case = copy.deepcopy(self.cases[0])
        case["controller_truth"]["deterministic_checks"]["checks"] = ["Report success"]
        errors = RUN.validate_case(case, public=True)
        self.assertTrue(any("two deterministic checks" in error for error in errors), errors)

    def test_non_public_content_cannot_use_public_case_contract(self):
        case = copy.deepcopy(self.cases[0])
        case["split"] = "sealed"
        case["privacy_class"] = "sealed_synthetic"
        errors = RUN.validate_case(case, public=True)
        self.assertTrue(any("public case" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
