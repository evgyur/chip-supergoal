import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKOUT_V7_SHA = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
SETUP_PYTHON_V6_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"


def read_text(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


class ReleaseEngineeringTest(unittest.TestCase):
    def test_version_changelog_and_release_checklist_agree(self):
        version = read_text("VERSION").strip()
        changelog = read_text("CHANGELOG.md")
        checklist = read_text("docs/release-checklist.md")
        first_release_heading = next(
            line for line in changelog.splitlines() if line.startswith("## ")
        )
        self.assertTrue(
            first_release_heading.startswith(f"## {version} "),
            first_release_heading,
        )
        self.assertIn("GitHub actions are pinned", checklist)
        self.assertIn("contents: read", checklist)
        self.assertEqual(version, "3.0.0-alpha.4")

    def test_active_completion_docs_share_package_terminal_authority(self):
        authority_documents = (
            "README.md",
            "docs/README.ru.md",
            "SKILL.md",
            "references/architect-plus-v3-upgrade-execution-lessons.md",
            "references/executable-contract-review.md",
            "references/execution-state-machine.md",
            "references/final-audit-packaging.md",
            "references/follow-on-supergoal-after-completion.md",
            "references/goal-identity-and-audit-lookup.md",
            "references/live-activation-continuation-hardening.md",
            "references/standing-goal-disambiguation-and-audit-lookup.md",
            "references/supergoal-continuation-and-package-path-drift.md",
            "references/supergoal-goal-code-review-hardening.md",
            "references/supergoal-goal-pipeline-turn-yield.md",
            "references/supergoal-status-snapshots.md",
        )
        for relative in authority_documents:
            document = read_text(relative)
            with self.subTest(relative=relative):
                self.assertIn("reports/terminal-record.txt", document)
                self.assertIn("python scripts/sgctl.py validate-terminal", document)

    def test_reference_index_canonical_section_matches_catalog(self):
        catalog = json.loads(read_text("spec/reference-catalog.json"))
        expected = {
            Path(entry["path"]).name
            for entry in catalog["references"]
            if entry["status"] == "canonical" and entry["path"] != "references/INDEX.md"
        }
        index = read_text("references/INDEX.md")
        canonical_block = index.split("## Canonical references", 1)[1].split(
            "## Specialist references", 1
        )[0]
        actual = set(re.findall(r"`([^`]+\.md)`", canonical_block))
        self.assertEqual(actual, expected)
        self.assertIn("`spec/reference-catalog.json` is the status authority", index)

    def test_canary_and_traceability_describe_executed_terminal_coverage(self):
        canary = read_text("docs/canary-report.md")
        self.assertIn("reload the authoritative state in `RUNNING`", canary)
        self.assertNotIn("transition to audit/done", canary)
        traceability = read_text("docs/traceability.csv")
        self.assertIn("lib/chip_supergoal/terminal.py", traceability)
        self.assertIn("tests/security/test_terminal_authority.py", traceability)

    def test_native_cross_file_consistency_command_is_documented(self):
        command = (
            "python <installed-chip-supergoal>/scripts/"
            "check-cross-file-consistency.py <package-root>"
        )
        self.assertIn(
            command,
            read_text("references/cross-file-consistency-review-hardening.md"),
        )
        self.assertIn("scripts/check-cross-file-consistency.py", read_text("SKILL.md"))
        self.assertIn(
            '"scripts/check-cross-file-consistency.py"',
            read_text("scripts/test.py"),
        )

    def test_ci_is_split_and_actions_are_pinned(self):
        ci = read_text(".github/workflows/ci.yml")
        workflow = yaml.load(ci, Loader=yaml.BaseLoader)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        jobs = workflow["jobs"]
        for job in ("python-tests", "shell-quality", "aggregate"):
            self.assertIn(job, jobs)

        python_job = jobs["python-tests"]
        self.assertEqual(python_job["runs-on"], "${{ matrix.os }}")
        self.assertEqual(
            set(python_job["strategy"]["matrix"]["os"]),
            {"ubuntu-24.04", "windows-latest"},
        )
        self.assertEqual(
            set(python_job["strategy"]["matrix"]["python"]),
            {"3.11.9", "3.13.14"},
        )
        python_steps = {step.get("name"): step for step in python_job["steps"]}
        self.assertEqual(
            python_steps["Set up Python"]["uses"],
            f"actions/setup-python@{SETUP_PYTHON_V6_SHA}",
        )
        self.assertEqual(
            python_steps["Set up Python"]["with"]["python-version"],
            "${{ matrix.python }}",
        )
        self.assertEqual(
            python_steps["Native aggregate suite"]["run"].strip(),
            "python scripts/test.py",
        )
        self.assertEqual(
            python_steps["Install Python test dependency"]["run"].strip(),
            "python -m pip install --disable-pip-version-check -r requirements-test.txt",
        )

        shell_job = jobs["shell-quality"]
        self.assertEqual(shell_job["runs-on"], "ubuntu-24.04")
        shell_steps = {step.get("name"): step for step in shell_job["steps"]}
        install = shell_steps["Install mandatory shell tools"]["run"]
        self.assertIn("apt-get install --yes shellcheck shfmt", install)
        self.assertEqual(
            shell_steps["Shell syntax and style"]["run"].strip(),
            "bash scripts/test.sh --shell-only",
        )

        aggregate = jobs["aggregate"]
        self.assertEqual(set(aggregate["needs"]), {"python-tests", "shell-quality"})
        self.assertEqual(aggregate.get("if"), "${{ always() }}")
        aggregate_run = aggregate["steps"][0]["run"]
        for result in (
            "needs.python-tests.result",
            "needs.shell-quality.result",
            '!= "success"',
            "exit 1",
        ):
            self.assertIn(result, aggregate_run)

        uses = [
            step["uses"]
            for job in jobs.values()
            for step in job.get("steps", [])
            if "uses" in step
        ]
        self.assertTrue(uses)
        for item in uses:
            self.assertRegex(item, r"@[a-f0-9]{40}$", item)
        self.assertEqual(uses.count(f"actions/checkout@{CHECKOUT_V7_SHA}"), 2)
        self.assertEqual(uses.count(f"actions/setup-python@{SETUP_PYTHON_V6_SHA}"), 1)
        self.assertEqual(len(uses), 3, uses)
        self.assertNotIn("unavailable", ci)

    def test_cross_platform_runtime_contract_is_documented(self):
        readme = read_text("README.md")
        readme_ru = read_text("docs/README.ru.md")
        matrix = read_text("docs/compatibility-matrix.md")
        checklist = read_text("docs/release-checklist.md")
        skill = read_text("SKILL.md")
        public = "\n".join([readme, readme_ru, matrix, checklist, skill])
        for phrase in (
            "Windows",
            "Ubuntu",
            "scripts/test.py",
            "Python authority",
            "recompile",
            "external archive",
            "terminal authority",
            "privacy scan",
        ):
            self.assertIn(phrase, public)
        for document in (readme, readme_ru):
            self.assertIn("CPython 3.11.9 or newer", document)
            self.assertIn(
                "python -m pip install --disable-pip-version-check -r requirements-test.txt",
                document,
            )
            self.assertIn("python scripts/test.py", document)
            self.assertIn("python scripts/sgctl.py compile", document)
            self.assertIn("../chip-supergoal-example", document)
            self.assertNotIn("--out .supergoal/", document)
            self.assertIn("Unix-only", document)
            self.assertNotIn("python3 ", document)
            self.assertNotIn("/tmp/", document)
            self.assertIn("--authorization-out", document)
            self.assertIn("--authorization-file", document)
        for document in (matrix, checklist, skill):
            self.assertIn("CPython 3.11.9", document)
            self.assertNotIn("python3 ", document)
            self.assertNotIn("/tmp/", document)
        self.assertEqual(read_text("requirements-test.txt"), "PyYAML==6.0.3\n")
        self.assertIn(
            "python scripts/sgctl.py validate-phase-markdown <phase-file>", skill
        )
        self.assertIn("only a Unix compatibility wrapper", skill)
        self.assertNotIn(
            'Run `bash "$SUPERGOAL_DIR/scripts/validate-phase.sh"', skill
        )
        protocol = read_text("templates/PROTOCOL.md")
        self.assertIn("--authorization-out <utf8-envelope-file>", protocol)
        self.assertIn("--authorization-file <utf8-envelope-file>", protocol)

    def test_live_goalmanager_hook_is_reserved_not_release_evidence(self):
        documents = [
            read_text(relative)
            for relative in (
                "README.md",
                "docs/README.ru.md",
                "docs/compatibility-matrix.md",
                "docs/release-checklist.md",
                "docs/canary-report.md",
            )
        ]
        for document in documents:
            self.assertNotIn("SUPERGOAL_HERMES_INTEGRATION", document)
        self.assertIn("must not be counted as release evidence", "\n".join(documents))

        environment = dict(os.environ)
        environment["SUPERGOAL_HERMES_INTEGRATION"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.integration.test_live_goalmanager",
                "-v",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("skipped=1", result.stdout)

    def test_terminal_completion_docs_require_package_bound_authority(self):
        matrix = read_text("docs/compatibility-matrix.md")
        skill = read_text("SKILL.md")
        compatibility = read_text("references/upstream-goal-compatibility.md")
        probe = read_text("scripts/probe-upstream-goal-compat.py")
        self.assertIn("legacy marker trio alone means continue", matrix)
        self.assertIn("python scripts/sgctl.py validate-terminal", matrix)
        self.assertNotIn(
            "`AUDIT_COMPLETE` + `SUPERGOAL_RUN_COMPLETE` + `Goal complete: yes` means done",
            matrix,
        )
        self.assertIn(
            "validated by `python scripts/sgctl.py validate-phase-markdown`", skill
        )
        self.assertIn("without a validated package terminal record", compatibility)
        self.assertIn("'legacy_trio'", probe)
        self.assertNotIn("'full_complete'", probe)

    def test_active_contracts_use_portable_python_authority(self):
        active_contracts = (
            "AGENT_HANDOFF.md",
            "docs/traceability.csv",
            "examples/brownfield-feature/CONTRACT.json",
            "references/artifact-boundaries.md",
            "references/artifact-schemas.md",
            "references/architect-plus-v3-upgrade-execution-lessons.md",
            "references/auth-ux-polish-phase.md",
            "references/category-backed-skill-path-validation.md",
            "references/completed-standing-goal-and-workdir-hygiene.md",
            "references/core-planning-contract.md",
            "references/cross-file-consistency-review-hardening.md",
            "references/dev-history-hardening.md",
            "references/execution-state-machine.md",
            "references/ignored-supergoal-package-hygiene.md",
            "references/follow-on-supergoal-after-completion.md",
            "references/goal-format.md",
            "references/loop-design-gate.md",
            "references/markdown-report-shell-quoting.md",
            "references/nested-package-preflight.md",
            "references/phase-design.md",
            "references/repeated-approval-blocked-goal-loop.md",
            "references/repo-state-comparison.md",
            "references/research-report-to-supergoal.md",
            "references/rpd-to-supergoal-handoff.md",
            "references/skill-feature-audit-user-stories.md",
            "references/skill-package-sync.md",
            "references/supergoal-execution-root-hygiene.md",
            "references/supergoal-git-cleanup-resume.md",
        )
        for relative in active_contracts:
            with self.subTest(relative=relative):
                self.assertNotIn("python3 ", read_text(relative))
        nested = read_text("references/nested-package-preflight.md")
        self.assertIn(
            "python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md",
            nested,
        )
        self.assertIn("unnecessary on native Windows", nested)

        boundaries = read_text("references/artifact-boundaries.md")
        self.assertIn("optional Unix compatibility", boundaries)
        self.assertIn("Python evidence/audit remains authority", boundaries)

        artifact_schemas = read_text("references/artifact-schemas.md")
        self.assertIn(
            "python scripts/sgctl.py validate-loop-design", artifact_schemas
        )
        self.assertIn(
            "python scripts/sgctl.py validate-phase-markdown", artifact_schemas
        )
        core = read_text("references/core-planning-contract.md")
        self.assertIn("optional Unix-only recon helpers", core)
        self.assertIn("Python validator authority", core)
        execution = read_text("references/execution-state-machine.md")
        self.assertIn("runtime/STATE.json", execution)
        self.assertIn("python scripts/sgctl.py validate-terminal", execution)
        self.assertNotIn(
            "`DONE` — `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE` printed",
            execution,
        )
        completed = read_text(
            "references/completed-standing-goal-and-workdir-hygiene.md"
        )
        self.assertIn("python scripts/sgctl.py validate-terminal", completed)
        repo_state = read_text("references/repo-state-comparison.md")
        self.assertIn("optional Unix-only compatibility helper", repo_state)
        self.assertIn("not terminal or audit authority", repo_state)
        rpd_handoff = read_text("references/rpd-to-supergoal-handoff.md")
        self.assertIn("python scripts/sgctl.py validate-phase-markdown", rpd_handoff)
        self.assertIn("review_pack_v2", rpd_handoff)
        self.assertIn("LOOP_DESIGN.md", rpd_handoff)
        goal_format = read_text("references/goal-format.md")
        self.assertIn("SUPERGOAL_TERMINAL v1", goal_format)
        self.assertIn("Don't stop at safe numbered phase boundaries", goal_format)
        self.assertNotIn("after every numbered phase", goal_format)

    def test_compile_reproducibility_command_shape(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a"; b = Path(td) / "b"
            for out in [a, b]:
                result = subprocess.run([sys.executable, "scripts/sgctl.py", "compile", "examples/brownfield-feature/CONTRACT.json", "--out", str(out)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for rel in ["CONTRACT.json", "THINKING.md", "RESEARCH.md", "reports/research.json", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "PROTOCOL.md", "LAUNCH_GOAL.md", "MANIFEST.json", "phases/phase-01.md"]:
                self.assertEqual((a / rel).read_bytes(), (b / rel).read_bytes(), rel)

    def test_no_tracked_test_dirtiness_gate_is_documented(self):
        test_runner = read_text("scripts/test.py")
        self.assertRegex(
            test_runner,
            r'TestGate\("git-diff-check", \("git", "diff", "--check"\)\)',
        )
        checklist = read_text("docs/release-checklist.md")
        self.assertIn("compare deterministic immutable outputs", checklist)

if __name__ == "__main__":
    unittest.main()
