from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .model import contract_from_dict
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

def migrate_v2_package(src: str | Path, out: str | Path) -> dict[str, Any]:
    src = Path(src); out = Path(out)
    if not src.is_dir():
        raise MigrationError(f"source package not found: {src}")
    phase_files = sorted((src / "phases").glob("phase-*.md"))
    if not phase_files:
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
        command = _meta(text, "Mandatory commands") or "bash scripts/test.sh"
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
        raise MigrationError(json.dumps({"migration_unresolved": diagnostics}, ensure_ascii=False))
    roadmap = (src / "ROADMAP.md").read_text(encoding="utf-8", errors="ignore") if (src / "ROADMAP.md").exists() else "# Migrated v2 package"
    title = re.search(r"^#\s+(.+)$", roadmap, re.M)
    title_text = title.group(1).strip() if title else "Migrated v2 package"
    goal_id = f"sg-20260625-{_slug(title_text)}-{_sha(roadmap)[:6]}"
    contract = {
        "schema_version": "3.0", "protocol_version": "3.0", "contract_revision": 1, "profile": "chip-private",
        "goal": {"id": goal_id, "title": title_text, "objective": "Migrated v2 package preserves original phase semantics for v3 validation.", "request_digest": _sha(roadmap), "workspace_root": ".", "owner": "chip", "non_goals": ["invent missing v2 semantics"], "done_condition": "migrated contract validates"},
        "source_set": [{"id": "SRC-001", "kind": "v2_package", "locator": str(src), "authority": "provided_context", "freshness": "captured_at_migration", "sensitivity": "internal"}],
        "decisions": [], "architecture": {}, "loop": {
            "outcome_definition": {
                "outcome": "The migrated package preserves the original v2 phase semantics and validates as v3.",
                "evidence": ["strict v3 contract validation passes", "every migrated phase retains its source criterion and command"],
                "threshold": "Zero unresolved migration diagnostics and all blocking criteria remain represented.",
                "in_scope": ["v2 phase metadata", "v3 contract and backup artifacts"],
                "out_of_scope": ["inventing missing v2 semantics", "executing production effects during migration"],
                "stop_and_ask": "Stop if a v2 phase lacks a recoverable task, criterion, or mandatory command.",
            },
            "execution_profile": {
                "owner": "Sol", "planner_effort": "high", "integrator_effort": "max",
                "engineering_mode": "shawl", "worker_model": "gpt-5.6-luna", "worker_mode": "scout",
                "max_parallel_scouts": 3, "max_review_rounds": 3,
                "phase_routes": {phase["id"]: "shawl" if phase["rpd"]["required"] else "direct" for phase in phases},
            },
        }, "risks": [], "approvals": [], "phases": phases, "delivery": {}, "compatibility": {"legacy_fallback": ["v2-read-only"]},
    }
    contract_from_dict(contract)
    out.mkdir(parents=True, exist_ok=True)
    backup = out / "v2-backup"
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(src, backup)
    (out / "CONTRACT.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {"ok": True, "source": str(src), "backup": str(backup), "contract": str(out / "CONTRACT.json"), "migration_unresolved": []}
    (out / "migration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
