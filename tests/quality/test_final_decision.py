from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.run import _sandbox_gate, final_aggregate, release_decision, verify_rollback


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

    def test_final_aggregate_closes_import_only_for_immutable_no_candidate(self):
        result = final_aggregate()
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hard_gates"]["sandbox_path_closed"])

    def test_import_only_cannot_support_candidate_or_synthetic_receipt(self):
        capabilities = {"status": "import_only", "authoritative": False, "synthetic_containment_claimed": False}
        selection = {"decision": "candidate", "status": "pass", "selected_variant": "b-only", "sealed_holdout_accessed": False, "retained_runtime_layers": ["b-only"]}
        study = {"decision": "candidate", "status": "pass", "sealed_holdout_accessed": False, "selection_sha256": "adr"}
        release = {"verdict": "go", "runtime_profile_enabled": True}
        live = {"outcome": "no_veto", "tasks_observed": 12, "phase_exposures": 2}
        self.assertFalse(_sandbox_gate(capabilities, selection, study, release, live, "adr"))
        capabilities["synthetic_containment_claimed"] = True
        selection.update({"decision": "no_candidate", "status": "no_go", "selected_variant": None, "retained_runtime_layers": []})
        study.update({"decision": "no_candidate", "status": "not_applicable"})
        release.update({"verdict": "no-go", "runtime_profile_enabled": False})
        live.update({"outcome": "not_applicable", "tasks_observed": 0, "phase_exposures": 0})
        self.assertFalse(_sandbox_gate(capabilities, selection, study, release, live, "adr"))

    def test_no_candidate_rollback_preserves_fixture_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = verify_rollback(ROOT / "evals/baselines/v3-baseline-manifest.json", root / "pre", root / "post")
            before = ((root / "pre/NO_PACKAGE.json").read_bytes(), (root / "post/NO_PACKAGE.json").read_bytes())
            verify_rollback(ROOT / "evals/baselines/v3-baseline-manifest.json", root / "pre", root / "post")
            self.assertEqual(before, ((root / "pre/NO_PACKAGE.json").read_bytes(), (root / "post/NO_PACKAGE.json").read_bytes()))
            self.assertTrue(result["baseline_restored"])


if __name__ == "__main__": unittest.main()
