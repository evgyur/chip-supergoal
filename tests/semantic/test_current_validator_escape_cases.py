import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class CurrentValidatorEscapeCases(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/sgctl.py"), *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_phase_99_of_1_with_rpd_mismatch_is_rejected(self):
        fixture = ROOT / "tests/fixtures/v2-invalid/phase-99-of-1-rpd-mismatch.md"
        result = self.run_cli("validate-phase-markdown", str(fixture))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_one_word_loop_design_is_rejected(self):
        fixture = ROOT / "tests/fixtures/v2-invalid/loop-one-word.md"
        result = self.run_cli(
            "validate-loop-design", str(fixture), "--instantiated"
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_v2_valid_fixtures_still_pass_native_python_authority(self):
        phase = ROOT / "tests/fixtures/v2-valid/phase-valid.md"
        loop = ROOT / "tests/fixtures/v2-valid/loop-design-valid.md"
        phase_result = self.run_cli("validate-phase-markdown", str(phase))
        loop_result = self.run_cli(
            "validate-loop-design", str(loop), "--instantiated"
        )
        self.assertEqual(phase_result.returncode, 0, phase_result.stdout + phase_result.stderr)
        self.assertEqual(loop_result.returncode, 0, loop_result.stdout + loop_result.stderr)

if __name__ == "__main__":
    unittest.main()
