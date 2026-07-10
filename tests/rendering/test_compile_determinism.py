import filecmp
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class CompileDeterminismTest(unittest.TestCase):
    def compile_to(self, out: Path):
        result = subprocess.run([sys.executable, "scripts/sgctl.py", "compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(out)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compile_outputs_required_files_and_single_launch_marker(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sg"
            self.compile_to(out)
            for rel in ["CONTRACT.json", "MANIFEST.json", "THINKING.md", "RESEARCH.md", "reports/research.json", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "PROTOCOL.md", "LAUNCH_GOAL.md", "phases/phase-01.md"]:
                self.assertTrue((out / rel).is_file(), rel)
            hits = []
            for p in out.rglob("*.md"):
                for i, line in enumerate(p.read_text().splitlines(), 1):
                    if line.startswith("SUPERGOAL_GOAL_BODY:"):
                        hits.append(f"{p.relative_to(out)}:{i}")
            self.assertEqual(len(hits), 1)
            self.assertTrue(hits[0].startswith("LAUNCH_GOAL.md:"))

    def test_recompile_is_byte_stable_including_launch_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            out1 = Path(td) / "a"; out2 = Path(td) / "b"
            self.compile_to(out1); self.compile_to(out2)
            comparable = ["CONTRACT.json", "THINKING.md", "RESEARCH.md", "reports/research.json", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "PROTOCOL.md", "LAUNCH_GOAL.md", "MANIFEST.json", "phases/phase-01.md"]
            for rel in comparable:
                self.assertTrue(filecmp.cmp(out1 / rel, out2 / rel, shallow=False), rel)

class CompileSafetyTest(unittest.TestCase):
    def run_compile(self, out: Path):
        return subprocess.run([sys.executable, "scripts/sgctl.py", "compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(out)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_compile_refuses_unsealed_existing_directory(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "not-a-package"
            out.mkdir()
            (out / "important.txt").write_text("do not delete\n", encoding="utf-8")
            result = self.run_compile(out)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((out / "important.txt").is_file())
            self.assertIn("sealed chip-supergoal package", result.stderr + result.stdout)

    def test_compile_refuses_runtime_package(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sg"
            ok = self.run_compile(out)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            runtime = out / "runtime"
            runtime.mkdir()
            (runtime / "STATE.json").write_text('{"live": true}\n', encoding="utf-8")
            result = self.run_compile(out)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((runtime / "STATE.json").is_file())
            self.assertIn("runtime", result.stderr + result.stdout)

    def test_compile_refuses_source_container(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_compile(ROOT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source", result.stderr + result.stdout)

if __name__ == "__main__":
    unittest.main()
