from __future__ import annotations

import unittest

from evals.harness.benchmark import evaluate_bias_controls


class JudgeBiasControlTests(unittest.TestCase):
    def test_position_following_judge_is_rejected(self):
        observations = [
            {"control": "position_swap", "pair_id": "P1", "order": "AB", "winner_content_sha256": "a" * 64},
            {"control": "position_swap", "pair_id": "P1", "order": "BA", "winner_content_sha256": "b" * 64},
        ]
        report = evaluate_bias_controls(observations)
        self.assertFalse(report["authoritative"])
        self.assertIn("position_bias", report["failures"])

    def test_verbosity_trap_rejects_long_wrong_preference(self):
        observations = [
            {"control": "verbosity_trap", "trap_id": "V1", "winner": "long_wrong", "expected": "concise_correct"}
        ]
        report = evaluate_bias_controls(observations)
        self.assertFalse(report["authoritative"])
        self.assertIn("verbosity_bias", report["failures"])

    def test_clean_controls_are_authoritative(self):
        observations = [
            {"control": "position_swap", "pair_id": "P1", "order": "AB", "winner_content_sha256": "a" * 64},
            {"control": "position_swap", "pair_id": "P1", "order": "BA", "winner_content_sha256": "a" * 64},
            {"control": "verbosity_trap", "trap_id": "V1", "winner": "concise_correct", "expected": "concise_correct"},
        ]
        report = evaluate_bias_controls(observations)
        self.assertTrue(report["authoritative"])
        self.assertEqual(report["failures"], [])


if __name__ == "__main__":
    unittest.main()
