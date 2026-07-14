from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evals.harness.benchmark import (
    aggregate_task_votes,
    blind_pair,
    immutable_write,
)


class BlindComparisonTests(unittest.TestCase):
    def test_pair_is_identity_free_and_deterministic(self):
        left = {"variant": "baseline", "text": "short plan"}
        right = {"variant": "b-plus-c", "text": "long plan"}
        first = blind_pair("DEV-01", 7, left, right, "a" * 64)
        second = blind_pair("DEV-01", 7, left, right, "a" * 64)
        self.assertEqual(first, second)
        self.assertEqual(set(first["plans"]), {"A", "B"})
        rendered = json.dumps(first)
        self.assertNotIn("baseline", rendered)
        self.assertNotIn("b-plus-c", rendered)
        self.assertRegex(first["assignment_commitment_sha256"], r"^[0-9a-f]{64}$")

    def test_aggregation_uses_task_as_the_only_independent_unit(self):
        votes = [
            {"task_id": "T1", "winner": "candidate"},
            {"task_id": "T1", "winner": "candidate"},
            {"task_id": "T1", "winner": "baseline"},
            {"task_id": "T2", "winner": "baseline"},
            {"task_id": "T2", "winner": "baseline"},
            {"task_id": "T2", "winner": "candidate"},
        ]
        report = aggregate_task_votes(votes)
        self.assertEqual(report["statistical_unit"], "task")
        self.assertEqual(report["independent_sample_size"], 2)
        self.assertEqual(report["task_results"], {"T1": "candidate", "T2": "baseline"})

    def test_run_artifact_is_create_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "run.json"
            immutable_write(path, {"status": "first"})
            with self.assertRaises(FileExistsError):
                immutable_write(path, {"status": "replacement"})
            self.assertEqual(json.loads(path.read_text())["status"], "first")


if __name__ == "__main__":
    unittest.main()
