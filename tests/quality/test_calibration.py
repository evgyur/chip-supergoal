from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evals.harness.calibration import calibrate


class CalibrationTests(unittest.TestCase):
    def test_missing_observations_are_non_authoritative(self):
        with tempfile.TemporaryDirectory() as td:
            report = calibrate(Path(td), cases=12, judges=2, outcome_adjudicators=2)
        self.assertEqual(report["status"], "non_authoritative")
        self.assertFalse(report["authoritative"])
        self.assertIn("private_calibration_bundle_unavailable", report["reasons"])

    def test_threshold_failure_never_becomes_authoritative(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "validation_report.json").write_text(json.dumps({
                "status": "pass",
                "counts": {"calibration": 12},
                "calibration_coverage": {"expert_episodes": 12, "multi_manifest_episodes": 6, "positive_planner_miss_manifestations": 30},
                "commitments": {"calibration_labels_sha256": "a" * 64, "outcome_partitions_sha256": "b" * 64}
            }))
            imported = root / "observations.json"
            imported.write_text(json.dumps({
                "schema_version": "calibration-observations-v1",
                "calibration_labels_sha256": "a" * 64,
                "outcome_partitions_sha256": "b" * 64,
                "judge_families": [
                    {"id": "J1", "agreement_with_expert": 0.79, "position_swap_consistency": 1.0, "kappa": 0.8, "icc": 0.8, "condition_guess_balanced_accuracy": 0.5},
                    {"id": "J2", "agreement_with_expert": 0.9, "position_swap_consistency": 1.0, "kappa": 0.8, "icc": 0.8, "condition_guess_balanced_accuracy": 0.5}
                ],
                "outcome_adjudicators": [
                    {"id": "O1", "planner_miss_precision": 0.9, "planner_miss_recall": 0.9, "macro_f1": 0.8, "label_kappa": 0.7},
                    {"id": "O2", "planner_miss_precision": 0.9, "planner_miss_recall": 0.9, "macro_f1": 0.8, "label_kappa": 0.7}
                ]
            }))
            report = calibrate(root, cases=12, judges=2, outcome_adjudicators=2, observations=imported)
        self.assertFalse(report["authoritative"])
        self.assertIn("judge_threshold_failure", report["reasons"])


if __name__ == "__main__":
    unittest.main()
