from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from .diagnostics import Diagnostic, diagnostic_metadata
from .events import EVENT_FIELDS, read_events, verify_event_chain
from .model import canonical_json, load_contract
from .pipeline import contract_diagnostics, repository_resource_root
from .portable import (
    MUTABLE_PATH_NAMES,
    MUTABLE_PATHS,
    REQUIRED_MUTABLE_PATHS,
    SEALED_RUNTIME_PATHS,
    canonical_text_bytes,
    logical_mode,
)
from .render import render_launch_goal, render_loop_design, render_phase, render_roadmap, render_thinking
from .research import render_research_markdown, research_gate, research_report, research_required, validate_research_gate
from .state import LIFECYCLES, State, render_state_md, state_json_bytes

REQUIRED_LOOP_SECTIONS = [
    "Goal", "Context sources", "Host model", "Reviewer / judge model", "Verification gates",
    "State checkpoints", "Stop conditions", "Budget", "Boundaries", "Failure recovery",
    "Human approvals", "ASCII preview",
]
REQUIRED_PHASE_SECTIONS = ["Work", "Acceptance criteria", "Mandatory commands", "Evidence required"]


def _diag(code: str, invariant_id: str, artifact: str, pointer: str, message: str, remediation: str, *, severity: str = "error", stage: str = "preflight") -> Diagnostic:
    metadata = diagnostic_metadata(code)
    if (invariant_id, stage) != (metadata.invariant, metadata.stage):
        raise ValueError(f"diagnostic metadata mismatch for {code}")
    return Diagnostic(code=code, severity=severity, blocking_stage=metadata.stage, invariant_id=metadata.invariant, artifact=artifact, pointer=pointer, message=message, remediation=remediation)


def section_text(text: str, heading: str) -> str | None:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^##\s+{re.escape(heading)}\s*$", line):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^##\s+", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def substantive_lines(section: str) -> list[str]:
    result = []
    for line in section.splitlines():
        line = line.strip()
        if not line or line.startswith("```"):
            continue
        normalized = re.sub(r"^([-*]|\d+\.)\s+", "", line).strip()
        if re.fullmatch(r"(<[^>]+>|\{\{[^}]+\}\}|TODO:?|TBD|none|n/a|\.\.\.|placeholder|replace me)", normalized, re.I):
            continue
        result.append(normalized)
    return result


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zА-Яа-я0-9_]+", text))


def validate_loop_design(path: str | Path, *, instantiated: bool = False) -> list[Diagnostic]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="ignore")
    diagnostics: list[Diagnostic] = []
    for heading in REQUIRED_LOOP_SECTIONS:
        sec = section_text(text, heading)
        if sec is None:
            diagnostics.append(_diag("SGV-LOOP-MISSING-SECTION", "INV-VALIDATOR-001", str(p), f"/sections/{heading}", f"missing section ## {heading}", "Add the required LOOP_DESIGN.md section."))
            continue
        lines = substantive_lines(sec)
        if not lines:
            diagnostics.append(_diag("SGV-LOOP-EMPTY-SECTION", "INV-VALIDATOR-001", str(p), f"/sections/{heading}", f"section ## {heading} has no substantive content", "Replace placeholders with concrete loop design content."))
        if instantiated and _word_count(" ".join(lines)) < 4 and heading != "ASCII preview":
            diagnostics.append(_diag("SGV-LOOP-WEAK-SECTION", "INV-VALIDATOR-001", str(p), f"/sections/{heading}", f"section ## {heading} is too weak for an instantiated loop", "Describe concrete actors, limits, gates, or recovery behavior."))
    if re.search(r"^SUPERGOAL_GOAL_BODY:", text, re.M):
        diagnostics.append(_diag("SGV-LOOP-LAUNCH-BODY", "INV-LAUNCH-001", str(p), "/", "LOOP_DESIGN.md contains a launch body", "Move the launch marker to LAUNCH_GOAL.md only."))
    if instantiated:
        checks = [
            ("Budget", r"[0-9]", "SGV-LOOP-BUDGET-MISSING-LIMIT", "Budget must include numeric limits."),
            ("Stop conditions", r"(?i)(retry|retries|attempt|iteration|no-progress|попыт|итерац|max|<=|≤)", "SGV-LOOP-STOP-MISSING-LIMIT", "Stop conditions must include retry/iteration/no-progress limits."),
            ("Verification gates", r"(?i)(test|pytest|npm|bash|curl|smoke|verify|validator|programmatic|command)", "SGV-LOOP-GATE-NOT-PROGRAMMATIC", "Verification gates must name concrete programmatic checks."),
            ("Reviewer / judge model", r"(?i)(reviewer|judge|rpd|senior|critic|model|xhigh)", "SGV-LOOP-REVIEWER-MISSING", "Reviewer/judge model must name the reviewer mode."),
            ("Boundaries", r"(?i)(secret|credential|env|token|redact|private|public|egress|telegram|payment|prod|production)", "SGV-LOOP-BOUNDARY-MISSING", "Boundaries must include privacy/secret/egress or production limits."),
            ("Failure recovery", r"(?i)(rollback|resume|recover|fallback|handoff|fail|blocker|retry)", "SGV-LOOP-RECOVERY-MISSING", "Failure recovery must include a concrete fallback/retry path."),
        ]
        for heading, pattern, code, msg in checks:
            sec = section_text(text, heading) or ""
            if not re.search(pattern, sec):
                diagnostics.append(_diag(code, "INV-VALIDATOR-001", str(p), f"/sections/{heading}", msg, msg))
    return diagnostics


