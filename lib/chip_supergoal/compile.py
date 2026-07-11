from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .diagnostics import ContractValidationError
from .model import Contract, canonical_json, load_contract
from .pipeline import ContractPipelineResult, contract_diagnostics, validate_contract_source
from .portable import logical_mode, write_bytes_atomic, write_utf8_lf
from .profiles import ResolvedContract
from .render import render_launch_goal, render_loop_design, render_phase, render_roadmap, render_state, render_thinking
from .research import render_research_markdown, research_report, research_required, research_gate


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
    write_utf8_lf(path, content)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_package_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.name != "MANIFEST.json" and "out" not in p.relative_to(root).parts)


def file_mode(relative_path: str | Path) -> str:
    return logical_mode(relative_path)


def build_manifest(root: Path) -> dict:
    artifacts = []
    for p in _iter_package_files(root):
        rel = p.relative_to(root).as_posix()
        artifacts.append({"path": rel, "sha256": file_sha256(p), "bytes": p.stat().st_size, "mode": file_mode(rel)})
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
        raise CompileSafetyError("existing output manifest is malformed") from exc
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
        try:
            existing = load_contract(out_path / "CONTRACT.json")
        except Exception as exc:
            raise CompileSafetyError("existing output contract is malformed") from exc
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


def _render_package(resolved: ResolvedContract, out_path: Path, *, template_protocol: str | Path | None = None) -> None:
    contract = resolved.contract
    out_path.mkdir(parents=True, exist_ok=False)
    phases_dir = out_path / "phases"
    phases_dir.mkdir()
    write_bytes_atomic(out_path / "CONTRACT.json", resolved.canonical_bytes)
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
        _write(out_path / "reports" / "research.json", json.dumps(research_report(contract), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    manifest = build_manifest(out_path)
    _write(out_path / "MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _compile_resolved(
    resolved: ResolvedContract,
    out: str | Path,
    *,
    template_protocol: str | Path | None = None,
    contract_source: str | Path | None = None,
) -> Path:
    contract = resolved.contract
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
        _render_package(resolved, staging, template_protocol=template_protocol)
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


def _resolved_or_raise(result: ContractPipelineResult) -> ResolvedContract:
    if result.diagnostics:
        raise ContractValidationError(result.diagnostics)
    if result.resolved is None:
        raise RuntimeError("canonical contract pipeline returned no result")
    return result.resolved


def compile_contract(
    contract: Contract,
    out: str | Path,
    *,
    template_protocol: str | Path | None = None,
    contract_source: str | Path | None = None,
    resource_root: str | Path | None = None,
    risk_policy_path: str | Path | None = None,
) -> Path:
    result = validate_contract_source(
        contract,
        artifact=str(contract_source or "CONTRACT.json"),
        resource_root=resource_root,
        risk_policy_path=risk_policy_path,
    )
    return _compile_resolved(
        _resolved_or_raise(result),
        out,
        template_protocol=template_protocol,
        contract_source=contract_source,
    )


def compile_contract_file(
    path: str | Path,
    out: str | Path,
    *,
    template_protocol: str | Path | None = None,
    resource_root: str | Path | None = None,
    risk_policy_path: str | Path | None = None,
) -> Path:
    contract_path = Path(path)
    result = contract_diagnostics(
        contract_path,
        resource_root=resource_root,
        risk_policy_path=risk_policy_path,
    )
    return _compile_resolved(
        _resolved_or_raise(result),
        out,
        template_protocol=template_protocol,
        contract_source=contract_path,
    )
