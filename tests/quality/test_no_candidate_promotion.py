from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.run import promotion_study, verify_execution_no_candidate, verify_live_canary_no_candidate


class NoCandidatePromotionTests(unittest.TestCase):
    def setUp(self):
        self.selection = ROOT / "docs/adr/ADR-005-quality-candidate-selection.md"

    def test_study_does_not_unblind_holdout(self):
        result = promotion_study(self.selection, ROOT / "evals/manifests/holdout-manifest.json", ROOT / "spec/promotion-policy.json")
        self.assertEqual(result["status"], "not_applicable")
        self.assertFalse(result["sealed_holdout_accessed"])

    def test_forged_study_fails_execution_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "study.json"
            path.write_text(json.dumps({"decision": "no_candidate", "status": "pass", "sealed_holdout_accessed": True}), encoding="utf-8")
            with self.assertRaises(ValueError): verify_execution_no_candidate(self.selection, path)

    def test_live_receipt_counts_cannot_relax(self):
        with self.assertRaises(ValueError):
            verify_live_canary_no_candidate(self.selection, {"not_applicable"}, 0, 0, 0)

    def test_live_no_candidate_is_zero_exposure(self):
        result = verify_live_canary_no_candidate(self.selection, {"no_veto", "veto", "inconclusive", "not_applicable"}, 30, 30, 150)
        self.assertEqual(result["outcome"], "not_applicable")
        self.assertEqual(result["phase_exposures"], 0)
        self.assertFalse(result["profile_enabled"])


if __name__ == "__main__": unittest.main()