def _metadata(text: str, label: str) -> str | None:
    m = re.search(rf"^{re.escape(label)}:\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip() if m else None


def _bullet_count(sec: str) -> int:
    return sum(1 for line in sec.splitlines() if re.match(r"^\s*[-*]\s+", line))


def validate_phase_markdown(path: str | Path) -> list[Diagnostic]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="ignore")
    diagnostics: list[Diagnostic] = []
    if not re.search(r"^SUPERGOAL_PHASE_START\s*$", text, re.M):
        diagnostics.append(_diag("SGV-PHASE-MISSING-MARKER", "INV-VALIDATOR-001", str(p), "/marker", "missing SUPERGOAL_PHASE_START", "Add the phase-start marker."))
    required_meta = ["Phase", "Task", "Mandatory commands", "Acceptance criteria", "Evidence required", "Depends on phases", "RPD required", "RPD focus"]
    meta = {k: _metadata(text, k) for k in required_meta}
    for k, v in meta.items():
        if not v:
            diagnostics.append(_diag("SGV-PHASE-MISSING-METADATA", "INV-VALIDATOR-001", str(p), f"/metadata/{k}", f"missing {k} metadata", "Add the required phase metadata line."))
    for heading in REQUIRED_PHASE_SECTIONS:
        sec = section_text(text, heading)
        if sec is None:
            diagnostics.append(_diag("SGV-PHASE-MISSING-SECTION", "INV-VALIDATOR-001", str(p), f"/sections/{heading}", f"missing section ## {heading}", "Add the exact required section heading."))
            continue
        if not substantive_lines(sec):
            diagnostics.append(_diag("SGV-PHASE-EMPTY-SECTION", "INV-VALIDATOR-001", str(p), f"/sections/{heading}", f"section ## {heading} has no substantive content", "Add concrete non-placeholder bullets."))
    phase_meta = meta.get("Phase") or ""
    m = re.search(r"(\d+)\s+of\s+(\d+)", phase_meta)
    phase_n = total = None
    if m:
        phase_n, total = int(m.group(1)), int(m.group(2))
        if phase_n < 1 or phase_n > total:
            diagnostics.append(_diag("SGV-PHASE-ORDINAL-OUT-OF-RANGE", "INV-VALIDATOR-001", str(p), "/metadata/Phase", f"Phase {phase_n} of {total} is impossible", "Regenerate phase ordinal from the phase array."))
    elif meta.get("Phase"):
        diagnostics.append(_diag("SGV-PHASE-BAD-ORDINAL", "INV-VALIDATOR-001", str(p), "/metadata/Phase", "Phase metadata must include 'N of TOTAL'", "Use 'Phase: N of TOTAL — name'."))
    crit_meta = meta.get("Acceptance criteria")
    crit_sec = section_text(text, "Acceptance criteria") or ""
    if crit_meta and crit_meta.isdigit():
        actual = _bullet_count(crit_sec)
        if int(crit_meta) != actual:
            diagnostics.append(_diag("SGV-PHASE-COUNT-MISMATCH", "INV-VALIDATOR-001", str(p), "/metadata/Acceptance criteria", f"declared {crit_meta} criteria, found {actual}", "Regenerate the count from criteria bullets."))
    if meta.get("Mandatory commands") and re.fullmatch(r"(?i)(TBD|TODO|PLACEHOLDER|none|n/a)", meta["Mandatory commands"]):
        diagnostics.append(_diag("SGV-PHASE-PLACEHOLDER-COMMAND", "INV-VALIDATOR-001", str(p), "/metadata/Mandatory commands", "mandatory commands metadata is a placeholder", "Name a real command or explicit safe no-op with reason."))
    if meta.get("RPD required") not in {None, "yes", "no"}:
        diagnostics.append(_diag("SGV-PHASE-RPD-ENUM", "INV-RPD-001", str(p), "/metadata/RPD required", "RPD required must be yes or no", "Use yes/no."))
    focus = meta.get("RPD focus")
    if focus and focus not in {"security", "integration", "ux", "migration", "data-loss", "gateway", "payments", "none"}:
        diagnostics.append(_diag("SGV-PHASE-RPD-FOCUS-ENUM", "INV-RPD-001", str(p), "/metadata/RPD focus", "RPD focus has unsupported value", "Use the allowed focus enum."))
    if meta.get("RPD required") == "no" and focus and focus != "none":
        diagnostics.append(_diag("SGV-PHASE-RPD-MISMATCH", "INV-RPD-001", str(p), "/metadata/RPD", "RPD focus is set while RPD required is no", "Set RPD required yes or focus none with a waiver."))
    deps = meta.get("Depends on phases") or ""
    if total is not None and deps.lower() != "none":
        for dep in re.findall(r"\d+", deps):
            d = int(dep)
            if d < 1 or d > total:
                diagnostics.append(_diag("SGV-PHASE-MISSING-DEPENDENCY", "INV-VALIDATOR-001", str(p), "/metadata/Depends on phases", f"dependency {dep} is outside 1..{total}", "Reference only existing phases."))
            if phase_n is not None and d == phase_n:
                diagnostics.append(_diag("SGV-PHASE-SELF-DEPENDENCY", "INV-VALIDATOR-001", str(p), "/metadata/Depends on phases", "phase depends on itself", "Remove self dependency."))
    weak_words = {"good", "clean", "secure", "fast", "perfect", "works", "x"}
    for line in substantive_lines(crit_sec):
        words = set(w.lower() for w in re.findall(r"[A-Za-zА-Яа-я0-9_]+", line))
        if len(words) <= 2 or words <= weak_words:
            diagnostics.append(_diag("SGV-CRITERION-WEAK", "INV-VALIDATOR-001", str(p), "/sections/Acceptance criteria", f"weak criterion: {line}", "Use observable pass/fail criteria with verifier/evidence."))
    return diagnostics


