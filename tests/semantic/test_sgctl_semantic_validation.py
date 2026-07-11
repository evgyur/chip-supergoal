import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class SgctlSemanticValidationTest(unittest.TestCase):
    def run_sgctl(self, *args):
        return subprocess.run([sys.executable, "scripts/sgctl.py", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_validate_contract_accepts_example(self):
        result = self.run_sgctl("validate-contract", "examples/brownfield-feature/CONTRACT.json", "--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validate_phase_rejects_known_bad_fixture_with_stable_codes(self):
        result = self.run_sgctl("validate-phase-markdown", "tests/fixtures/v2-invalid/phase-99-of-1-rpd-mismatch.md", "--format", "json")
        self.assertNotEqual(result.returncode, 0)
        codes = {d["code"] for d in json.loads(result.stdout)}
        self.assertIn("SGV-PHASE-ORDINAL-OUT-OF-RANGE", codes)
        self.assertIn("SGV-PHASE-COUNT-MISMATCH", codes)
        self.assertIn("SGV-PHASE-RPD-MISMATCH", codes)

    def test_validate_loop_rejects_known_bad_fixture_with_stable_code(self):
        result = self.run_sgctl("validate-loop-design", "--instantiated", "tests/fixtures/v2-invalid/loop-one-word.md", "--format", "json")
        self.assertNotEqual(result.returncode, 0)
        codes = {d["code"] for d in json.loads(result.stdout)}
        self.assertIn("SGV-LOOP-WEAK-SECTION", codes)

    def test_validate_package_catches_launch_marker_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "package-drift"
            package.mkdir(parents=True, exist_ok=True)
            for name in ["THINKING.md", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "PROTOCOL.md", "LAUNCH_GOAL.md"]:
                (package / name).write_text(f"# {name}\n", encoding="utf-8")
            (package / "ROADMAP.md").write_text("SUPERGOAL_GOAL_BODY: wrong\n", encoding="utf-8")
            result = self.run_sgctl("validate-package", str(package), "--format", "json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SGV-PACKAGE-LAUNCH-MARKER", {d["code"] for d in json.loads(result.stdout)})

    def test_validate_package_catches_generated_view_drift_even_if_marker_ok(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "sg"
            compile_result = subprocess.run([sys.executable, "scripts/sgctl.py", "compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(package)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            (package / "ROADMAP.md").write_text((package / "ROADMAP.md").read_text() + "\nmanual drift\n", encoding="utf-8")
            result = self.run_sgctl("validate-package", str(package), "--format", "json")
            self.assertNotEqual(result.returncode, 0)
            codes = {d["code"] for d in json.loads(result.stdout)}
            self.assertIn("SGV-PACKAGE-GENERATED-DRIFT", codes)
            self.assertIn("SGV-PACKAGE-MANIFEST-HASH", codes)

    def test_validate_package_catches_manifest_file_set_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "sg"
            compile_result = subprocess.run([sys.executable, "scripts/sgctl.py", "compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(package)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            (package / "UNSEALED.md").write_text("# unsealed\n", encoding="utf-8")
            result = self.run_sgctl("validate-package", str(package), "--format", "json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SGV-PACKAGE-MANIFEST-FILESET", {d["code"] for d in json.loads(result.stdout)})

    def test_validate_package_catches_mode_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "sg"
            compile_result = subprocess.run([sys.executable, "scripts/sgctl.py", "compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(package)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            manifest_path = package / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            roadmap = next(item for item in manifest["artifacts"] if item["path"] == "ROADMAP.md")
            roadmap["mode"] = "0755"
            joined = "\n".join(
                f"{item['path']} {item['sha256']} {item['bytes']} {item['mode']}"
                for item in manifest["artifacts"]
            )
            manifest["package_fingerprint"] = hashlib.sha256(joined.encode()).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            result = self.run_sgctl("validate-package", str(package), "--format", "json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SGV-PACKAGE-MANIFEST-HASH", {d["code"] for d in json.loads(result.stdout)})

    def test_validate_package_reports_missing_generated_file_once(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "sg"
            compiled = self.run_sgctl("compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(package))
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            (package / "THINKING.md").unlink()
            result = self.run_sgctl("validate-package", str(package), "--format", "json")
            missing = [d for d in json.loads(result.stdout) if d["code"] == "SGV-PACKAGE-MISSING-FILE" and d["pointer"] == "/THINKING.md"]
            self.assertEqual(len(missing), 1, missing)

    def test_validate_package_sanitizes_malformed_contract_details(self):
        import tempfile
        secret = "package-private-token"
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "sg"
            compiled = self.run_sgctl("compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(package))
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            contract = json.loads((package / "CONTRACT.json").read_text(encoding="utf-8"))
            contract["contract_revision"] = secret
            (package / "CONTRACT.json").write_text(json.dumps(contract), encoding="utf-8")
            result = self.run_sgctl("validate-package", str(package), "--format", "json")
            self.assertIn("SGV-PACKAGE-CONTRACT-MALFORMED", {d["code"] for d in json.loads(result.stdout)})
            self.assertNotIn(secret, result.stdout + result.stderr)

if __name__ == "__main__":
    unittest.main()
