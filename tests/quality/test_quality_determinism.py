import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.quality import lint_quality_gate, quality_report_bytes
from tests.quality.test_quality_lint import valid_quality_contract


class QualityDeterminismTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / "spec/plan-quality-policy.json").read_text(encoding="utf-8"))
        self.rubric = json.loads((ROOT / "spec/quality-rubric.json").read_text(encoding="utf-8"))

    def test_report_bytes_are_canonical_and_repeatable(self):
        contract = valid_quality_contract()
        first = quality_report_bytes(contract, self.policy, self.rubric)
        for _ in range(5):
            self.assertEqual(quality_report_bytes(copy.deepcopy(contract), self.policy, self.rubric), first)
        self.assertEqual(first, json.dumps(json.loads(first), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n")

    def test_forged_high_risk_b_only_fails_closed(self):
        contract = valid_quality_contract()
        contract["risks"] = [{"id": "RISK-001", "tag": "control_plane", "severity": "P1", "mitigation": "bounded"}]
        attestation = contract["compatibility"]["quality_gate_v1"]["attestation"]
        attestation["semantic_review_lane"] = "b_only"
        attestation["semantic_review_lane_reason"] = "QG-LANE-STANDARD"
        attestation["semantic_judge_required"] = False
        attestation["semantic_judge_reason"] = "QG-JUDGE-NOT-REQUIRED"
        codes = {item.code for item in lint_quality_gate(contract, policy=self.policy, rubric=self.rubric)}
        self.assertIn("QG-LANE-MISMATCH", codes)
        self.assertIn("QG-JUDGE-MISMATCH", codes)

    def test_required_judge_must_have_passed_status(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["attestation"]["semantic_judge_status"] = "unavailable"
        self.assertIn(
            "QG-JUDGE-MISMATCH",
            {item.code for item in lint_quality_gate(contract, policy=self.policy, rubric=self.rubric)},
        )

    def test_tampered_subject_and_report_hash_fail_closed(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["subject"]["intent"]["objective"] = "tampered"
        codes = {item.code for item in lint_quality_gate(contract, policy=self.policy, rubric=self.rubric)}
        self.assertIn("QG-SUBJECT-HASH", codes)
        self.assertIn("QG-REPORT-HASH", codes)

    def test_stale_policy_version_fails_closed(self):
        contract = valid_quality_contract()
        contract["compatibility"]["quality_gate_v1"]["attestation"]["quality_policy_version"] = "stale"
        codes = {item.code for item in lint_quality_gate(contract, policy=self.policy, rubric=self.rubric)}
        self.assertIn("QG-POLICY-VERSION", codes)

    def test_quality_commands_require_execution_bindings(self):
        contract = valid_quality_contract()
        contract["phases"] = [{"id": "P01", "commands": [{"id": "P01-CMD01", "command": "python3 scripts/check.py", "purpose": "check", "safety": "local_read_write", "timeout_seconds": 30}]}]
        codes = {item.code for item in lint_quality_gate(contract, policy=self.policy, rubric=self.rubric)}
        self.assertIn("QG-COMMAND-TYPE", codes)

    def test_fake_command_and_undeclared_risk_fail_closed(self):
        contract = valid_quality_contract()
        contract["phases"] = [{"id": "P01", "commands": [{
            "id": "P01-CMD01", "command": "echo ok", "purpose": "check", "safety": "local_read_write", "timeout_seconds": 30,
            "cwd": ".", "mutation_class": "production_mutation", "availability_dependencies": ["echo"],
            "expected_output": {"kind": "exit_code", "value": 0}, "risk_tags": [], "risk_waiver": None,
        }]}]
        codes = {item.code for item in lint_quality_gate(contract, policy=self.policy, rubric=self.rubric)}
        self.assertIn("QG-FAKE-COMMAND", codes)
        self.assertIn("QG-UNDECLARED-RISK", codes)


if __name__ == "__main__":
    unittest.main()
