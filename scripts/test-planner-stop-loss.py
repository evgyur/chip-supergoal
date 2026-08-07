#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("planner-stop-loss.py")
SHA_A = "a" * 64
SHA_B = "b" * 64


class PlannerStopLossTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "package"
        self.root.mkdir()
        (self.root / "CONTRACT.json").write_text(json.dumps({"goal_id": "test-goal"}))
        self.run_guard("init")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_guard(self, action: str, *extra: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["python3", str(SCRIPT), action, "--package-root", str(self.root), *extra],
            text=True,
            capture_output=True,
        )
        if ok and proc.returncode != 0:
            self.fail(f"guard failed rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}")
        if not ok and proc.returncode == 0:
            self.fail(f"guard unexpectedly passed stdout={proc.stdout!r}")
        return proc

    def payload(self, proc: subprocess.CompletedProcess[str]) -> dict:
        return json.loads(proc.stdout)

    def test_concurrent_review_and_candidate_mismatch_are_rejected(self) -> None:
        first = self.payload(self.run_guard("pre-review", "--candidate-sha", SHA_A))
        self.assertTrue(first["review_in_flight"])
        self.run_guard("pre-review", "--candidate-sha", SHA_A, ok=False)
        self.run_guard(
            "review-result", "--candidate-sha", SHA_B,
            "--verdict", "NO_GO", "--p0", "0", "--p1", "1", ok=False,
        )
        status = self.payload(self.run_guard("status"))
        self.assertTrue(status["review_in_flight"])
        self.assertEqual(status["review_rounds"], 0)

    def test_second_non_go_blocks_third_review(self) -> None:
        self.run_guard("pre-review", "--candidate-sha", SHA_A)
        first = self.payload(self.run_guard(
            "review-result", "--candidate-sha", SHA_A,
            "--verdict", "NO_GO", "--p0", "0", "--p1", "1",
        ))
        self.assertEqual(first["terminal"], "repair")
        self.assertTrue(first["may_dispatch_review"])
        self.run_guard("pre-review", "--candidate-sha", SHA_B)
        second = self.payload(self.run_guard(
            "review-result", "--candidate-sha", SHA_B,
            "--verdict", "NO_GO", "--p0", "1", "--p1", "0",
        ))
        self.assertEqual(second["terminal"], "blocked")
        self.assertFalse(second["may_dispatch_review"])
        self.run_guard("pre-review", "--candidate-sha", SHA_B, ok=False)

    def test_only_one_meta_fix_cycle_is_allowed(self) -> None:
        first = self.payload(self.run_guard("meta-fix", "--reason", "compiler cannot include required file"))
        self.assertEqual(first["meta_fix_cycles"], 1)
        self.run_guard("meta-fix", "--reason", "second shared infrastructure change", ok=False)
        status = self.payload(self.run_guard("status"))
        self.assertEqual(status["meta_fix_cycles"], 1)

    def test_clean_first_round_go_is_terminal(self) -> None:
        self.run_guard("pre-review", "--candidate-sha", SHA_A)
        result = self.payload(self.run_guard(
            "review-result", "--candidate-sha", SHA_A,
            "--verdict", "GO", "--p0", "0", "--p1", "0",
        ))
        self.assertEqual(result["terminal"], "go")
        self.assertEqual(result["review_rounds"], 1)
        self.assertFalse(result["may_dispatch_review"])
        self.run_guard("pre-review", "--candidate-sha", SHA_A, ok=False)


if __name__ == "__main__":
    unittest.main()
