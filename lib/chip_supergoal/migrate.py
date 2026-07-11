from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from .model import contract_from_dict
from .portable import (
    UnsafeFileError,
    is_reparse_point,
    iter_tree_no_follow,
    read_regular_file_no_follow,
    staged_directory_publication,
)
from .validate import validate_phase_markdown

class MigrationError(ValueError):
    pass

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32]
    return slug or "migrated"

def _meta(text: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""

def _section(text: str, heading: str) -> str:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.M)
    if not m:
        return ""
    start = m.end()
    next_h = re.search(r"^##\s+", text[start:], re.M)
    end = start + next_h.start() if next_h else len(text)
    return text[start:end]

def _bullets(sec: str) -> list[str]:
    return [re.sub(r"^\s*[-*]\s+", "", line).strip() for line in sec.splitlines() if re.match(r"^\s*[-*]\s+", line)]

def read_v2_state_md(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    current = _meta(text, "Current phase") or "unknown"
    total = _meta(text, "Total phases") or "unknown"
    return {"compatibility_mode": "v2-read-only", "current_phase": current, "total_phases": total}


def _migration_stat_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_mode),
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(getattr(value, "st_file_attributes", 0)),
    )


def _snapshot_v2_source(
    source: Path,
    destination: Path,
    source_stat: os.stat_result,
    entries: tuple[tuple[Path, os.stat_result], ...],
) -> None:
    try:
        if _migration_stat_signature(source.lstat()) != _migration_stat_signature(
            source_stat
        ):
            raise MigrationError("source package identity changed during migration")
        destination.mkdir()
        expected_inventory = {
            path.relative_to(source).as_posix(): _migration_stat_signature(entry_stat)
            for path, entry_stat in entries
        }
        for path, expected_stat in entries:
            relative = path.relative_to(source)
            current = path.lstat()
            if _migration_stat_signature(current) != _migration_stat_signature(
                expected_stat
            ):
                raise MigrationError(
                    f"source package identity changed during migration: {path}"
                )
            target = destination / relative
            if stat.S_ISDIR(current.st_mode):
                target.mkdir()
                continue
            data = read_regular_file_no_follow(path, source)
            after = path.lstat()
            if _migration_stat_signature(after) != _migration_stat_signature(
                expected_stat
            ):
                raise MigrationError(
                    f"source package identity changed during migration: {path}"
                )
            target.write_bytes(data)
            os.chmod(target, stat.S_IMODE(current.st_mode))
        observed_inventory = {
            path.relative_to(source).as_posix(): _migration_stat_signature(path.lstat())
            for path, _ in iter_tree_no_follow(source)
        }
        if observed_inventory != expected_inventory:
            raise MigrationError("source package inventory changed during migration")
        if _migration_stat_signature(source.lstat()) != _migration_stat_signature(
            source_stat
        ):
            raise MigrationError("source package identity changed during migration")
    except UnsafeFileError as exc:
        raise MigrationError(
            f"source package contains a symlink or reparse point: {exc.path}"
        ) from exc


def _migration_publication_checkpoint(output: Path) -> None:
    """Internal deterministic race-injection seam; production is a no-op."""

    del output


