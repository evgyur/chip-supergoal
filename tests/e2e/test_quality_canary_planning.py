from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.harness.canary import run_quality_canary


def lint(subject):
    missing = subject.get("missing", False)
    return [{"code": "QG-MISSING", "severity": "P1", "pointer": "/missing"}] if missing else []


class QualityCanaryPlanningTests(unittest.TestCase):
    def test_b_only_makes_zero_semantic_calls(self):
        calls = {"critic": 0, "judge": 0}
        report = run_quality_canary(
            {"missing": False}, route="b_only", lint=lint,
            critic=lambda _: calls.__setitem__("critic", calls["critic"] + 1),
            judge=lambda _: calls.__setitem__("judge", calls["judge"] + 1),
        )
        self.assertEqual(calls, {"critic": 0, "judge": 0})
        self.assertEqual(report["status"], "green")

    def test_b_plus_c_repairs_and_relints(self):
        counts = {"lint": 0, "critic": 0, "repair": 0}
        def counted_lint(subject):
            counts["lint"] += 1
            return lint(subject)
        def critic(_subject):
            counts["critic"] += 1
            return {"findings": [{"code": "CRIT-MISSING", "severity": "P1", "evidence_pointer": "/missing"}]}
        def repair(subject, _findings):
            counts["repair"] += 1
            return {"subject": {**subject, "missing": False}, "evidence_pointers": ["/missing"]}
        report = run_quality_canary({"missing": True}, route="b_plus_c", lint=counted_lint, critic=critic, repair=repair)
        self.assertEqual(report["status"], "green")
        self.assertEqual(counts["repair"], 1)
        self.assertGreaterEqual(counts["lint"], 2)
        self.assertTrue(report["re_lint_after_every_repair"])

    def test_policy_required_judge_is_called_once(self):
        calls = []
        report = run_quality_canary(
            {"missing": False}, route="b_plus_c", lint=lint,
            critic=lambda _: {"findings": []},
            judge=lambda _: calls.append("judge") or {"status": "passed", "findings": []},
            judge_required=True,
        )
        self.assertEqual(calls, ["judge"])
        self.assertEqual(report["semantic_calls"]["judge"], 1)


if __name__ == "__main__":
    unittest.main()
