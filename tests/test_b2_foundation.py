import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FoundationMaterializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.materialize = load_module("materialize_foundation", "evals/b2/materialize_foundation.py")
        cls.verify_foundation = load_module("verify_foundation", "evals/b2/verify_foundation.py")
        cls.verify_closeout = load_module("verify_closeout", "evals/b2/verify_closeout.py")

    def test_materialized_records_bind_selected_and_rollback_shas(self):
        capabilities, provenance = self.materialize.build_records(
            ROOT,
            adr=ROOT / "docs/adr/ADR-003-b2-adoption.md",
            main_sha="35a22fe5bc4821559d9a186579bc1ea07ad6ac33",
            hardening_sha="5725192154dfca78032e861edbd29570bb2d94e8",
            plan_sha256="a269af6b6f7190a383d090430ec7ad155c474aa49646d15321d115c4177f132e",
        )
        self.assertEqual(capabilities["status"], "pass")
        self.assertEqual(capabilities["selected_foundation_sha"], provenance["selected_foundation_sha"])
        self.assertNotEqual(provenance["selected_foundation_sha"], provenance["rollback_sha"])
        self.assertEqual(provenance["commit_count"], 29)
        self.assertEqual(provenance["changed_file_count"], 151)

    def test_foundation_verifier_rejects_plain_main(self):
        capabilities = {
            "status": "pass",
            "selected_foundation_sha": "a" * 40,
            "rollback_sha": "a" * 40,
            "native_windows_v1": {"status": "pass", "python_versions": ["3.11.9", "3.13.14"]},
            "linux_parity": {"status": "pass"},
        }
        provenance = {
            "selected_foundation_sha": "a" * 40,
            "rollback_sha": "a" * 40,
            "capabilities_sha256": "unused",
        }
        with self.assertRaisesRegex(ValueError, "plain main"):
            self.verify_foundation.verify_records(
                capabilities,
                provenance,
                required_capability="native_windows_v1",
                windows_versions=["3.11", "3.13"],
                require_linux_parity=True,
            )

    def test_closeout_rejects_plan_hash_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "plan.md"
            plan.write_text("drifted\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "plan SHA-256"):
                self.verify_closeout.build_closeout(
                    plan=plan,
                    expected_plan_sha256="0" * 64,
                    capabilities_path=ROOT / "evals/baselines/b2-branch-comparison.json",
                    provenance_path=ROOT / "evals/b2/b2-disposition-manifest.json",
                )


if __name__ == "__main__":
    unittest.main()
