from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.run import final_aggregate, release_decision, verify_rollback


class FinalDecisionTests(unittest.TestCase):
    def test_no_candidate_derives_no_go_without_threshold_change(self):
        result, adr = release_decision(ROOT / "reports/quality/promotion-study.json", ROOT / "reports/quality/live-canary-veto.json", ROOT / "spec/promotion-policy.json")
        self.assertEqual(result["verdict"], "no-go")
        self.assertFalse(result["thresholds_changed"])
        self.assertIn("`no-go`", adr)

    def test_failed_study_cannot_be_rescued(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary) / "study.json"
            study.write_text(json.dumps({"decision": "candidate", "status": "pass"}), encoding="utf-8")
            with self.assertRaises(ValueError): release_decision(study, ROOT / "reports/quality/live-canary-veto.json", ROOT / "spec/promotion-policy.json")

    def test_final_aggregate_blocks_import_only_sandbox(self):
        result = final_aggregate()
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["hard_gates"]["sandbox_promotion_authority"])

    def test_no_candidate_rollback_preserves_fixture_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = verify_rollback(ROOT / "evals/baselines/v3-baseline-manifest.json", root / "pre", root / "post")
            before = ((root / "pre/NO_PACKAGE.json").read_bytes(), (root / "post/NO_PACKAGE.json").read_bytes())
            verify_rollback(ROOT / "evals/baselines/v3-baseline-manifest.json", root / "pre", root / "post")
            self.assertEqual(before, ((root / "pre/NO_PACKAGE.json").read_bytes(), (root / "post/NO_PACKAGE.json").read_bytes()))
            self.assertTrue(result["baseline_restored"])


if __name__ == "__main__": unittest.main()
