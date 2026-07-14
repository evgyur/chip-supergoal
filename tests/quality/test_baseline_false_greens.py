import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "evals/baselines/v3-baseline-manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BaselineFalseGreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_baseline_is_bound_to_selected_foundation_and_profile_off(self):
        self.assertEqual(self.manifest["schema_version"], "v3-baseline-manifest-v1")
        self.assertEqual(
            self.manifest["foundation"]["selected_sha"],
            "5725192154dfca78032e861edbd29570bb2d94e8",
        )
        self.assertNotEqual(
            self.manifest["foundation"]["selected_sha"],
            self.manifest["foundation"]["rollback_sha"],
        )
        self.assertEqual(self.manifest["profile_off"]["status"], "pass")
        self.assertEqual(len(self.manifest["representative_packages"]), 3)
        self.assertTrue(all(item["package_fingerprint"] for item in self.manifest["representative_packages"]))

    def test_all_five_false_greens_preserve_structural_pass_and_semantic_failure(self):
        fixtures = self.manifest["false_green_fixtures"]
        self.assertEqual([item["id"] for item in fixtures], [f"B2-FG-0{i}" for i in range(1, 6)])
        for item in fixtures:
            path = ROOT / item["path"]
            fixture = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(sha256(path), item["sha256"])
            self.assertEqual(fixture["id"], item["id"])
            fragment = fixture["plan_fragment"]
            self.assertIsInstance(fragment, dict)
            self.assertTrue(fragment)
            self.assertTrue(all(value not in (None, "", [], {}) for value in fragment.values()))
            self.assertEqual(item["legacy_structural_validation"], "pass")
            self.assertEqual(item["independent_semantic_truth"], "fail")
            self.assertTrue(fixture["expected_defect"])
            self.assertEqual(fixture["review"]["verdict"], "confirmed_false_green")
            self.assertEqual(fixture["review"]["reviewer"], "standard-hermes-goal-rpd")

    def test_independent_review_receipts_are_hash_bound(self):
        review = self.manifest["independent_review"]
        path = ROOT / review["path"]
        value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sha256(path), review["sha256"])
        self.assertTrue(value["implementation_independent"])
        self.assertEqual(len(value["fixtures"]), 5)
        self.assertTrue(all(item["verdict"] == "confirmed_false_green" for item in value["fixtures"]))
        rpd = self.manifest["rpd_review"]
        rpd_path = ROOT / rpd["path"]
        rpd_value = json.loads(rpd_path.read_text(encoding="utf-8"))
        self.assertEqual(sha256(rpd_path), rpd["sha256"])
        self.assertEqual(rpd_value["verdict"], "READY FOR DISCUSSION")
        self.assertEqual(rpd_value["unresolved_p0_p1"], 0)

    def test_prompt_reference_and_compiler_inputs_are_git_pinned(self):
        for key in ("prompt_reference_set", "compiler_adapter"):
            records = self.manifest[key]
            self.assertTrue(records)
            for record in records:
                self.assertEqual(len(record["git_blob_sha"]), 40)
                self.assertEqual(len(record["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