def validate_contract_file(
    path: str | Path,
    risk_policy_path: str | Path | None = None,
    *,
    resource_root: str | Path | None = None,
) -> list[Diagnostic]:
    root = Path(resource_root) if resource_root is not None else repository_resource_root()
    result = contract_diagnostics(
        path,
        resource_root=root,
        risk_policy_path=risk_policy_path,
    )
    return list(result.diagnostics)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_MANIFEST_KEYS = {
    "manifest_version",
    "source_contract_sha256",
    "contract_sha256",
    "artifacts",
    "mutable_paths",
    "package_fingerprint",
}
_ARTIFACT_KEYS = {"path", "sha256", "bytes", "mode"}
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_EVENT_ID_PATTERN = re.compile(r"^EVT-[0-9]{6}$")
_TIMESTAMP_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


def _expected_generated_files(
    root: Path,
) -> tuple[dict[str, bytes], object | None, list[Diagnostic]]:
    contract_path = root / "CONTRACT.json"
    result = contract_diagnostics(contract_path, resource_root=root)
    if result.diagnostics:
        if any(item.code == "SGV-CONTRACT-MALFORMED" for item in result.diagnostics):
            return {}, None, [
                _diag(
                    "SGV-PACKAGE-CONTRACT-MALFORMED",
                    "INV-VALIDATOR-001",
                    str(root),
                    "/CONTRACT.json",
                    "package contract is malformed",
                    "Regenerate the package from a valid CONTRACT.json.",
                )
            ]
        return {}, None, list(result.diagnostics)
    if result.resolved is None:
        return {}, None, [
            _diag(
                "SGV-PACKAGE-CONTRACT-MALFORMED",
                "INV-VALIDATOR-001",
                str(root),
                "/CONTRACT.json",
                "package contract could not be resolved",
                "Regenerate the package from a valid CONTRACT.json.",
            )
        ]
    contract = result.resolved.contract
    expected: dict[str, bytes] = {
        "CONTRACT.json": result.resolved.canonical_bytes,
        "THINKING.md": render_thinking(contract).encode("utf-8"),
        "LOOP_DESIGN.md": render_loop_design(contract).encode("utf-8"),
        "ROADMAP.md": render_roadmap(contract).encode("utf-8"),
        "LAUNCH_GOAL.md": render_launch_goal(contract).encode("utf-8"),
    }
    protocol_template = root / "templates" / "PROTOCOL.md"
    if protocol_template.is_file():
        try:
            expected["PROTOCOL.md"] = canonical_text_bytes(
                protocol_template.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError):
            pass
    if research_required(contract) or research_gate(contract):
        expected["RESEARCH.md"] = render_research_markdown(contract).encode("utf-8")
        expected["reports/research.json"] = (
            json.dumps(research_report(contract), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
    for index in range(len(contract.phases)):
        expected[f"phases/phase-{index + 1:02d}.md"] = render_phase(
            contract, index
        ).encode("utf-8")
    return expected, contract, []


def _manifest_records(
    root: Path,
) -> tuple[dict | None, dict[str, dict], list[Diagnostic]]:
    manifest_path = root / "MANIFEST.json"
    if not manifest_path.is_file():
        return None, {}, [
            _diag(
                "SGV-PACKAGE-MISSING-MANIFEST",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json",
                "missing MANIFEST.json",
                "Recompile the package.",
            )
        ]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None, {}, [
            _diag(
                "SGV-PACKAGE-MANIFEST-MALFORMED",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json",
                "package manifest is malformed",
                "Recompile the package.",
            )
        ]
    if not isinstance(manifest, dict):
        return None, {}, [
            _diag(
                "SGV-PACKAGE-MANIFEST-SHAPE",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json",
                "manifest has unsupported shape",
                "Recompile the package with manifest_version 1.1.",
            )
        ]
    if manifest.get("manifest_version") != "1.1":
        return manifest, {}, [
            _diag(
                "SGV-PACKAGE-MANIFEST-SHAPE",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json",
                "manifest version is unsupported",
                "Recompile the source contract to produce manifest_version 1.1.",
            )
        ]
    if set(manifest) != _MANIFEST_KEYS or not isinstance(manifest.get("artifacts"), list):
        return manifest, {}, [
            _diag(
                "SGV-PACKAGE-MANIFEST-SHAPE",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json",
                "manifest has unsupported shape",
                "Recompile the package with the canonical manifest 1.1 fields.",
            )
        ]

    diagnostics: list[Diagnostic] = []
    for field in ("source_contract_sha256", "contract_sha256", "package_fingerprint"):
        if not isinstance(manifest.get(field), str) or not _SHA256_PATTERN.fullmatch(
            manifest[field]
        ):
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MANIFEST-SHAPE",
                    "INV-VALIDATOR-001",
                    str(root),
                    f"/MANIFEST.json/{field}",
                    f"manifest {field} is malformed",
                    "Recompile the package.",
                )
            )
    if manifest.get("mutable_paths") != [dict(item) for item in MUTABLE_PATHS]:
        diagnostics.append(
            _diag(
                "SGV-PACKAGE-MUTABLE-REGISTRY",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json/mutable_paths",
                "manifest mutable path registry is not canonical",
                "Recompile the package; do not add mutable path patterns or exceptions.",
            )
        )

    records: dict[str, dict] = {}
    ordered_paths: list[str] = []
    for item in manifest["artifacts"]:
        if not isinstance(item, dict) or set(item) != _ARTIFACT_KEYS:
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MANIFEST-SHAPE",
                    "INV-VALIDATOR-001",
                    str(root),
                    "/MANIFEST.json/artifacts",
                    "artifact record is malformed",
                    "Use exact path/sha256/bytes/mode records.",
                )
            )
            continue
        relative = item.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or relative in records
            or relative.startswith("/")
            or "\\" in relative
            or ".." in Path(relative).parts
            or "\x00" in relative
        ):
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MANIFEST-PATH",
                    "INV-VALIDATOR-001",
                    str(root),
                    "/MANIFEST.json/artifacts",
                    "manifest path is unsafe or duplicated",
                    "Use unique normalized relative package paths.",
                )
            )
            continue
        if (
            not isinstance(item.get("sha256"), str)
            or not _SHA256_PATTERN.fullmatch(item["sha256"])
            or type(item.get("bytes")) is not int
            or item["bytes"] < 0
            or item.get("mode") not in {"0644", "0755"}
        ):
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MANIFEST-SHAPE",
                    "INV-VALIDATOR-001",
                    str(root),
                    f"/MANIFEST.json/artifacts/{relative}",
                    "artifact identity record is malformed",
                    "Recompile the package.",
                )
            )
            continue
        records[relative] = item
        ordered_paths.append(relative)
    if ordered_paths != sorted(ordered_paths):
        diagnostics.append(
            _diag(
                "SGV-PACKAGE-MANIFEST-SHAPE",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json/artifacts",
                "artifact records are not canonically ordered",
                "Recompile the package.",
            )
        )
    joined = "\n".join(
        f"{item['path']} {item['sha256']} {item['bytes']} {item['mode']}"
        for item in records.values()
    )
    expected_fingerprint = hashlib.sha256(joined.encode()).hexdigest()
    if manifest.get("package_fingerprint") != expected_fingerprint:
        diagnostics.append(
            _diag(
                "SGV-PACKAGE-FINGERPRINT-MISMATCH",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json/package_fingerprint",
                "package fingerprint does not match sealed artifact records",
                "Recompile the package from canonical sealed bytes.",
            )
        )
    contract_path = root / "CONTRACT.json"
    if contract_path.is_file() and manifest.get("contract_sha256") != _sha256_bytes(
        contract_path.read_bytes()
    ):
        diagnostics.append(
            _diag(
                "SGV-PACKAGE-MANIFEST-HASH",
                "INV-VALIDATOR-001",
                str(root),
                "/MANIFEST.json/contract_sha256",
                "manifest contract identity does not match emitted CONTRACT.json bytes",
                "Recompile the package.",
            )
        )
    return manifest, records, diagnostics


