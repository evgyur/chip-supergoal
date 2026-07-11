from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "test.py"
CROSS_FILE_PATH = ROOT / "scripts" / "check-cross-file-consistency.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("chip_supergoal_native_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load native runner: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_cross_file_checker():
    spec = importlib.util.spec_from_file_location(
        "chip_supergoal_cross_file_checker",
        CROSS_FILE_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load cross-file checker: {CROSS_FILE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NativeRunnerTests(unittest.TestCase):
    def _write_cross_file_fixture(
        self,
        root: Path,
        *,
        declared_total: int = 2,
    ) -> None:
        phases = root / "phases"
        phases.mkdir(parents=True)
        (root / "LAUNCH_GOAL.md").write_text(
            "SUPERGOAL_GOAL_BODY: execute this package\n",
            encoding="utf-8",
        )
        (root / "ROADMAP.md").write_text("# Roadmap\n", encoding="utf-8")
        for ordinal in (1, 2):
            (phases / f"phase-{ordinal:02d}.md").write_text(
                f"SUPERGOAL_PHASE_START\n"
                f"Phase: {ordinal} of {declared_total} — phase {ordinal}\n",
                encoding="utf-8",
            )

    def _directory_link(self, link: Path, target: Path) -> None:
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"junction creation unavailable: {result.stderr}")
        else:
            link.symlink_to(target, target_is_directory=True)

    def _remove_directory_link(self, link: Path) -> None:
        if not os.path.lexists(link):
            return
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()

    def test_sgctl_reconfigures_cp1251_stdio_to_utf8(self):
        environment = dict(os.environ)
        environment.pop("PYTHONUTF8", None)
        environment["PYTHONIOENCODING"] = "cp1251:strict"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "package-🙂"
            result = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8=0",
                    ROOT / "scripts" / "sgctl.py",
                    "compile",
                    ROOT / "examples" / "brownfield-feature" / "CONTRACT.json",
                    "--out",
                    output,
                ],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        diagnostic = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, diagnostic)
        self.assertEqual(result.stderr, b"")
        self.assertIn("package-🙂", result.stdout.decode("utf-8"))

    def test_user_story_paths_are_posix_serialized(self):
        result = subprocess.run(
            [sys.executable, ROOT / "scripts" / "test-user-stories.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("USER_STORY_TESTS total=55 passed=55 failed=0", result.stdout)

    def test_cross_file_consistency_entrypoint_runs_natively(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory) / "package with space 🙂"
            self._write_cross_file_fixture(package_root)
            result = subprocess.run(
                [sys.executable, CROSS_FILE_PATH, package_root],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "CROSS_FILE_CONSISTENCY_PASS phases=2 launch=LAUNCH_GOAL.md:1",
            result.stdout,
        )

    def test_cross_file_consistency_entrypoint_rejects_phase_total_drift(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory) / "package"
            self._write_cross_file_fixture(package_root, declared_total=3)
            result = subprocess.run(
                [sys.executable, CROSS_FILE_PATH, package_root],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "phase-01.md declares total 3; discovered 2 phase files",
            result.stderr,
        )

    def test_cross_file_consistency_bounds_tree_entries(self):
        checker = load_cross_file_checker()
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory) / "package"
            self._write_cross_file_fixture(package_root)
            with mock.patch.object(checker, "MAX_TREE_ENTRIES", 2):
                result = checker.inspect_cross_file_consistency(package_root)

        self.assertEqual(
            result.errors,
            ("tree entry count exceeds 2-entry limit",),
        )

    def test_cross_file_consistency_bounds_each_markdown_file(self):
        checker = load_cross_file_checker()
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory) / "package"
            self._write_cross_file_fixture(package_root)
            with mock.patch.object(checker, "MAX_MARKDOWN_BYTES", 20):
                result = checker.inspect_cross_file_consistency(package_root)

        self.assertIn(
            "Markdown exceeds 20-byte limit: LAUNCH_GOAL.md",
            result.errors,
        )

    def test_cross_file_consistency_bounds_total_markdown_bytes(self):
        checker = load_cross_file_checker()
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory) / "package"
            self._write_cross_file_fixture(package_root)
            with mock.patch.object(
                checker,
                "MAX_TOTAL_MARKDOWN_BYTES",
                50,
            ):
                result = checker.inspect_cross_file_consistency(package_root)

        self.assertIn(
            "Markdown total exceeds 50-byte limit",
            result.errors,
        )

    def test_aggregate_runner_uses_current_interpreter(self):
        runner = load_runner()
        plan = runner.build_test_plan(ROOT)

        self.assertTrue(plan.python_commands)
        self.assertTrue(
            all(command[0] == sys.executable for command in plan.python_commands)
        )
        flattened = [str(argument).lower() for gate in plan.gates for argument in gate.command]
        self.assertNotIn("bash", flattened)
        self.assertNotIn("wsl", flattened)

    def test_python_command_inventory_cannot_filter_a_wrong_launcher(self):
        runner = load_runner()
        wrong = runner.TestGate(
            "wrong-python",
            ("python3", "wrong.py"),
            uses_python=True,
        )
        plan = runner.TestPlan(root=ROOT, gates=(wrong,))

        self.assertEqual(plan.python_commands, (wrong.command,))
        self.assertFalse(
            all(command[0] == sys.executable for command in plan.python_commands)
        )

    def test_aggregate_runner_stops_at_first_failing_gate(self):
        runner = load_runner()
        plan = runner.TestPlan(
            root=ROOT,
            gates=(
                runner.TestGate("first", (sys.executable, "first.py")),
                runner.TestGate("second", (sys.executable, "second.py")),
                runner.TestGate("never", (sys.executable, "never.py")),
            ),
        )
        completed = (
            subprocess.CompletedProcess(plan.gates[0].command, 0),
            subprocess.CompletedProcess(plan.gates[1].command, 7),
        )
        output = io.StringIO()

        with mock.patch.object(runner.subprocess, "run", side_effect=completed) as run:
            with redirect_stdout(output):
                returncode = runner.run_test_plan(plan)

        self.assertEqual(returncode, 7)
        self.assertEqual(run.call_count, 2)
        self.assertIn(
            "NATIVE_TEST_SUMMARY total=3 passed=1 failed=1 first_failed=second",
            output.getvalue(),
        )

    def test_relative_paths_have_platform_independent_serialization(self):
        runner = load_runner()

        relative = runner.relative_posix(
            ROOT / "templates" / "LAUNCH_GOAL.md",
            ROOT,
        )

        self.assertEqual(relative, "templates/LAUNCH_GOAL.md")

    def test_privacy_scan_covers_force_tracked_runtime_paths_and_html_lines(self):
        runner = load_runner()
        secret = "ghp_" + ("A" * 24)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tracked = root / ".shaw" / "tracked.txt"
            tracked.parent.mkdir()
            tracked.write_text(f"<note>{secret}</note>\n", encoding="utf-8")
            subprocess.run(
                ["git", "init", "--quiet", root],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", root, "add", "--force", ".shaw/tracked.txt"],
                check=True,
                capture_output=True,
            )

            violations = runner._check_privacy(root)

        self.assertTrue(
            any(item.startswith(".shaw/tracked.txt:1:github_token") for item in violations),
            violations,
        )
        self.assertTrue(all(secret not in item for item in violations), violations)

    def test_privacy_scan_never_exempts_token_shaped_angle_content(self):
        runner = load_runner()
        placeholder = "ghp_EXAMPLE_" + ("P" * 20)
        exposed = "ghp_" + ("E" * 24)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sample.txt").write_text(
                f"example <{placeholder}>\n"
                f"<div>{exposed}</div>\n"
                f'<a data-token="{exposed}">link</a>\n',
                encoding="utf-8",
            )

            violations = runner._check_privacy(root)

        self.assertEqual(
            violations,
            [
                "sample.txt:1:github_token",
                "sample.txt:2:github_token",
                "sample.txt:3:github_token",
                "sample.txt:3:env_secret_assignment",
            ],
        )

    def test_privacy_scan_never_reads_through_tracked_directory_link(self):
        runner = load_runner()
        secret = "ghp_" + ("J" * 24)
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            root = base / "repository"
            tracked = root / "tracked"
            outside = base / "outside"
            tracked.mkdir(parents=True)
            outside.mkdir()
            (tracked / "sentinel.txt").write_text("inside\n", encoding="utf-8")
            (outside / "sentinel.txt").write_text(
                f"{secret}\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "init", "--quiet", root],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", root, "add", "tracked/sentinel.txt"],
                check=True,
                capture_output=True,
            )
            tracked.rename(root / "tracked-original")
            self._directory_link(tracked, outside)
            try:
                violations = runner._check_privacy(root)
            finally:
                self._remove_directory_link(tracked)

        self.assertEqual(violations, [])

    def test_recursive_aggregate_scanners_use_the_no_follow_tree_walk(self):
        for relative in (
            "scripts/test.py",
            "scripts/test-user-stories.py",
            "scripts/probe-upstream-goal-compat.py",
            "scripts/probe-dev-history-contracts.py",
        ):
            contents = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertIn("iter_tree_no_follow", contents)
                self.assertNotIn(".rglob(", contents)
                self.assertNotIn("os.walk(", contents)

    def test_shell_wrapper_preserves_unix_behavior_gates_then_delegates(self):
        wrapper = (ROOT / "scripts" / "test.sh").read_text(encoding="utf-8")

        for contract in (
            "bash -n",
            "shellcheck",
            "shfmt -d -i 2",
            "--shell-only",
            "scripts/validate-loop-design.sh",
            "scripts/validate-phase.sh",
            "scripts/repo-state.sh",
            "scripts/detect-env.sh",
            "git check-ignore",
            "python3 scripts/test.py --skip-shell",
        ):
            self.assertIn(contract, wrapper)

    def test_gitattributes_reserve_crlf_for_native_windows_launchers(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

        for pattern in (
            "*.py",
            "*.md",
            "*.json",
            "*.yaml",
            "*.yml",
            "*.csv",
            "*.txt",
            "*.sh",
        ):
            self.assertIn(f"{pattern} text eol=lf", attributes)
        self.assertIn("*.cmd text eol=crlf", attributes)
        self.assertIn("*.bat text eol=crlf", attributes)


if __name__ == "__main__":
    unittest.main()
