from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.canary import run_quality_canary


class QualityChainOfThoughtTests(unittest.TestCase):
    def test_raw_reasoning_is_never_persisted(self):
        report = run_quality_canary(
            {"ok": True}, route="b_plus_c", lint=lambda _: [],
            critic=lambda _: {"chain_of_thought": "private reasoning", "findings": [], "evidence_pointers": ["/evidence/1"]},
        )
        rendered = json.dumps(report)
        self.assertNotIn("private reasoning", rendered)
        self.assertNotIn("chain_of_thought", rendered)

    def test_ledger_contains_hashes_and_evidence_pointers_only(self):
        report = run_quality_canary(
            {"ok": True}, route="b_plus_c", lint=lambda _: [],
            critic=lambda _: {"reasoning": "hidden", "findings": [], "evidence_pointers": ["/evidence/1"]},
        )
        entry = report["mutation_ledger"][0]
        self.assertRegex(entry["entry_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(entry["evidence_pointers"], ["/evidence/1"])


if __name__ == "__main__":
    unittest.main()
