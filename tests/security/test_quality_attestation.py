from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.quality import lint_quality_gate, plan_subject_projection, seal_quality_attestation
from tests.quality.test_quality_lint import valid_quality_contract


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


class QualityAttestationTests(unittest.TestCase):
    def test_subject_projection_is_acyclic_and_hash_bound(self):
        contract = valid_quality_contract()
        attestation = contract["compatibility"]["quality_gate_v1"]["attestation"]
        self.assertEqual(attestation["plan_subject_sha256"], hashlib.sha256(canonical(plan_subject_projection(contract))).hexdigest())
        self.assertEqual(contract, seal_quality_attestation(contract, {"schema_version": "plan-quality-policy-v1"}, {"schema_version": "quality-rubric-v1"}))

    def test_subject_mutation_invalidates_attestation(self):
        contract = copy.deepcopy(valid_quality_contract())
        contract["compatibility"]["quality_gate_v1"]["subject"]["requirements"][0]["statement"] = "mutated"
        codes = {finding.code for finding in lint_quality_gate(contract)}
        self.assertIn("QG-SUBJECT-HASH", codes)

    def test_report_hash_mutation_fails_closed(self):
        contract = copy.deepcopy(valid_quality_contract())
        contract["compatibility"]["quality_gate_v1"]["attestation"]["report_sha256"] = "0" * 64
        codes = {finding.code for finding in lint_quality_gate(contract, policy={"schema_version": "plan-quality-policy-v1"}, rubric={"schema_version": "quality-rubric-v1"})}
        self.assertIn("QG-REPORT-HASH", codes)


if __name__ == "__main__": unittest.main()
