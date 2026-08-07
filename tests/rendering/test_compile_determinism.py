import filecmp
import hashlib
import json
import os
import stat
import subprocess
import sys
import tarfile
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

            roadmap = (out / "ROADMAP.md").read_text(encoding="utf-8")
            phase = (out / "phases/phase-01.md").read_text(encoding="utf-8")
            launch = (out / "LAUNCH_GOAL.md").read_text(encoding="utf-8")
            for text in [roadmap, phase]:
                self.assertIn("Deliverables", text)
                self.assertIn("P01-D01", text)
                self.assertIn("fixture.txt", text)
            self.assertIn("CONTRACT.json", launch)

    def test_compile_emits_file_first_runtime_seed_bundle_and_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sg"
            self.compile_to(out)
            seed_names = ["PLAN.md", "TODO.md", "MEMORY.md", "STATUS.md", "RUN_LOG.md", "CHECKS.md", "REVIEW.md"]
            for name in seed_names:
                self.assertTrue((out / "runtime-seed" / name).is_file(), name)

            plan = (out / "runtime-seed/PLAN.md").read_text(encoding="utf-8")
            todo = (out / "runtime-seed/TODO.md").read_text(encoding="utf-8")
            memory = (out / "runtime-seed/MEMORY.md").read_text(encoding="utf-8")
            status = (out / "runtime-seed/STATUS.md").read_text(encoding="utf-8")
            checks = (out / "runtime-seed/CHECKS.md").read_text(encoding="utf-8")
            review = (out / "runtime-seed/REVIEW.md").read_text(encoding="utf-8")
            run_log = (out / "runtime-seed/RUN_LOG.md").read_text(encoding="utf-8")

            self.assertIn("sg-20260625-brownfield-feature", plan)
            self.assertIn("P01", plan)
            self.assertIn("P01 | pending", todo)
            for heading in ["## Verified facts", "## Decisions", "## Constraints", "## Mistakes to avoid"]:
                self.assertIn(heading, memory)
            self.assertIn("active_todo: P01", status)
            self.assertIn("phase: READY_TO_DISPATCH", status)
            self.assertIn("python3 -m unittest", checks)
            self.assertIn("P01-C01", checks)
            self.assertIn("RPD_PLAN_REVIEW", review)
            self.assertIn("EVT-000001", run_log)

            protocol = (out / "PROTOCOL.md").read_text(encoding="utf-8")
            launch = (out / "LAUNCH_GOAL.md").read_text(encoding="utf-8")
            for text in [protocol, launch]:
                self.assertIn("runtime-seed", text)
                self.assertIn("out/runtime", text)
                for name in ["PLAN.md", "TODO.md", "MEMORY.md", "STATUS.md", "RUN_LOG.md"]:
                    self.assertIn(name, text)

            manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
            manifested = {record["path"] for record in manifest["artifacts"]}
            for name in seed_names:
                self.assertIn(f"runtime-seed/{name}", manifested)

    def test_runtime_initializer_is_idempotent_and_never_overwrites_live_state(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sg"
            self.compile_to(out)
            init = out / "scripts/init-runtime.sh"
            self.assertTrue(init.is_file())
            first = subprocess.run(["bash", str(init), str(out)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            runtime = out / "out/runtime"
            self.assertTrue(runtime.is_dir())
            for name in ["PLAN.md", "TODO.md", "MEMORY.md", "STATUS.md", "RUN_LOG.md", "CHECKS.md", "REVIEW.md"]:
                self.assertTrue((runtime / name).is_file(), name)

            status = runtime / "STATUS.md"
            status.write_text(status.read_text(encoding="utf-8") + "- live_probe: keep\n", encoding="utf-8")
            second = subprocess.run(["bash", str(init), str(out)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("already initialized", second.stdout)
            self.assertIn("live_probe: keep", status.read_text(encoding="utf-8"))

    def test_recompile_is_byte_stable_including_launch_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            out1 = Path(td) / "a"; out2 = Path(td) / "b"
            self.compile_to(out1); self.compile_to(out2)
            comparable = ["CONTRACT.json", "THINKING.md", "RESEARCH.md", "reports/research.json", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "PROTOCOL.md", "LAUNCH_GOAL.md", "MANIFEST.json", "phases/phase-01.md"]
            for rel in comparable:
                self.assertTrue(filecmp.cmp(out1 / rel, out2 / rel, shallow=False), rel)

    def test_complete_package_contains_every_manifest_file_and_preserves_modes(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sg"
            self.compile_to(out)
            command = ["bash", str(out / "templates/delivery/package-complete-supergoal.sh")]
            env = dict(os.environ, SUPERGOAL_ROOT=str(out))
            first = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            lines = [line for line in first.stdout.splitlines() if line.strip()]
            self.assertEqual(len(lines), 3, lines)
            archive = Path(lines[0])
            receipt = json.loads(Path(lines[2]).read_text(encoding="utf-8"))
            self.assertTrue(receipt["ok"])
            self.assertEqual(receipt["fileset"], "MANIFEST.json.artifacts + present MANIFEST.json.mutable_paths + MANIFEST.json")
            self.assertEqual(receipt["extracted_strict_validation"], "passed")
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), receipt["sha256"])

            manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
            expected = {record["path"] for record in manifest["artifacts"]} | {"MANIFEST.json"}
            for rel in manifest.get("mutable_paths", []):
                if (out / rel).exists():
                    expected.add(rel)
            extracted = Path(td) / "extracted"
            with tarfile.open(archive, "r:gz") as tar:
                self.assertEqual(set(tar.getnames()), expected)
                self.assertEqual(len(tar.getnames()), len(expected))
                tar.extractall(extracted, filter="data")
            for record in manifest["artifacts"]:
                mode = stat.S_IMODE((extracted / record["path"]).stat().st_mode)
                self.assertEqual(f"{mode:04o}", record["mode"], record["path"])
            strict = subprocess.run(
                [sys.executable, str(extracted / "scripts/sgctl.py"), "validate-package", str(extracted), "--strict", "--format", "json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)

            second = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(lines[1], [line for line in second.stdout.splitlines() if line.strip()][1])


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
