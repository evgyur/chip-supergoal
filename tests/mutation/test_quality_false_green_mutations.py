import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.quality import lint_quality_gate
from tests.quality.test_quality_lint import valid_quality_contract


class QualityFalseGreenMutationTests(unittest.TestCase):
    def test_each_reproduced_false_green_mutation_is_killed(self):
        mutations = []

        def missing_trace(contract):
            contract["compatibility"]["quality_gate_v1"]["subject"]["traceability"] = []

        mutations.append(("missing_trace", missing_trace, "QG-MISSING-TRACE"))

        def unbound_assumption(contract):
            value = contract["compatibility"]["quality_gate_v1"]["subject"]["assumptions"][0]
            value["evidence_source_id"] = None
            value["falsifier_command_id"] = None

        mutations.append(("unbound_assumption", unbound_assumption, "QG-UNBOUND-ASSUMPTION"))

        def no_alternative(contract):
            subject = contract["compatibility"]["quality_gate_v1"]["subject"]
            subject["options"] = subject["options"][:1]

        mutations.append(("no_alternative", no_alternative, "QG-NO-ALTERNATIVE"))

        def missing_rollback(contract):
            contract["compatibility"]["quality_gate_v1"]["subject"]["failure_modes"][0]["rollback"] = ""

        mutations.append(("missing_rollback", missing_rollback, "QG-RISK-NO-ROLLBACK"))

        def layer_without_removal(contract):
            contract["compatibility"]["quality_gate_v1"]["subject"]["overengineering"][0]["removal_condition"] = ""

        mutations.append(("layer_without_removal", layer_without_removal, "QG-LAYER-NO-REMOVAL"))

        killed = []
        for name, mutate, expected_code in mutations:
            contract = valid_quality_contract()
            mutate(contract)
            codes = {item.code for item in lint_quality_gate(contract)}
            self.assertIn(expected_code, codes, name)
            killed.append(name)
        self.assertEqual(len(killed), len(mutations))


if __name__ == "__main__":
    unittest.main()
