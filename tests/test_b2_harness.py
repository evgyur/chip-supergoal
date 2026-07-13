from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_PATH = ROOT / "evals" / "b2" / "run.py"
PRIVACY_PATH = ROOT / "evals" / "b2" / "privacy_scan.py"
MANIFEST_PATH = ROOT / "evals" / "b2" / "b2-audit-manifest.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class B2HarnessContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_module(RUN_PATH, "b2_audit_runner")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_accounts_for_all_commits_and_changed_files_once(self):
        facts = self.runner.validate_manifest(self.manifest, ROOT)

        self.assertEqual(facts["observed_commit_count"], 29)
        self.assertEqual(facts["observed_changed_file_count"], 151)
        self.assertEqual(facts["accounted_commit_count"], 29)
        self.assertEqual(facts["accounted_changed_file_count"], 151)
        self.assertEqual(len(self.manifest["clusters"]), 5)
        self.assertEqual(self.manifest["compositions"][0]["id"], "main")
        self.assertEqual(self.manifest["compositions"][-1]["id"], "hardening-whole")

    def test_manifest_freezes_measurement_and_five_reviewed_false_greens(self):
        measurement = self.manifest["measurement"]
        self.assertGreaterEqual(measurement["measured_repetitions"], 5)
        self.assertGreaterEqual(measurement["warmup_repetitions"], 1)
        self.assertEqual(measurement["compile_p50_max_regression_pct"], 10)
        self.assertEqual(measurement["compile_p95_max_regression_pct"], 20)
        self.assertEqual(measurement["package_size_max_regression_pct"], 25)

        fixtures = self.manifest["semantic_false_green_fixtures"]
        self.assertEqual(len(fixtures), 5)
        self.assertEqual(len({item["id"] for item in fixtures}), 5)
        for item in fixtures:
            fixture = json.loads((ROOT / item["path"]).read_text(encoding="utf-8"))
            self.assertEqual(fixture["id"], item["id"])
            self.assertTrue(fixture["expected_defect"])
            self.assertEqual(fixture["review"]["verdict"], "confirmed_false_green")
            self.assertTrue(fixture["review"]["reviewer"])

    def test_verify_rejects_disallowed_decision_or_unresolved_findings(self):
        report = self.runner.empty_report_for_test("invented")
        dispositions = self.runner.empty_dispositions_for_test()
        with self.assertRaisesRegex(ValueError, "branch decision"):
            self.runner.verify_report(report, dispositions, require_zero_p0_p1=True)

        report = self.runner.empty_report_for_test("adopt_whole")
        report["unresolved_findings"] = [{"severity": "P1", "id": "P1-test"}]
        with self.assertRaisesRegex(ValueError, "P0/P1"):
            self.runner.verify_report(report, dispositions, require_zero_p0_p1=True)

    def test_verify_accepts_complete_allowed_report(self):
        report = self.runner.empty_report_for_test("adopt_whole")
        dispositions = self.runner.empty_dispositions_for_test()

        result = self.runner.verify_report(
            report,
            dispositions,
            require_zero_p0_p1=True,
        )

        self.assertEqual(result["decision"], "adopt_whole")
        self.assertEqual(result["unresolved_p0_p1"], 0)
        self.assertEqual(result["cluster_count"], 5)

    def test_absolute_cost_exception_is_explicit_and_bounded(self):
        exceptions = self.runner.performance_exceptions(
            compile_p50_seconds=0.258,
            compile_p95_seconds=0.272,
            archive_p50_seconds=0.190,
            archive_p95_seconds=0.220,
            package_bytes=743321,
            compile_p50_regression_pct=309.4,
            compile_p95_regression_pct=324.5,
            archive_p50_regression_pct=41.0,
            archive_p95_regression_pct=48.0,
            package_size_regression_pct=2350.4,
        )

        self.assertEqual(
            {item["metric"] for item in exceptions},
            {"compile_p50", "compile_p95", "archive_p50", "archive_p95", "package_size"},
        )
        self.assertTrue(all(item["bounded_absolute_cost"] for item in exceptions))
        self.assertTrue(all(item["rationale"] for item in exceptions))


class B2PrivacyScanTests(unittest.TestCase):

    def test_privacy_scan_reports_location_without_echoing_secret(self):
        privacy = load_module(PRIVACY_PATH, "b2_privacy_scan")
        secret = "ghp_" + ("A" * 36)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "evidence.json"
            path.write_text(f'{{"token":"{secret}"}}\n', encoding="utf-8")
            violations = privacy.scan_files(root, [path])

        self.assertEqual(violations, ["evidence.json:1:github_token"])
        self.assertNotIn(secret, "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