def _mutable_diagnostic(
    code: str, root: Path, relative: str, message: str, remediation: str
) -> Diagnostic:
    return _diag(
        code,
        "INV-VALIDATOR-001",
        str(root),
        f"/{relative}",
        message,
        remediation,
    )


def _validate_mutable_plane(
    root: Path, contract: object | None, contract_sha256: str | None
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for relative in sorted(REQUIRED_MUTABLE_PATHS):
        if not (root / relative).is_file():
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MISSING-FILE",
                    "INV-VALIDATOR-001",
                    str(root),
                    f"/{relative}",
                    f"missing required mutable file {relative}",
                    "Recompile the package to initialize the mutable runtime plane.",
                )
            )

    state: State | None = None
    state_path = root / "runtime" / "STATE.json"
    if state_path.is_file():
        try:
            state_data = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(state_data, dict):
                raise ValueError("state must be an object")
            state = State.from_dict(state_data)
            if state_path.read_bytes() != state_json_bytes(state):
                raise ValueError("state bytes are not canonical")
            phase_ids = (
                {phase.id for phase in getattr(contract, "phases", ())}
                if contract is not None
                else set()
            )
            goal_id = getattr(getattr(contract, "goal", None), "id", None)
            if (
                state.state_revision < 1
                or state.lifecycle == "DRAFT"
                or state.lifecycle not in LIFECYCLES
                or state.goal_id != goal_id
                or state.contract_sha256 != contract_sha256
                or state.current_phase_id not in phase_ids
            ):
                raise ValueError("state identity or lifecycle is inconsistent")
        except Exception:
            diagnostics.append(
                _mutable_diagnostic(
                    "SGV-PACKAGE-STATE-MALFORMED",
                    root,
                    "runtime/STATE.json",
                    "runtime state is malformed or inconsistent with the emitted contract",
                    "Recover or recompile the package before execution.",
                )
            )
            state = None

    projection_path = root / "STATE.md"
    if projection_path.is_file() and state is not None:
        try:
            if projection_path.read_bytes() != render_state_md(state).encode("utf-8"):
                raise ValueError("projection mismatch")
        except Exception:
            diagnostics.append(
                _mutable_diagnostic(
                    "SGV-PACKAGE-STATE-MALFORMED",
                    root,
                    "STATE.md",
                    "STATE.md is not the canonical projection of runtime/STATE.json",
                    "Regenerate the projection from runtime/STATE.json.",
                )
            )

    events_path = root / "runtime" / "events.jsonl"
    if events_path.is_file():
        try:
            raw_events = events_path.read_bytes()
            if not raw_events.endswith(b"\n") or b"\r" in raw_events:
                raise ValueError("events are not canonical LF JSONL")
            events = read_events(events_path)
            if not events or verify_event_chain(events):
                raise ValueError("event chain is invalid")
            if events[0].get("event_type") != "state_initialized":
                raise ValueError("missing genesis event")
            if events[0].get("state_revision") != 1:
                raise ValueError("genesis revision is invalid")
            previous_revision = 0
            phase_ids = (
                {phase.id for phase in getattr(contract, "phases", ())}
                if contract is not None
                else set()
            )
            goal_id = getattr(getattr(contract, "goal", None), "id", None)
            for index, event in enumerate(events, 1):
                if set(event) != EVENT_FIELDS:
                    raise ValueError("event fields are invalid")
                if event.get("event_id") != f"EVT-{index:06d}" or not _EVENT_ID_PATTERN.fullmatch(
                    event["event_id"]
                ):
                    raise ValueError("event id is invalid")
                revision = event.get("state_revision")
                if type(revision) is not int or revision < previous_revision or revision < 1:
                    raise ValueError("event revision is invalid")
                previous_revision = revision
                if (
                    event.get("goal_id") != goal_id
                    or event.get("contract_sha256") != contract_sha256
                    or event.get("phase_id") not in phase_ids
                    or not isinstance(event.get("actor"), str)
                    or not isinstance(event.get("event_type"), str)
                    or not isinstance(event.get("evidence_ids"), list)
                    or not isinstance(event.get("timestamp"), str)
                    or not _TIMESTAMP_PATTERN.fullmatch(event["timestamp"])
                    or not isinstance(event.get("state_sha256"), str)
                    or not _SHA256_PATTERN.fullmatch(event["state_sha256"])
                ):
                    raise ValueError("event identity is invalid")
            if state is None:
                raise ValueError("state unavailable")
            if events[-1].get("state_revision") != state.state_revision:
                raise ValueError("event tail revision differs from state")
            if events[-1].get("state_sha256") != _sha256_bytes(state_path.read_bytes()):
                raise ValueError("event tail state hash differs from state")
        except Exception:
            diagnostics.append(
                _mutable_diagnostic(
                    "SGV-PACKAGE-EVENTS-MALFORMED",
                    root,
                    "runtime/events.jsonl",
                    "runtime event journal is malformed or inconsistent",
                    "Recover the event chain or recompile a pristine package.",
                )
            )

    evidence_path = root / "runtime" / "evidence.json"
    if evidence_path.is_file():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            if not isinstance(evidence, list) or not all(
                isinstance(item, dict) for item in evidence
            ):
                raise ValueError("evidence must be a list of records")
        except Exception:
            diagnostics.append(
                _mutable_diagnostic(
                    "SGV-PACKAGE-EVIDENCE-MALFORMED",
                    root,
                    "runtime/evidence.json",
                    "runtime evidence is not a JSON list of records",
                    "Restore a valid evidence list or recompile a pristine package.",
                )
            )

    lock_path = root / "runtime" / "state.lock"
    if lock_path.exists() and (not lock_path.is_file() or lock_path.read_bytes() != b"\0"):
        diagnostics.append(
            _mutable_diagnostic(
                "SGV-PACKAGE-MUTABLE-MALFORMED",
                root,
                "runtime/state.lock",
                "runtime lock must be a regular one-byte zero file",
                "Recreate the package lock through the portable runtime.",
            )
        )
    for relative in (
        "reports/final-audit.json",
        "out/review-md-files-delivery-receipt.json",
        "out/final-artifacts-delivery-receipt.json",
        "out/final-artifacts-manifest.json",
    ):
        path = root / relative
        if path.is_file():
            try:
                if not isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
                    raise ValueError("mutable JSON must be an object")
            except Exception:
                diagnostics.append(
                    _mutable_diagnostic(
                        "SGV-PACKAGE-MUTABLE-MALFORMED",
                        root,
                        relative,
                        f"{relative} is malformed",
                        "Regenerate the mutable artifact through sgctl.",
                    )
                )
    for relative in ("reports/final-audit.md", "reports/terminal-record.txt"):
        path = root / relative
        if path.is_file():
            try:
                data = path.read_bytes()
                data.decode("utf-8")
                if b"\r" in data:
                    raise ValueError("mutable text must use LF")
            except Exception:
                diagnostics.append(
                    _mutable_diagnostic(
                        "SGV-PACKAGE-MUTABLE-MALFORMED",
                        root,
                        relative,
                        f"{relative} is not canonical UTF-8/LF text",
                        "Regenerate the mutable artifact through sgctl.",
                    )
                )
    return diagnostics