def _copy_snapshot_to_publication(source: Path, publication: Any) -> None:
    publication.ensure_directory("v2-backup", mode=0o755)
    entries = None
    try:
        entries = iter_tree_no_follow(source)
        for path, entry_stat in entries:
            relative = path.relative_to(source).as_posix()
            destination = f"v2-backup/{relative}"
            mode = stat.S_IMODE(entry_stat.st_mode)
            if stat.S_ISLNK(entry_stat.st_mode) or is_reparse_point(entry_stat):
                raise MigrationError(
                    f"source snapshot contains a symlink or reparse point: {path}"
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                publication.ensure_directory(destination, mode=mode)
            elif stat.S_ISREG(entry_stat.st_mode):
                publication.write_bytes(
                    destination,
                    read_regular_file_no_follow(path, source),
                    mode=mode,
                )
            else:
                raise MigrationError(
                    f"source snapshot contains a special file: {path}"
                )
    except UnsafeFileError as exc:
        raise MigrationError(
            f"source snapshot changed during migration: {exc.path}"
        ) from exc
    finally:
        close = getattr(entries, "close", None)
        if close is not None:
            close()

def migrate_v2_package(src: str | Path, out: str | Path) -> dict[str, Any]:
    src = Path(src); out = Path(out)
    try:
        source_stat = src.lstat()
    except OSError as exc:
        raise MigrationError(f"source package not found: {src}") from exc
    if (
        not stat.S_ISDIR(source_stat.st_mode)
        or stat.S_ISLNK(source_stat.st_mode)
        or is_reparse_point(source_stat)
    ):
        raise MigrationError(f"source package not found: {src}")
    try:
        enumerated_entries = tuple(iter_tree_no_follow(src))
    except OSError as exc:
        raise MigrationError(f"source package cannot be enumerated safely: {src}") from exc
    verified_entries = []
    for path, _ in enumerated_entries:
        entry_stat = path.lstat()
        if stat.S_ISLNK(entry_stat.st_mode) or is_reparse_point(entry_stat):
            raise MigrationError(
                f"source package contains a symlink or reparse point: {path}"
            )
        if not (
            stat.S_ISDIR(entry_stat.st_mode) or stat.S_ISREG(entry_stat.st_mode)
        ):
            raise MigrationError(f"source package contains a special file: {path}")
        verified_entries.append((path, entry_stat))
    source_entries = tuple(verified_entries)
    if os.path.lexists(out):
        raise MigrationError(f"output path already exists: {out}")
    source_locator = src
    snapshot = tempfile.TemporaryDirectory(prefix="chip-supergoal-v2-migration-")
    snapshot_source = Path(snapshot.name) / "source"
    try:
        _snapshot_v2_source(src, snapshot_source, source_stat, source_entries)
    except Exception:
        snapshot.cleanup()
        raise
    src = snapshot_source
    phase_files = sorted((src / "phases").glob("phase-*.md"))
    if not phase_files:
        snapshot.cleanup()
        raise MigrationError("no v2 phase files found")
    diagnostics = []
    phases = []
    for idx, pf in enumerate(phase_files, 1):
        diags = validate_phase_markdown(pf)
        if diags:
            diagnostics.extend({"file": str(pf), "code": d.code, "message": d.message} for d in diags)
            continue
        text = pf.read_text(encoding="utf-8")
        name = _meta(text, "Phase").split("—", 1)[-1].strip() or f"Phase {idx}"
        task = _meta(text, "Task") or name
        command = _meta(text, "Mandatory commands") or "python scripts/test.py"
        criteria = _bullets(_section(text, "Acceptance criteria")) or ["Migrated criterion requires manual verification"]
        phase_id = f"P{idx:02d}"
        phases.append({
            "id": phase_id,
            "ordinal": idx,
            "name": name,
            "task": task,
            "depends_on": [] if idx == 1 else [f"P{idx-1:02d}"],
            "work_items": [{"id": f"{phase_id}-W01", "text": "Migrated from v2 phase spec"}],
            "deliverables": [{"id": f"{phase_id}-D01", "kind": "migration_note", "path": pf.relative_to(src).as_posix(), "change_expectation": "read_only_migrated", "verification": "source_hash"}],
            "criteria": [{"id": f"{phase_id}-C{n:02d}", "statement": c, "verifier": {"type": "manual_observation", "command_id": f"{phase_id}-CMD01", "expected_exit": 0, "expected_assertion": "migrated criterion checked"}, "evidence_tier": "provided_context", "blocking": True} for n, c in enumerate(criteria, 1)],
            "commands": [{"id": f"{phase_id}-CMD01", "command": command, "purpose": "migrated v2 mandatory command", "safety": "local_read_write", "timeout_seconds": 120}],
            "risk_tags": [],
            "rpd": {"required": _meta(text, "RPD required") == "yes", "focus": [] if _meta(text, "RPD focus") in {"", "none"} else [_meta(text, "RPD focus")]},
        })
    if diagnostics:
        snapshot.cleanup()
        raise MigrationError(json.dumps({"migration_unresolved": diagnostics}, ensure_ascii=False))
    roadmap = (src / "ROADMAP.md").read_text(encoding="utf-8", errors="ignore") if (src / "ROADMAP.md").exists() else "# Migrated v2 package"
    title = re.search(r"^#\s+(.+)$", roadmap, re.M)
    title_text = title.group(1).strip() if title else "Migrated v2 package"
    goal_id = f"sg-20260625-{_slug(title_text)}-{_sha(roadmap)[:6]}"
    contract = {
        "schema_version": "3.0", "protocol_version": "3.0", "contract_revision": 1, "profile": "chip-private",
        "goal": {"id": goal_id, "title": title_text, "objective": "Migrated v2 package preserves original phase semantics for v3 validation.", "request_digest": _sha(roadmap), "workspace_root": ".", "owner": "chip", "non_goals": ["invent missing v2 semantics"], "done_condition": "migrated contract validates"},
        "source_set": [{"id": "SRC-001", "kind": "v2_package", "locator": str(source_locator), "authority": "provided_context", "freshness": "captured_at_migration", "sensitivity": "internal"}],
        "decisions": [], "architecture": {}, "loop": {}, "risks": [], "approvals": [], "phases": phases, "delivery": {}, "compatibility": {"legacy_fallback": ["v2-read-only"]},
    }
    contract_from_dict(contract)
    out.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(out):
        snapshot.cleanup()
        raise MigrationError(f"output path already exists: {out}")
    report = {
        "ok": True,
        "source": str(source_locator),
        "backup": str(out / "v2-backup"),
        "contract": str(out / "CONTRACT.json"),
        "migration_unresolved": [],
    }
    try:
        with staged_directory_publication(out) as publication:
            _migration_publication_checkpoint(out)
            _copy_snapshot_to_publication(src, publication)
            publication.write_bytes(
                "CONTRACT.json",
                (
                    json.dumps(
                        contract,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8"),
                mode=0o644,
            )
            publication.write_bytes(
                "migration-report.json",
                (
                    json.dumps(
                        report,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8"),
                mode=0o644,
            )
            snapshot.cleanup()
            publication.publish()
    except FileExistsError as exc:
        raise MigrationError(f"output path already exists: {out}") from exc
    except UnsafeFileError as exc:
        raise MigrationError(
            f"output path changed during secure publication: {out}"
        ) from exc
    except OSError as exc:
        raise MigrationError(
            f"output path could not be published securely: {out}"
        ) from exc
    finally:
        snapshot.cleanup()
    return report
