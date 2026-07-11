import filecmp
from copy import deepcopy
import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.events import read_events, verify_event_chain
from chip_supergoal.state import StateStore, read_state

class CompileDeterminismTest(unittest.TestCase):
    def compile_to(self, out: Path):
        result = subprocess.run([sys.executable, "scripts/sgctl.py", "compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(out)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compile_outputs_required_files_and_single_launch_marker(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sg"
            self.compile_to(out)
            for rel in ["CONTRACT.json", "MANIFEST.json", "THINKING.md", "RESEARCH.md", "reports/research.json", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "runtime/STATE.json", "runtime/events.jsonl", "runtime/evidence.json", "PROTOCOL.md", "LAUNCH_GOAL.md", "phases/phase-01.md", "scripts/sgctl.py", "lib/chip_supergoal/validate.py", "templates/PROTOCOL.md", "spec/risk-policy.json", "profiles/chip-private.json"]:
                self.assertTrue((out / rel).is_file(), rel)
            hits = []
            for p in out.rglob("*.md"):
                if p.relative_to(out).as_posix().startswith("templates/"):
                    continue
                for i, line in enumerate(p.read_text().splitlines(), 1):
                    if line.startswith("SUPERGOAL_GOAL_BODY:"):
                        hits.append(f"{p.relative_to(out)}:{i}")
            self.assertEqual(len(hits), 1)
            self.assertTrue(hits[0].startswith("LAUNCH_GOAL.md:"))

    def test_sealed_plane_is_byte_stable_separately_from_mutable_event_timestamps(self):
        with tempfile.TemporaryDirectory() as td:
            out1 = Path(td) / "a"; out2 = Path(td) / "b"
            self.compile_to(out1); self.compile_to(out2)
            manifest1 = json.loads((out1 / "MANIFEST.json").read_text(encoding="utf-8"))
            manifest2 = json.loads((out2 / "MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest1, manifest2)
            for rel in [item["path"] for item in manifest1["artifacts"]]:
                self.assertTrue(filecmp.cmp(out1 / rel, out2 / rel, shallow=False), rel)
            for rel in ["STATE.md", "runtime/STATE.json", "runtime/evidence.json"]:
                self.assertTrue(filecmp.cmp(out1 / rel, out2 / rel, shallow=False), rel)
            for out in (out1, out2):
                events = read_events(out / "runtime/events.jsonl")
                self.assertEqual(len(events), 1)
                self.assertEqual(verify_event_chain(events), [])
                self.assertIn("timestamp", events[0])

    def test_launch_hydrates_context_preflight_and_resolved_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sg"
            self.compile_to(out)
            launch = (out / "LAUNCH_GOAL.md").read_text(encoding="utf-8")
            resolved = json.loads((out / "CONTRACT.json").read_text(encoding="utf-8"))

            for text in [
                "CONTRACT.json",
                "THINKING.md",
                "RESEARCH.md",
                "LOOP_DESIGN.md",
                "ROADMAP.md",
                "STATE.md",
                "runtime/STATE.json",
                "phases/phase-*.md",
                "python scripts/sgctl.py validate-package . --strict",
                "python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated",
                "python scripts/sgctl.py validate-phase-markdown phases/phase-01.md",
                "Delivery boundary",
                "Approval boundary",
                "Dispatch status: continue until final audit passes",
            ]:
                self.assertIn(text, launch)
            self.assertIn(resolved["delivery"]["transport"], launch)
            self.assertIn("not declared by CONTRACT.json", launch)

    def test_launch_omits_research_context_when_no_research_artifact_is_emitted(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            data = json.loads(
                (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                    encoding="utf-8"
                )
            )
            data["profile"] = "public-clean"
            data["risks"] = []
            for phase in data["phases"]:
                phase["risk_tags"] = []
                phase["rpd"] = {"required": False, "focus": []}
            data["compatibility"].pop("research_gate", None)
            source = parent / "without-research.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/sgctl.py",
                    "compile",
                    str(source),
                    "--out",
                    str(parent / "sg"),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            package = parent / "sg"
            self.assertFalse((package / "RESEARCH.md").exists())
            self.assertNotIn(
                "RESEARCH.md",
                (package / "LAUNCH_GOAL.md").read_text(encoding="utf-8"),
            )

    def test_swapped_phase_array_compiles_files_and_roadmap_by_ordinal(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            data = json.loads(
                (ROOT / "examples/brownfield-feature/CONTRACT.json").read_text(
                    encoding="utf-8"
                )
            )
            phase_one = data["phases"][0]
            phase_two = deepcopy(phase_one)
            phase_two.update(
                {
                    "id": "P02",
                    "ordinal": 2,
                    "name": "Verify fixture",
                    "task": "Verify the ordinally compiled fixture",
                    "depends_on": ["P01"],
                }
            )
            phase_two["work_items"][0]["id"] = "P02-W01"
            phase_two["deliverables"][0].update(
                {"id": "P02-D01", "path": "fixture-verified.txt"}
            )
            phase_two["criteria"][0]["id"] = "P02-C01"
            phase_two["criteria"][0]["verifier"]["command_id"] = "P02-CMD01"
            phase_two["commands"][0]["id"] = "P02-CMD01"
            data["phases"] = [phase_two, phase_one]

            source = parent / "swapped.json"
            package = parent / "package"
            source.write_text(json.dumps(data), encoding="utf-8")
            compiled = subprocess.run(
                [
                    sys.executable,
                    "scripts/sgctl.py",
                    "compile",
                    str(source),
                    "--out",
                    str(package),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)

            state = json.loads(
                (package / "runtime/STATE.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["current_phase_id"], "P01")
            self.assertTrue(
                (package / "phases/phase-01.md")
                .read_text(encoding="utf-8")
                .startswith("# P01 —")
            )
            self.assertTrue(
                (package / "phases/phase-02.md")
                .read_text(encoding="utf-8")
                .startswith("# P02 —")
            )
            roadmap = (package / "ROADMAP.md").read_text(encoding="utf-8")
            self.assertLess(roadmap.index("- P01:"), roadmap.index("- P02:"))
            self.assertLess(roadmap.index("### P01 —"), roadmap.index("### P02 —"))

            validated = subprocess.run(
                [
                    sys.executable,
                    "scripts/sgctl.py",
                    "validate-package",
                    str(package),
                    "--strict",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(
                validated.returncode, 0, validated.stdout + validated.stderr
            )

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
            store = StateStore(out)
            state = read_state(store.state_json)
            store.transition("PLAN_REVIEWED", expected_revision=state.state_revision)
            result = self.run_compile(out)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(read_state(store.state_json).state_revision, 2)
            self.assertIn("started runtime", result.stderr + result.stdout)

    def test_compile_allows_pristine_package_recompile(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sg"
            first = self.run_compile(out)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

            second = self.run_compile(out)

            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(read_state(out / "runtime/STATE.json").state_revision, 1)

    def test_private_staging_validation_leaves_no_operation_lock_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            out = parent / "sg"
            result = self.run_compile(out)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            orphaned = [
                path.name
                for path in parent.glob(".*.operation.lock")
                if path.name != ".sg.operation.lock"
            ]
            self.assertEqual(orphaned, [])

    def test_compile_refuses_source_container(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_compile(ROOT)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source", result.stderr + result.stdout)

if __name__ == "__main__":
    unittest.main()