def validate_package(root: str | Path) -> list[Diagnostic]:
    package_root = Path(root)
    manifest, records, manifest_diagnostics = _manifest_records(package_root)
    if isinstance(manifest, dict) and manifest.get("manifest_version") != "1.1":
        return manifest_diagnostics
    diagnostics: list[Diagnostic] = list(manifest_diagnostics)
    for required in (
        "CONTRACT.json",
        "THINKING.md",
        "LOOP_DESIGN.md",
        "ROADMAP.md",
        "STATE.md",
        "PROTOCOL.md",
        "LAUNCH_GOAL.md",
        "MANIFEST.json",
    ):
        if not (package_root / required).is_file():
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MISSING-FILE",
                    "INV-VALIDATOR-001",
                    str(package_root),
                    f"/{required}",
                    f"missing {required}",
                    "Recompile the package.",
                )
            )

    expected_generated, contract, generated_diagnostics = _expected_generated_files(
        package_root
    )
    diagnostics.extend(generated_diagnostics)
    for relative, expected_bytes in expected_generated.items():
        path = package_root / relative
        if not path.is_file():
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MISSING-FILE",
                    "INV-VALIDATOR-001",
                    str(package_root),
                    f"/{relative}",
                    f"missing {relative}",
                    "Recompile the package.",
                )
            )
        elif path.read_bytes() != expected_bytes:
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-GENERATED-DRIFT",
                    "INV-VALIDATOR-001",
                    str(package_root),
                    f"/{relative}",
                    f"{relative} no longer matches package-local canonical resources",
                    "Recompile the package; do not hand-edit generated views.",
                )
            )

    launch_hits: list[str] = []
    for path in package_root.rglob("*.md"):
        relative = path.relative_to(package_root).as_posix()
        if (
            relative.startswith("templates/")
            or relative.startswith("out/")
            or relative == "reports/final-audit.md"
        ):
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            if line.startswith("SUPERGOAL_GOAL_BODY:"):
                launch_hits.append(f"{relative}:{line_number}")
    if len(launch_hits) != 1 or not launch_hits[0].startswith("LAUNCH_GOAL.md:"):
        diagnostics.append(
            _diag(
                "SGV-PACKAGE-LAUNCH-MARKER",
                "INV-LAUNCH-001",
                str(package_root),
                "/LAUNCH_GOAL.md",
                f"expected one launch marker in LAUNCH_GOAL.md, got {launch_hits}",
                "Keep the actual launch body only in LAUNCH_GOAL.md.",
            )
        )

    required_sealed = set(SEALED_RUNTIME_PATHS) | set(expected_generated)
    for relative in sorted(required_sealed - set(expected_generated)):
        if not (package_root / relative).is_file():
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MISSING-FILE",
                    "INV-VALIDATOR-001",
                    str(package_root),
                    f"/{relative}",
                    f"missing sealed package file {relative}",
                    "Recompile the package.",
                )
            )

    actual_sealed = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
        and path.relative_to(package_root).as_posix() != "MANIFEST.json"
        and path.relative_to(package_root).as_posix() not in MUTABLE_PATH_NAMES
    )
    if records:
        record_files = sorted(records)
        if actual_sealed != record_files or not required_sealed <= set(records):
            diagnostics.append(
                _diag(
                    "SGV-PACKAGE-MANIFEST-FILESET",
                    "INV-VALIDATOR-001",
                    str(package_root),
                    "/MANIFEST.json/artifacts",
                    "sealed manifest files do not match the exact package inventory",
                    "Recompile the package and remove unknown or unsealed files.",
                )
            )
        for relative, item in records.items():
            path = package_root / relative
            if not path.is_file():
                continue
            data = path.read_bytes()
            if (
                item.get("sha256") != _sha256_bytes(data)
                or item.get("bytes") != len(data)
                or item.get("mode") != logical_mode(relative)
            ):
                diagnostics.append(
                    _diag(
                        "SGV-PACKAGE-MANIFEST-HASH",
                        "INV-VALIDATOR-001",
                        str(package_root),
                        f"/MANIFEST.json/artifacts/{relative}",
                        f"manifest record for {relative} does not match current bytes or mode",
                        "Recompile the package from canonical resources.",
                    )
                )
    elif manifest is not None and manifest.get("manifest_version") == "1.1":
        diagnostics.append(
            _diag(
                "SGV-PACKAGE-MANIFEST-FILESET",
                "INV-VALIDATOR-001",
                str(package_root),
                "/MANIFEST.json/artifacts",
                "manifest contains no valid sealed artifact inventory",
                "Recompile the package.",
            )
        )

    contract_sha256 = (
        manifest.get("contract_sha256")
        if isinstance(manifest, dict)
        and isinstance(manifest.get("contract_sha256"), str)
        and _SHA256_PATTERN.fullmatch(manifest["contract_sha256"])
        else _sha256_bytes((package_root / "CONTRACT.json").read_bytes())
        if (package_root / "CONTRACT.json").is_file()
        else None
    )
    diagnostics.extend(
        _validate_mutable_plane(package_root, contract, contract_sha256)
    )

    unique: list[Diagnostic] = []
    seen: set[tuple[str, str, str, str]] = set()
    for diagnostic in diagnostics:
        identity = (
            diagnostic.code,
            diagnostic.artifact,
            diagnostic.pointer,
            diagnostic.message,
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(diagnostic)
    return unique
