import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("quality_eval_run_fairness", ROOT / "evals/run.py")
assert SPEC and SPEC.loader
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class CaseFairnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((ROOT / "evals/corpus/public").glob("*.json"))]

    def test_case_envelope_contains_no_self_referential_reviewers(self):
        for case in self.cases:
            self.assertNotIn("fairness", case)
            self.assertNotIn("expert_labels", case["planner_input"])
            self.assertNotIn("outcome_partition_labels", case["planner_input"])

    def test_metamorphic_and_strategy_fairness_minima(self):
        variants = sum(bool(case["controller_truth"]["metamorphic"]["transforms"]) for case in self.cases)
        self.assertGreaterEqual(variants, 20)
        for case in self.cases:
            checks = case["controller_truth"]["deterministic_checks"]
            if checks["strategy_flexible"]:
                self.assertGreaterEqual(len(set(checks["valid_strategy_ids"])), 2)
            self.assertTrue(case["controller_truth"]["metamorphic"]["acceptable_decision_equivalence_set"])

    def test_underspecified_case_without_oracle_is_rejected(self):
        case = copy.deepcopy(self.cases[0])
        case["planner_input"]["clarification_oracle"] = {"required": True, "question": None, "allowed_answer_hash": None}
        errors = RUN.validate_case(case, public=True)
        self.assertTrue(any("clarification" in error for error in errors), errors)

    def test_single_strategy_grader_is_rejected_when_flexible(self):
        case = copy.deepcopy(self.cases[0])
        case["controller_truth"]["deterministic_checks"]["valid_strategy_ids"] = ["only-one"]
        errors = RUN.validate_case(case, public=True)
        self.assertTrue(any("two valid strategies" in error for error in errors), errors)

    def test_policy_thresholds_and_statistical_unit_are_frozen(self):
        rubric = json.loads((ROOT / "spec/quality-rubric.json").read_text(encoding="utf-8"))
        quality = json.loads((ROOT / "spec/plan-quality-policy.json").read_text(encoding="utf-8"))
        promotion = json.loads((ROOT / "spec/promotion-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(item["weight"] for item in rubric["dimensions"]), 100)
        self.assertEqual(quality["mcid"]["weighted_score_0_to_100"], 6.25)
        self.assertEqual(quality["paired_protocol"]["statistical_unit"], "task")
        self.assertFalse(quality["paired_protocol"]["seed_or_judge_as_independent_sample"])
        self.assertEqual(promotion["primary_endpoint_selection"]["qualified_tie_breaker"], "hidden_pass")
        self.assertTrue(promotion["primary_endpoint_selection"]["post_unblinding_substitution_forbidden"])
        self.assertEqual([gate["id"] for gate in promotion["gates"]], list(range(1, 14)))

    def test_policy_freeze_rejects_transitive_reference_mutation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "evals") as tmp:
            tmp_path = Path(tmp)
            reference = tmp_path / "transitive.json"
            reference.write_text('{"version":1}\n', encoding="utf-8")
            holdout = tmp_path / "holdout.json"
            holdout.write_text(json.dumps({"policies": {"fixture": reference.relative_to(ROOT).as_posix()}}), encoding="utf-8")
            output = tmp_path / "freeze.json"
            RUN.freeze_policy(
                ROOT / "spec/quality-rubric.json",
                ROOT / "spec/plan-quality-policy.json",
                ROOT / "spec/promotion-policy.json",
                holdout,
                output=output,
            )
            reference.write_text('{"version":2}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "post-freeze policy mutation"):
                RUN.freeze_policy(
                    ROOT / "spec/quality-rubric.json",
                    ROOT / "spec/plan-quality-policy.json",
                    ROOT / "spec/promotion-policy.json",
                    holdout,
                    output=output,
                )

    def test_policy_freeze_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sources = []
            for original in (
                ROOT / "spec/quality-rubric.json",
                ROOT / "spec/plan-quality-policy.json",
                ROOT / "spec/promotion-policy.json",
                ROOT / "evals/baselines/v3-baseline-manifest.json",
            ):
                target = tmp_path / original.name
                target.write_bytes(original.read_bytes())
                sources.append(target)
            output = tmp_path / "policy-freeze.json"
            RUN.freeze_policy(*sources, output=output)
            value = json.loads(sources[0].read_text(encoding="utf-8"))
            value["dimensions"][0]["weight"] = 19
            sources[0].write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "post-freeze policy mutation"):
                RUN.freeze_policy(*sources, output=output)


if __name__ == "__main__":
    unittest.main()
