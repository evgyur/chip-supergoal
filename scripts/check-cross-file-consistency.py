#!/usr/bin/env python3
"""Check cross-file phase totals and the single launch surface natively."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import re
import stat
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "lib"))

from chip_supergoal.portable import (  # noqa: E402
    UnsafeFileError,
    is_reparse_point,
    iter_tree_no_follow,
    read_regular_file_no_follow,
)


PHASE_FILE = re.compile(r"phase-(\d+)\.md\Z")
PHASE_HEADER = re.compile(r"^Phase:\s+(\d+)\s+of\s+(\d+)\b", re.MULTILINE)
MAX_TREE_ENTRIES = 20_000
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
MAX_TOTAL_MARKDOWN_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ConsistencyResult:
    errors: tuple[str, ...]
    phase_count: int
    launch_line: int | None


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def inspect_cross_file_consistency(package_root: str | Path) -> ConsistencyResult:
    """Return a deterministic result for one generated package."""

    root = Path(os.path.abspath(os.fspath(package_root)))
    errors: list[str] = []
    markdown: dict[Path, str] = {}
    total_markdown_bytes = 0
    try:
        for path, stat_result in iter_tree_no_follow(
            root,
            max_entries=MAX_TREE_ENTRIES,
        ):
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(stat_result.st_mode) or is_reparse_point(stat_result):
                errors.append(f"linked path is not allowed: {relative}")
                continue
            if not stat.S_ISREG(stat_result.st_mode) or path.suffix != ".md":
                continue
            try:
                raw = read_regular_file_no_follow(
                    path,
                    root,
                    max_bytes=MAX_MARKDOWN_BYTES,
                )
                total_markdown_bytes += len(raw)
                if total_markdown_bytes > MAX_TOTAL_MARKDOWN_BYTES:
                    return ConsistencyResult(
                        (
                            "Markdown total exceeds "
                            f"{MAX_TOTAL_MARKDOWN_BYTES}-byte limit",
                        ),
                        0,
                        None,
                    )
                markdown[path] = raw.decode("utf-8")
            except UnsafeFileError as error:
                if error.kind == "limit":
                    errors.append(
                        "Markdown exceeds "
                        f"{MAX_MARKDOWN_BYTES}-byte limit: {relative}"
                    )
                    continue
                errors.append(
                    f"cannot read UTF-8 Markdown {relative}: {type(error).__name__}"
                )
            except (OSError, UnicodeError, ValueError) as error:
                errors.append(
                    f"cannot read UTF-8 Markdown {relative}: {type(error).__name__}"
                )
    except UnsafeFileError as error:
        if error.kind == "limit":
            return ConsistencyResult(
                (f"tree entry count exceeds {MAX_TREE_ENTRIES}-entry limit",),
                0,
                None,
            )
        return ConsistencyResult(
            (f"cannot scan package root: {type(error).__name__}",),
            0,
            None,
        )
    except (OSError, ValueError) as error:
        return ConsistencyResult(
            (f"cannot scan package root: {type(error).__name__}",),
            0,
            None,
        )

    phases: list[tuple[int, Path, str]] = []
    phases_root = root / "phases"
    for path, contents in markdown.items():
        if path.parent != phases_root:
            continue
        match = PHASE_FILE.fullmatch(path.name)
        if match is not None:
            phases.append((int(match.group(1)), path, contents))
    phases.sort(key=lambda item: (item[0], item[1].name))

    if not phases:
        errors.append("no phases/phase-NN.md files discovered")
    else:
        expected_ordinals = list(range(1, len(phases) + 1))
        actual_ordinals = [ordinal for ordinal, _, _ in phases]
        if actual_ordinals != expected_ordinals:
            errors.append(
                "phase filename ordinals are not contiguous: "
                + ",".join(str(value) for value in actual_ordinals)
            )
        for filename_ordinal, path, contents in phases:
            header = PHASE_HEADER.search(contents)
            if header is None:
                errors.append(f"{path.name} has no parseable Phase header")
                continue
            header_ordinal = int(header.group(1))
            declared_total = int(header.group(2))
            if header_ordinal != filename_ordinal:
                errors.append(
                    f"{path.name} declares phase {header_ordinal}; "
                    f"filename declares {filename_ordinal}"
                )
            if declared_total != len(phases):
                errors.append(
                    f"{path.name} declares total {declared_total}; "
                    f"discovered {len(phases)} phase files"
                )

    launch_markers: list[tuple[str, int]] = []
    for path, contents in markdown.items():
        relative = path.relative_to(root).as_posix()
        if relative.startswith("templates/"):
            continue
        for line_number, line in enumerate(contents.splitlines(), 1):
            if line.startswith("SUPERGOAL_GOAL_BODY:"):
                launch_markers.append((relative, line_number))
    launch_markers.sort()
    if len(launch_markers) != 1 or launch_markers[0][0] != "LAUNCH_GOAL.md":
        rendered = ", ".join(
            f"{relative}:{line_number}"
            for relative, line_number in launch_markers
        ) or "none"
        errors.append(
            "launch body must appear exactly once in root LAUNCH_GOAL.md; "
            f"found {rendered}"
        )

    launch_line = launch_markers[0][1] if len(launch_markers) == 1 else None
    return ConsistencyResult(tuple(sorted(errors)), len(phases), launch_line)


def check_cross_file_consistency(package_root: str | Path) -> list[str]:
    """Return deterministic diagnostics for one generated package."""

    return list(inspect_cross_file_consistency(package_root).errors)


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=(
            "Check phase header totals and the single launch body without Bash."
        )
    )
    parser.add_argument("package_root", nargs="?", default=".")
    args = parser.parse_args(argv)
    result = inspect_cross_file_consistency(args.package_root)
    if result.errors:
        for error in result.errors:
            print(f"CROSS_FILE_CONSISTENCY_FAIL {error}", file=sys.stderr)
        return 1
    print(
        "CROSS_FILE_CONSISTENCY_PASS "
        f"phases={result.phase_count} "
        f"launch=LAUNCH_GOAL.md:{result.launch_line}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
