#!/usr/bin/env python3
"""Cross-platform aggregate regression runner for chip-supergoal.

This module is the package-test authority on Windows and Linux.  Unix-only
shell syntax and style checks stay in ``scripts/test.sh``; every package gate
below is launched with an argument list and the current Python interpreter.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from chip_supergoal.portable import (
    is_reparse_point,
    iter_tree_no_follow,
    read_regular_file_no_follow,
)


@dataclass(frozen=True)
class TestGate:
    """One ordered aggregate gate."""

    name: str
    command: tuple[object, ...]
    uses_python: bool = False


@dataclass(frozen=True)
class TestPlan:
    """An immutable, ordered native test plan."""

    root: Path
    gates: tuple[TestGate, ...]

    @property
    def python_commands(self) -> tuple[tuple[object, ...], ...]:
        return tuple(
            gate.command
            for gate in self.gates
            if gate.uses_python
        )


def relative_posix(path: Path, root: Path = ROOT) -> str:
    """Serialize a repository-relative path independently of the host OS."""

    return path.absolute().relative_to(root.absolute()).as_posix()


def _python_script(root: Path, relative: str) -> tuple[object, ...]:
    return (sys.executable, root / relative)


def build_test_plan(root: Path = ROOT) -> TestPlan:
    """Build the identical package-test plan used on Windows and Linux."""

    root = root.resolve()
    runner = root / "scripts" / "test.py"
    gates = (
        TestGate(
            "install-layout",
            (sys.executable, runner, "--internal-gate", "layout"),
            uses_python=True,
        ),
        TestGate(
            "privacy-boundary",
            (sys.executable, runner, "--internal-gate", "privacy"),
            uses_python=True,
        ),
        TestGate(
            "reference-contract",
            (sys.executable, runner, "--internal-gate", "reference"),
            uses_python=True,
        ),
        TestGate(
            "dev-history-contracts",
            _python_script(root, "scripts/probe-dev-history-contracts.py"),
            uses_python=True,
        ),
        TestGate(
            "user-stories",
            _python_script(root, "scripts/test-user-stories.py"),
            uses_python=True,
        ),
        TestGate(
            "reference-taxonomy",
            _python_script(root, "scripts/probe-reference-taxonomy.py"),
            uses_python=True,
        ),
        TestGate(
            "upstream-goal-compatibility",
            _python_script(root, "scripts/probe-upstream-goal-compat.py"),
            uses_python=True,
        ),
        TestGate(
            "python-unittest",
            (
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                root / "tests",
            ),
            uses_python=True,
        ),
        TestGate("git-diff-check", ("git", "diff", "--check")),
    )
    return TestPlan(root=root, gates=gates)


def _native_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _portable_command(command: Sequence[object]) -> list[str]:
    return [os.fspath(argument) for argument in command]


def run_test_plan(plan: TestPlan) -> int:
    """Run gates in order, stopping and returning the first failure."""

    passed = 0
    total = len(plan.gates)
    environment = _native_environment()
    for gate in plan.gates:
        print(f"NATIVE_GATE_START name={gate.name}", flush=True)
        try:
            result = subprocess.run(
                _portable_command(gate.command),
                cwd=plan.root,
                env=environment,
                check=False,
            )
            returncode = result.returncode
        except OSError as error:
            print(
                f"NATIVE_GATE_ERROR name={gate.name} "
                f"error={type(error).__name__}",
                file=sys.stderr,
                flush=True,
            )
            returncode = 1

        if returncode != 0:
            print(
                f"NATIVE_GATE_FAIL name={gate.name} returncode={returncode}",
                flush=True,
            )
            print(
                f"NATIVE_TEST_SUMMARY total={total} passed={passed} "
                f"failed=1 first_failed={gate.name}",
                flush=True,
            )
            return returncode if returncode > 0 else 1

        passed += 1
        print(f"NATIVE_GATE_PASS name={gate.name}", flush=True)

    print(
        f"NATIVE_TEST_SUMMARY total={total} passed={passed} "
        "failed=0 first_failed=none",
        flush=True,
    )
    return 0


def _check_layout(root: Path) -> list[str]:
    required = (
        "SKILL.md",
        "lib/chip_supergoal/state.py",
        "scripts/test.py",
        "scripts/check-cross-file-consistency.py",
        "scripts/test-user-stories.py",
        "scripts/validate-phase.sh",
        "scripts/validate-loop-design.sh",
        "scripts/repo-state.sh",
        "templates/PROTOCOL.md",
        "templates/ROADMAP.md",
        "templates/RESEARCH.md",
        "templates/LOOP_DESIGN.md",
        "templates/LAUNCH_GOAL.md",
        "references/rpd-review-gates.md",
        "references/core-planning-contract.md",
        "references/artifact-boundaries.md",
        "references/artifact-schemas.md",
        "references/loop-design-gate.md",
        "references/execution-state-machine.md",
        "references/INDEX.md",
        "references/dispatch-map.md",
        "references/dev-history-hardening.md",
        "references/upstream-goal-compatibility.md",
        "references/upstream-goal-reconciliation.md",
        "references/rpd-to-supergoal-handoff.md",
        "references/ignored-supergoal-package-hygiene.md",
        "templates/delivery/send-review-md-files.sh",
        "templates/delivery/package-final-artifacts.sh",
        "templates/delivery/send-final-artifacts.sh",
        "templates/delivery/review-md-files-delivery-receipt.schema.json",
        "templates/delivery/final-artifacts-delivery-receipt.schema.json",
    )
    return [f"missing required asset: {item}" for item in required if not (root / item).is_file()]


_SECRET_PATTERNS = (
    (
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----"),
    ),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("openai_style_token", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{32,}")),
    (
        "jwt",
        re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
            r"[A-Za-z0-9_-]{10,}"
        ),
    ),
    (
        "env_secret_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|token|password)\s*=\s*"
            r"[\"']?[A-Za-z0-9_./+=-]{24,}[\"']?"
        ),
    ),
)


def _tracked_files(root: Path) -> tuple[Path, ...]:
    """Return index-tracked files, including force-tracked runtime paths."""

    try:
        result = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return ()
    if result.returncode != 0:
        return ()

    paths: list[Path] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(os.fsdecode(raw_path))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        paths.append(root / relative)
    return tuple(paths)


def _repository_files(root: Path):
    """Yield tracked files plus a bounded untracked working-tree scope."""

    tracked = frozenset(_tracked_files(root))
    ignored_untracked = {".shaw", ".supergoal"}
    for path, stat_result in iter_tree_no_follow(
        root,
        prune_directory_names={".git", "__pycache__"},
    ):
        is_link = stat.S_ISLNK(stat_result.st_mode)
        is_regular = (
            stat.S_ISREG(stat_result.st_mode)
            and not is_reparse_point(stat_result)
        )
        if (
            not (is_regular or is_link)
            or path.name == ".git"
            or path.suffix == ".pyc"
        ):
            continue
        relative_parts = path.relative_to(root).parts
        if path not in tracked and any(
            part in ignored_untracked for part in relative_parts
        ):
            continue
        yield path


def _check_privacy(root: Path) -> list[str]:
    violations: list[str] = []
    for path in _repository_files(root):
        try:
            if path.is_symlink():
                contents = os.readlink(path)
            else:
                contents = read_regular_file_no_follow(path, root).decode(
                    "utf-8",
                    errors="ignore",
                )
        except OSError as error:
            violations.append(
                f"unreadable file: {relative_posix(path, root)}:{type(error).__name__}"
            )
            continue
        for line_number, line in enumerate(contents.splitlines(), 1):
            for pattern_name, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    # Never echo the matching line: the diagnostic itself must
                    # not turn a local credential into terminal or CI output.
                    violations.append(
                        f"{relative_posix(path, root)}:{line_number}:{pattern_name}"
                    )
    return violations


def _read(root: Path, relative: str) -> str:
    return read_regular_file_no_follow(root / relative, root).decode(
        "utf-8",
        errors="ignore",
    )


def _tree_files(
    root: Path,
    tree_root: Path | None = None,
    *,
    prune_directory_names=(),
):
    scan_root = root if tree_root is None else tree_root
    for path, stat_result in iter_tree_no_follow(
        scan_root,
        prune_directory_names=prune_directory_names,
    ):
        if stat.S_ISREG(stat_result.st_mode) and not is_reparse_point(stat_result):
            yield path


def _check_reference_contract(root: Path) -> list[str]:
    errors: list[str] = []

    launch_hits: list[str] = []
    for path in _tree_files(
        root,
        prune_directory_names={".git", ".shaw", ".supergoal", "__pycache__"},
    ):
        if path.suffix != ".md" or path.name == ".git":
            continue
        for line in read_regular_file_no_follow(path, root).decode(
            "utf-8",
            errors="ignore",
        ).splitlines():
            if line.startswith("SUPERGOAL_GOAL_BODY:"):
                launch_hits.append(relative_posix(path, root))
    if launch_hits != ["templates/LAUNCH_GOAL.md"]:
        errors.append(f"launch body locations: {launch_hits!r}")

    launch = _read(root, "templates/LAUNCH_GOAL.md")
    if "LOOP_DESIGN.md" not in launch or "Resolve the package root" not in launch:
        errors.append("launch goal does not resolve and read LOOP_DESIGN.md")
    loop_design = _read(root, "templates/LOOP_DESIGN.md")
    if any(line.startswith("SUPERGOAL_GOAL_BODY:") for line in loop_design.splitlines()):
        errors.append("LOOP_DESIGN.md is an alternate launch surface")

    active_files = (
        [root / "SKILL.md"]
        + list((root / "references").glob("*.md"))
        + [
            path
            for path in _tree_files(root, root / "templates")
            if path.suffix == ".md"
        ]
        + list((root / "scripts").glob("*.py"))
    )
    excluded = {
        "scripts/probe-reference-taxonomy.py",
        "scripts/test.py",
    }
    banned_phrases = (
        "exactly three native",
        "three native `.md` files",
        "one numbered phase per turn",
        "stop with SUPERGOAL_TURN_YIELD",
        "do not chain phases",
        "execute only current phase",
    )
    for path in sorted(active_files, key=lambda item: relative_posix(item, root)):
        relative = relative_posix(path, root)
        if "legacy-monolith" in path.name or relative in excluded:
            continue
        contents = read_regular_file_no_follow(path, root).decode(
            "utf-8",
            errors="ignore",
        )
        for phrase in banned_phrases:
            if phrase in contents:
                errors.append(f"stale phrase in {relative}: {phrase}")

    artifact_boundaries = _read(root, "references/artifact-boundaries.md")
    for required in (
        "review_pack_v2",
        "LOOP_DESIGN.md",
        'pack_version: "review_pack_v2"',
        "Planning delivery failure blocks `READY_TO_DISPATCH`",
    ):
        if required not in artifact_boundaries:
            errors.append(f"artifact boundary missing: {required}")

    skill = _read(root, "SKILL.md")
    frontmatter = re.match(r"^---\n(.*?)\n---\n", skill, re.DOTALL)
    if frontmatter is None:
        errors.append("SKILL.md frontmatter missing")
    else:
        name = re.search(r"(?m)^name:\s*(.+?)\s*$", frontmatter.group(1))
        description = re.search(
            r"(?m)^description:\s*(.+?)\s*$", frontmatter.group(1)
        )
        if name is None or name.group(1).strip("'\"") != "chip-supergoal":
            errors.append("SKILL.md frontmatter name is not chip-supergoal")
        if description is None or len(description.group(1).strip("'\"")) > 1024:
            errors.append("SKILL.md frontmatter description is missing or too long")
    if len(skill.encode("utf-8")) >= 40_000:
        errors.append(f"SKILL.md exceeds 40000 bytes: {len(skill.encode('utf-8'))}")
    for heading in (
        "Principal+ contract",
        "Generated artifacts",
        "Reference dispatch",
        "RPD / Senior Gate",
        "Loop Design Gate",
        "Output Contract",
    ):
        if heading not in skill:
            errors.append(f"SKILL.md missing root section: {heading}")

    marker_bundle = "\n".join(
        _read(root, relative)
        for relative in (
            "SKILL.md",
            "templates/PROTOCOL.md",
            "templates/LAUNCH_GOAL.md",
            "templates/phase-goal.txt",
            "references/rpd-review-gates.md",
        )
    )
    for marker in (
        "SUPERGOAL_GOAL_BODY:",
        "SUPERGOAL_PHASE_START",
        "SUPERGOAL_STATUS",
        "SUPERGOAL_PHASE_VERIFY",
        "RPD_PLAN_REVIEW",
        "RPD_PHASE_REVIEW",
        "RPD_FINAL_REVIEW",
        "MEMORY_SAVED",
        "SUPERGOAL_PHASE_DONE",
        "SUPERGOAL_TURN_YIELD",
        "PREFLIGHT_GREEN",
        "PREFLIGHT_RED",
        "AUDIT_START",
        "AUDIT_VERIFY",
        "AUDIT_GAPS",
        "AUDIT_COMPLETE",
        "AUDIT_HANDOFF",
        "SUPERGOAL_RUN_COMPLETE",
        "FAILURE_PROBE",
        "FAILURE_ESCALATE",
        "FAILURE_HANDOFF",
        "SUPERGOAL_REVIEW_FILES_BLOCKED",
        "SUPERGOAL_FILES_SENT",
        "BLOCKED_BY_APPROVAL",
        "READY_FOR_DELETE_APPROVAL",
        "READY_TO_DISPATCH",
    ):
        if marker not in marker_bundle:
            errors.append(f"marker contract missing: {marker}")

    protocol = _read(root, "templates/PROTOCOL.md")
    for required in (
        "scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated",
        "runtime/STATE.json",
    ):
        if required not in protocol:
            errors.append(f"protocol missing Python authority path: {required}")
    for forbidden in ("references/", "SKILL.md"):
        if forbidden in protocol:
            errors.append(f"generated protocol references package path: {forbidden}")

    repo_state = _read(root, "references/repo-state-comparison.md")
    for required in (
        ".supergoal/scripts/repo-state.sh",
        "invalid baseline",
        "exit 2",
        "unchanged — existed before baseline",
        "exit 3",
        "exists on disk only in non-git fallback mode",
    ):
        if required not in repo_state:
            errors.append(f"repo-state reference missing: {required}")
    for obsolete in (
        ".supergoal/repo-state.sh",
        "still reads `present`",
        "ignored-or-non-git existence fallback",
    ):
        if obsolete in repo_state:
            errors.append(f"repo-state reference contains obsolete text: {obsolete}")

    preservation = _read(root, "references/supergoal-hermes-update-preservation.md")
    for required in (
        "hermes_cli/goal_policies.py",
        "gateway/goal_launch.py",
        "thin compatibility shims",
        "skip exactly one post-turn judge pass",
        "Queued slash-command fallback is intentionally not used",
    ):
        if required not in preservation:
            errors.append(f"preservation reference missing: {required}")

    return errors


_INTERNAL_GATES: dict[str, Callable[[Path], list[str]]] = {
    "layout": _check_layout,
    "privacy": _check_privacy,
    "reference": _check_reference_contract,
}


def _run_internal_gate(name: str, root: Path) -> int:
    try:
        errors = _INTERNAL_GATES[name](root)
    except (OSError, UnicodeError) as error:
        errors = [f"{type(error).__name__}: {error}"]
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: native {name} gate")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run chip-supergoal package tests natively on Windows or Linux."
    )
    parser.add_argument(
        "--skip-shell",
        action="store_true",
        help="accepted from test.sh; Unix shell quality gates already ran",
    )
    parser.add_argument(
        "--internal-gate",
        choices=tuple(_INTERNAL_GATES),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.internal_gate:
        return _run_internal_gate(args.internal_gate, ROOT)
    return run_test_plan(build_test_plan(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
