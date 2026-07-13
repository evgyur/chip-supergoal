from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "evals" / "b2" / "b2-neutral-harness" / "probe.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("b2_neutral_probe", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load neutral probe")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class B2NeutralProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_metric_summary_uses_frozen_repetition_count_and_percentiles(self):
        summary = self.probe.summarize_measurements([1.0, 2.0, 3.0, 4.0, 9.0], expected=5)

        self.assertEqual(summary["count"], 5)
        self.assertEqual(summary["p50"], 3.0)
        self.assertEqual(summary["p95"], 9.0)
        self.assertEqual(summary["minimum"], 1.0)
        self.assertEqual(summary["maximum"], 9.0)

    def test_measurement_count_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "measurement count"):
            self.probe.summarize_measurements([1.0, 2.0], expected=5)

    def test_capability_receipt_requires_every_native_windows_capability(self):
        required = ["powershell-safe-cli", "path-swap-races"]
        receipt = self.probe.empty_capability_receipt_for_test(required)
        self.assertTrue(self.probe.validate_capability_receipt(receipt, required))

        del receipt["capabilities"]["path-swap-races"]
        with self.assertRaisesRegex(ValueError, "missing capabilities"):
            self.probe.validate_capability_receipt(receipt, required)

    def test_result_serialization_is_deterministic_and_redacted(self):
        secret = "ghp_" + ("A" * 36)
        result = self.probe.empty_probe_result_for_test()
        result["command_records"].append(
            {"name": "sample", "returncode": 1, "stdout_sha256": "0" * 64, "stderr_sha256": "1" * 64}
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "first.json"
            second = Path(temporary_directory) / "second.json"
            self.probe.write_result(first, result)
            self.probe.write_result(second, json.loads(json.dumps(result)))
            first_bytes = first.read_bytes()
            second_bytes = second.read_bytes()
            payload = first_bytes.decode("utf-8")

        self.assertEqual(first_bytes, second_bytes)
        self.assertNotIn(secret, payload)


if __name__ == "__main__":
    unittest.main()
