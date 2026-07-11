from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .diagnostics import ContractValidationError
from .events import read_events
from .model import Contract, canonical_json, load_contract
from .pipeline import ContractPipelineResult, contract_diagnostics, repository_resource_root, validate_contract_source
from .portable import (
    MUTABLE_PATH_NAMES,
    MUTABLE_PATHS,
    RUNTIME_MODULES,
    RUNTIME_PROFILES,
    RUNTIME_SCRIPTS,
    RUNTIME_SPEC_FILES,
    RUNTIME_TEMPLATES,
    logical_mode,
    write_bytes_atomic,
    write_utf8_lf,
)
from .profiles import ResolvedContract
from .render import render_launch_goal, render_loop_design, render_phase, render_roadmap, render_thinking
from .research import render_research_markdown, research_report, research_required, research_gate
from .state import State, StateStore, read_state
from .validate import validate_package


REQUIRED_GENERATED = {"CONTRACT.json", "THINKING.md", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "PROTOCOL.md", "LAUNCH_GOAL.md"}
class CompileSafetyError(ValueError):
    pass


def _write(path: Path, content: str) -> None:
    write_utf8_lf(path, content)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_package_files(root: Path) -> list[Path]:
    return sorted(
        (
            p
            for p in root.rglob("*")
            if p.is_file()
            and p.relative_to(root).as_posix() != "MANIFEST.json"
            and p.relative_to(root).as_posix() not in MUTABLE_PATH_NAMES
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def file_mode(relative_path: str | Path) -> str:
    return logical_mode(relative_path)


def build_manifest(
    root: Path,
    *,
    source_contract_sha256: str | None = None,
    contract_sha256: str | None = None,
) -> dict:
    contract_path = root / "CONTRACT.json"
    emitted_hash = contract_sha256
    if emitted_hash is None:
        emitted_hash = file_sha256(contract_path) if contract_path.is_file() else "0" * 64
    source_hash = source_contract_sha256 or emitted_hash
    artifacts = []
    for p in _iter_package_files(root):
        rel = p.relative_to(root).as_posix()
        artifacts.append({"path": rel, "sha256": file_sha256(p), "bytes": p.stat().st_size, "mode": file_mode(rel)})
    joined = "\n".join(f"{a['path']} {a['sha256']} {a['bytes']} {a['mode']}" for a in artifacts)
    return {
        "manifest_version": "1.1",
        "source_contract_sha256": source_hash,
        "contract_sha256": emitted_hash,
        "artifacts": artifacts,
        "mutable_paths": [dict(item) for item in MUTABLE_PATHS],
        "package_fingerprint": hashlib.sha256(joined.encode()).hexdigest(),
    }


def _copy_text(source: Path, destination: Path) -> None:
    _write(destination, source.read_text(encoding="utf-8"))


def _copy_runtime_inventory(
    out_path: Path,
    *,
    resource_root: Path,
    protocol_source: Path,
    risk_policy_source: Path,
) -> None:
    code_root = Path(__file__).resolve().parents[2]
    inventory = (
        *((code_root / "scripts" / name, Path("scripts") / name) for name in RUNTIME_SCRIPTS),
        *((code_root / "lib" / "chip_supergoal" / name, Path("lib/chip_supergoal") / name) for name in RUNTIME_MODULES),
        *((resource_root / "templates" / name, Path("templates") / name) for name in RUNTIME_TEMPLATES if name != "PROTOCOL.md"),
        *((resource_root / "spec" / name, Path("spec") / name) for name in RUNTIME_SPEC_FILES if name != "risk-policy.json"),
        *((resource_root / "profiles" / name, Path("profiles") / name) for name in RUNTIME_PROFILES),
        (protocol_source, Path("templates/PROTOCOL.md")),
        (risk_policy_source, Path("spec/risk-policy.json")),
    )
    for source, relative in inventory:
        if not source.is_file():
            raise FileNotFoundError(f"required package resource is missing: {source}")
        destination = out_path / relative
        _copy_text(source, destination)
        if logical_mode(relative) == "0755":
            os.chmod(destination, 0o755)


def initial_state(contract: Contract, contract_sha256: str) -> State:
    ready = [phase for phase in contract.phases if not phase.depends_on]
    if not ready:
        raise CompileSafetyError("contract has no dependency-ready initial phase")
    phase = min(ready, key=lambda item: item.ordinal)
    return State(
        goal_id=contract.goal.id,
        contract_sha256=contract_sha256,
        state_revision=1,
        lifecycle="COMPILED",
        current_phase_id=phase.id,
        phase_status="PENDING",
        blocker=None,
        attempt=0,
        audit_round=0,
    )


def _load_sealed_manifest(root: Path) -> dict:
    manifest_path = root / "MANIFEST.json"
    contract_path = root / "CONTRACT.json"
    if not manifest_path.is_file() or not contract_path.is_file():
        raise CompileSafetyError("existing output is not a sealed chip-supergoal package")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CompileSafetyError("existing output manifest is malformed") from exc
    if not isinstance(manifest, dict):
        raise CompileSafetyError("existing output manifest has unsupported shape")
    if manifest.get("manifest_version") != "1.1" or not isinstance(manifest.get("artifacts"), list):
        raise CompileSafetyError(
            "existing output manifest is unsupported; recompile the source contract as a manifest 1.1 package"
        )
    diagnostics = validate_package(root)
    if diagnostics:
        codes = ", ".join(sorted({diagnostic.code for diagnostic in diagnostics}))
        raise CompileSafetyError(
            f"refusing to overwrite an invalid sealed chip-supergoal package: {codes}"
        )
    return manifest


def _assert_pristine_runtime(root: Path, contract: Contract) -> None:
    try:
        state = read_state(root / "runtime" / "STATE.json")
        expected = initial_state(contract, file_sha256(root / "CONTRACT.json"))
        evidence = json.loads((root / "runtime" / "evidence.json").read_text(encoding="utf-8"))
        events = read_events(root / "runtime" / "events.jsonl")
    except Exception as exc:
        raise CompileSafetyError("refusing to overwrite started runtime package") from exc
    optional_paths = [
        item["path"] for item in MUTABLE_PATHS if not item["required"]
    ]
    if (
        state != expected
        or evidence != []
        or len(events) != 1
        or events[0].get("event_type") != "state_initialized"
        or any((root / relative).exists() for relative in optional_paths)
    ):
        raise CompileSafetyError("refusing to overwrite started runtime package")


def _assert_safe_target(out_path: Path, contract: Contract) -> None:
    if out_path.exists():
        if out_path.is_symlink() or not out_path.is_dir():
            raise CompileSafetyError("output target must be a directory or absent")
        _load_sealed_manifest(out_path)
        try:
            existing = load_contract(out_path / "CONTRACT.json")
        except Exception as exc:
            raise CompileSafetyError("existing output contract is malformed") from exc
        if existing.goal.id != contract.goal.id:
            raise CompileSafetyError("refusing to overwrite a package for a different goal id")
        _assert_pristine_runtime(out_path, existing)
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


def _render_package(
    resolved: ResolvedContract,
    out_path: Path,
    *,
    template_protocol: str | Path | None = None,
    resource_root: str | Path | None = None,
    risk_policy_path: str | Path | None = None,
) -> None:
    contract = resolved.contract
    resources = Path(resource_root) if resource_root is not None else repository_resource_root()
    protocol_source = Path(template_protocol) if template_protocol is not None else resources / "templates/PROTOCOL.md"
    risk_policy_source = Path(risk_policy_path) if risk_policy_path is not None else resources / "spec/risk-policy.json"
    out_path.mkdir(parents=True, exist_ok=False)
    phases_dir = out_path / "phases"
    phases_dir.mkdir()
    write_bytes_atomic(out_path / "CONTRACT.json", resolved.canonical_bytes)
    _write(out_path / "THINKING.md", render_thinking(contract))
    if research_required(contract) or research_gate(contract):
        _write(out_path / "RESEARCH.md", render_research_markdown(contract))
    _write(out_path / "LOOP_DESIGN.md", render_loop_design(contract))
    _write(out_path / "ROADMAP.md", render_roadmap(contract))
    _write(out_path / "LAUNCH_GOAL.md", render_launch_goal(contract))
    protocol_text = protocol_source.read_text(encoding="utf-8")
    _write(out_path / "PROTOCOL.md", protocol_text)
    for i in range(len(contract.phases)):
        _write(phases_dir / f"phase-{i+1:02d}.md", render_phase(contract, i))
    if research_required(contract) or research_gate(contract):
        _write(out_path / "reports" / "research.json", json.dumps(research_report(contract), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    StateStore(out_path).initialize(initial_state(contract, resolved.contract_sha256))
    _write(out_path / "runtime" / "evidence.json", "[]\n")
    _copy_runtime_inventory(
        out_path,
        resource_root=resources,
        protocol_source=protocol_source,
        risk_policy_source=risk_policy_source,
    )
    manifest = build_manifest(
        out_path,
        source_contract_sha256=resolved.source_sha256,
        contract_sha256=resolved.contract_sha256,
    )
    _write(out_path / "MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _compile_resolved(
    resolved: ResolvedContract,
    out: str | Path,
    *,
    template_protocol: str | Path | None = None,
    contract_source: str | Path | None = None,
    resource_root: str | Path | None = None,
    risk_policy_path: str | Path | None = None,
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
        _render_package(
            resolved,
            staging,
            template_protocol=template_protocol,
            resource_root=resource_root,
            risk_policy_path=risk_policy_path,
        )
        diagnostics = validate_package(staging)
        if diagnostics:
            codes = ", ".join(sorted({diagnostic.code for diagnostic in diagnostics}))
            raise CompileSafetyError(f"staging package validation failed: {codes}")
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
        resource_root=resource_root,
        risk_policy_path=risk_policy_path,
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
        resource_root=resource_root,
        risk_policy_path=risk_policy_path,
    )
