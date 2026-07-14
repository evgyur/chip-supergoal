from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.harness.canary import run_quality_canary


class QualityNoProgressTests(unittest.TestCase):
    def test_repair_rounds_never_exceed_two(self):
        calls = []
        def lint(subject):
            revision = subject.get("revision", 0)
            return [{"code": f"QG-X-{revision}", "severity": "P1", "pointer": f"/x/{revision}"}]
        def critic(_): return {"findings": [{"code": "CRIT-X", "severity": "P1", "evidence_pointer": "/x"}]}
        def repair(subject, _):
            calls.append(1)
            return {"subject": {**subject, "revision": len(calls)}}
        report = run_quality_canary({"x": 1}, route="b_plus_c", lint=lint, critic=critic, repair=repair)
        self.assertEqual(len(calls), 2)
        self.assertEqual(report["stop_reason"], "round_limit")
        self.assertEqual(report["status"], "blocked")

    def test_repeated_blocking_signature_stops_no_progress(self):
        def lint(_): return [{"code": "QG-X", "severity": "P1", "pointer": "/x"}]
        def critic(_): return {"findings": [{"code": "CRIT-X", "severity": "P1", "evidence_pointer": "/x"}]}
        report = run_quality_canary({"x": 1}, route="b_plus_c", lint=lint, critic=critic, repair=lambda s, _: {"subject": dict(s)})
        self.assertEqual(report["stop_reason"], "no_progress")
        self.assertEqual(report["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
