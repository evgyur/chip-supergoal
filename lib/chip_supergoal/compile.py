from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Iterable

from .model import Contract, canonical_json, load_contract
from .render import render_launch_goal, render_loop_design, render_phase, render_roadmap, render_state, render_thinking
from .research import render_research_markdown, research_required, research_gate, validate_research_gate, write_research_report


REQUIRED_GENERATED = {"CONTRACT.json", "THINKING.md", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "PROTOCOL.md", "LAUNCH_GOAL.md"}
RUNTIME_SENTINELS = {
    "STATE.json",
    "EVENTS.jsonl",
    "events.jsonl",
    "evidence.jsonl",
    "runtime",
    "runtime/STATE.json",
    "runtime/events.jsonl",
    "runtime/evidence.jsonl",
    "runtime/state.lock",
}


class CompileSafetyError(ValueError):
    pass


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_package_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.name != "MANIFEST.json" and "out" not in p.relative_to(root).parts)


def file_mode(path: Path) -> str:
    return f"{stat.S_IMODE(path.stat().st_mode):04o}"


def build_manifest(root: Path) -> dict:
    artifacts = []
    for p in _iter_package_files(root):
        rel = p.relative_to(root).as_posix()
        artifacts.append({"path": rel, "sha256": file_sha256(p), "bytes": p.stat().st_size, "mode": file_mode(p)})
    joined = "\n".join(f"{a['path']} {a['sha256']} {a['bytes']} {a['mode']}" for a in artifacts)
    return {"manifest_version": "1.0", "artifacts": artifacts, "package_fingerprint": hashlib.sha256(joined.encode()).hexdigest()}


def _load_sealed_manifest(root: Path) -> dict:
    manifest_path = root / "MANIFEST.json"
    contract_path = root / "CONTRACT.json"
    if not manifest_path.is_file() or not contract_path.is_file():
        raise CompileSafetyError("existing output is not a sealed chip-supergoal package")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CompileSafetyError(f"existing output manifest is malformed: {exc}") from exc
    if manifest.get("manifest_version") != "1.0" or not isinstance(manifest.get("artifacts"), list):
        raise CompileSafetyError("existing output manifest has unsupported shape")
    expected = build_manifest(root)
    if manifest != expected:
        raise CompileSafetyError("existing output manifest does not seal current bytes")
    return manifest


def _assert_safe_target(out_path: Path, contract: Contract) -> None:
    if out_path.exists():
        if out_path.is_symlink() or not out_path.is_dir():
            raise CompileSafetyError("output target must be a directory or absent")
        for sentinel in RUNTIME_SENTINELS:
            if (out_path / sentinel).exists():
                raise CompileSafetyError(f"refusing to overwrite started runtime package with {sentinel}")
        if (out_path / "out").exists():
            raise CompileSafetyError("refusing to overwrite package containing runtime delivery/output artifacts")
        _load_sealed_manifest(out_path)
        existing = load_contract(out_path / "CONTRACT.json")
        if existing.goal.id != contract.goal.id:
            raise CompileSafetyError("refusing to overwrite a package for a different goal id")
        if canonical_json(existing) != canonical_json(contract) and contract.contract_revision != existing.contract_revision + 1:
            raise CompileSafetyError("changed contract must advance contract_revision by exactly one")


def _assert_not_source_container(out_path: Path, contract_source: Path | None) -> None:
    if contract_source is None:
        return
    try:
        source = contract_source.resolve(strict=True)
    except FileNotFoundError:
        source = contract_source.resolve(strict=False)
    target = out_path.resolve(strict=False)
    if source == target or source.is_relative_to(target):
        raise CompileSafetyError("output target cannot be the contract file, source root, or a source ancestor")


def _render_package(contract: Contract, out_path: Path, *, template_protocol: str | Path | None = None) -> None:
    out_path.mkdir(parents=True, exist_ok=False)
    phases_dir = out_path / "phases"
    phases_dir.mkdir()
    _write(out_path / "CONTRACT.json", canonical_json(contract))
    _write(out_path / "THINKING.md", render_thinking(contract))
    if research_required(contract) or research_gate(contract):
        _write(out_path / "RESEARCH.md", render_research_markdown(contract))
    _write(out_path / "LOOP_DESIGN.md", render_loop_design(contract))
    _write(out_path / "ROADMAP.md", render_roadmap(contract))
    _write(out_path / "STATE.md", render_state(contract))
    _write(out_path / "LAUNCH_GOAL.md", render_launch_goal(contract))
    protocol_text = Path(template_protocol).read_text(encoding="utf-8") if template_protocol else "# PROTOCOL\n\nAUDIT_COMPLETE\nSUPERGOAL_RUN_COMPLETE\n"
    _write(out_path / "PROTOCOL.md", protocol_text)
    for i in range(len(contract.phases)):
        _write(phases_dir / f"phase-{i+1:02d}.md", render_phase(contract, i))
    if research_required(contract) or research_gate(contract):
        write_research_report(contract, out_path / "reports" / "research.json")
    manifest = build_manifest(out_path)
    _write(out_path / "MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def compile_contract(contract: Contract, out: str | Path, *, template_protocol: str | Path | None = None, contract_source: str | Path | None = None) -> Path:
    research_diags = validate_research_gate(contract, artifact=str(contract_source or "CONTRACT.json"))
    if research_diags:
        joined = "\n".join(d.render_human() for d in research_diags)
        raise CompileSafetyError(f"research gate is not satisfied:\n{joined}")
    raw_out = Path(out)
    out_path = raw_out.resolve(strict=False)
    parent = out_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    _assert_not_source_container(out_path, Path(contract_source) if contract_source is not None else None)
    _assert_safe_target(out_path, contract)

    staging = Path(tempfile.mkdtemp(prefix=f".{out_path.name}.tmp-", dir=str(parent)))
    backup: Path | None = None
    try:
        shutil.rmtree(staging)
        _render_package(contract, staging, template_protocol=template_protocol)
        if out_path.exists():
            backup = parent / f".{out_path.name}.backup-{os.getpid()}-{next(tempfile._get_candidate_names())}"
            out_path.rename(backup)
        staging.rename(out_path)
        if backup is not None:
            shutil.rmtree(backup)
        return out_path
    except Exception:
        if out_path.exists() and backup is not None:
            shutil.rmtree(out_path, ignore_errors=True)
        if backup is not None and backup.exists():
            backup.rename(out_path)
        shutil.rmtree(staging, ignore_errors=True)
        raise


def compile_contract_file(path: str | Path, out: str | Path, *, template_protocol: str | Path | None = None) -> Path:
    contract_path = Path(path)
    return compile_contract(load_contract(contract_path), out, template_protocol=template_protocol, contract_source=contract_path)
