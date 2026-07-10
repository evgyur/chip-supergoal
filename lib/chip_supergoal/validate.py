from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Iterable

from .diagnostics import Diagnostic
from .model import canonical_json, load_contract
from .normalize import semantic_errors
from .policy import load_risk_policy
from .render import render_launch_goal, render_loop_design, render_phase, render_roadmap, render_state, render_thinking
from .research import render_research_markdown, research_gate, research_report, research_required, validate_research_gate

REQUIRED_LOOP_SECTIONS = [
    "Goal", "Context sources", "Host model", "Reviewer / judge model", "Verification gates",
    "State checkpoints", "Stop conditions", "Budget", "Boundaries", "Failure recovery",
    "Human approvals", "ASCII preview",
]
REQUIRED_PHASE_SECTIONS = ["Work", "Acceptance criteria", "Mandatory commands", "Evidence required"]


def _diag(code: str, invariant_id: str, artifact: str, pointer: str, message: str, remediation: str, *, severity: str = "error", stage: str = "preflight") -> Diagnostic:
    return Diagnostic(code=code, severity=severity, blocking_stage=stage, invariant_id=invariant_id, artifact=artifact, pointer=pointer, message=message, remediation=remediation)


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


def validate_contract_file(path: str | Path, risk_policy_path: str | Path | None = None) -> list[Diagnostic]:
    p = Path(path)
    try:
        contract = load_contract(p)
        policy = load_risk_policy(risk_policy_path) if risk_policy_path else None
        errors = semantic_errors(contract, policy)
    except Exception as exc:
        return [_diag("SGV-CONTRACT-MALFORMED", "INV-VALIDATOR-001", str(p), "/", str(exc), "Fix the contract JSON shape/version/fields.")]
    diagnostics = [_diag("SGV-CONTRACT-SEMANTIC", "INV-VALIDATOR-001", str(p), "/", e, "Fix the semantic contract error.") for e in errors]
    diagnostics.extend(validate_research_gate(contract, artifact=str(p)))
    return diagnostics


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_mode(path: Path) -> str:
    return f"{stat.S_IMODE(path.stat().st_mode):04o}"


def _expected_generated_files(root: Path) -> tuple[dict[str, bytes], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    try:
        contract = load_contract(root / "CONTRACT.json")
        diagnostics.extend(validate_research_gate(contract, artifact=str(root / "CONTRACT.json")))
    except Exception as exc:
        diagnostics.append(_diag("SGV-PACKAGE-CONTRACT-MALFORMED", "INV-VALIDATOR-001", str(root), "/CONTRACT.json", str(exc), "Regenerate the package from a valid CONTRACT.json."))
        return {}, diagnostics
    expected: dict[str, bytes] = {
        "CONTRACT.json": canonical_json(contract).encode("utf-8"),
        "THINKING.md": render_thinking(contract).encode("utf-8"),
        "LOOP_DESIGN.md": render_loop_design(contract).encode("utf-8"),
        "ROADMAP.md": render_roadmap(contract).encode("utf-8"),
        "STATE.md": render_state(contract).encode("utf-8"),
        "LAUNCH_GOAL.md": render_launch_goal(contract).encode("utf-8"),
    }
    if research_required(contract) or research_gate(contract):
        expected["RESEARCH.md"] = render_research_markdown(contract).encode("utf-8")
        expected["reports/research.json"] = (json.dumps(research_report(contract), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    for i in range(len(contract.phases)):
        expected[f"phases/phase-{i+1:02d}.md"] = render_phase(contract, i).encode("utf-8")
    return expected, diagnostics


def _manifest_records(root: Path) -> tuple[dict[str, dict], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    manifest_path = root / "MANIFEST.json"
    if not manifest_path.is_file():
        return {}, [_diag("SGV-PACKAGE-MISSING-MANIFEST", "INV-VALIDATOR-001", str(root), "/MANIFEST.json", "missing MANIFEST.json", "Regenerate the package.")]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [_diag("SGV-PACKAGE-MANIFEST-MALFORMED", "INV-VALIDATOR-001", str(root), "/MANIFEST.json", str(exc), "Regenerate MANIFEST.json.")]
    records_raw = manifest.get("artifacts")
    if manifest.get("manifest_version") != "1.0" or not isinstance(records_raw, list):
        diagnostics.append(_diag("SGV-PACKAGE-MANIFEST-SHAPE", "INV-VALIDATOR-001", str(root), "/MANIFEST.json", "manifest has unsupported shape", "Use manifest_version 1.0 with artifacts[]."))
        return {}, diagnostics
    records: dict[str, dict] = {}
    for item in records_raw:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            diagnostics.append(_diag("SGV-PACKAGE-MANIFEST-SHAPE", "INV-VALIDATOR-001", str(root), "/MANIFEST.json/artifacts", "artifact record is malformed", "Use path/sha256/bytes/mode records."))
            continue
        rel = item["path"]
        if rel in records or rel.startswith("/") or ".." in Path(rel).parts or "\x00" in rel:
            diagnostics.append(_diag("SGV-PACKAGE-MANIFEST-PATH", "INV-VALIDATOR-001", str(root), f"/MANIFEST.json/artifacts/{rel}", "manifest path is unsafe or duplicated", "Use unique relative package paths."))
            continue
        records[rel] = item
    joined = "\n".join(f"{r['path']} {r['sha256']} {r['bytes']} {r['mode']}" for r in records.values() if {'path','sha256','bytes','mode'} <= r.keys())
    expected_fingerprint = hashlib.sha256(joined.encode()).hexdigest()
    if manifest.get("package_fingerprint") != expected_fingerprint:
        diagnostics.append(_diag("SGV-PACKAGE-FINGERPRINT-MISMATCH", "INV-VALIDATOR-001", str(root), "/MANIFEST.json/package_fingerprint", "package fingerprint does not match artifact records", "Rebuild MANIFEST.json from current artifact bytes."))
    return records, diagnostics


def validate_package(root: str | Path) -> list[Diagnostic]:
    r = Path(root)
    diagnostics: list[Diagnostic] = []
    launch_hits = []
    for p in r.rglob("*.md"):
        if "out" in p.relative_to(r).parts:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if line.startswith("SUPERGOAL_GOAL_BODY:"):
                launch_hits.append(f"{p.relative_to(r)}:{n}")
    if len(launch_hits) != 1 or not launch_hits[0].startswith("LAUNCH_GOAL.md:"):
        diagnostics.append(_diag("SGV-PACKAGE-LAUNCH-MARKER", "INV-LAUNCH-001", str(r), "/LAUNCH_GOAL.md", f"expected one launch marker in LAUNCH_GOAL.md, got {launch_hits}", "Keep the actual launch body only in LAUNCH_GOAL.md."))
    for required in ["CONTRACT.json", "THINKING.md", "LOOP_DESIGN.md", "ROADMAP.md", "STATE.md", "PROTOCOL.md", "LAUNCH_GOAL.md", "MANIFEST.json"]:
        if not (r / required).is_file():
            diagnostics.append(_diag("SGV-PACKAGE-MISSING-FILE", "INV-VALIDATOR-001", str(r), f"/{required}", f"missing {required}", "Regenerate the package."))

    expected_generated, generated_diags = _expected_generated_files(r)
    diagnostics.extend(generated_diags)
    for rel, expected_bytes in expected_generated.items():
        p = r / rel
        if not p.is_file():
            diagnostics.append(_diag("SGV-PACKAGE-MISSING-FILE", "INV-VALIDATOR-001", str(r), f"/{rel}", f"missing {rel}", "Regenerate the package."))
            continue
        actual = p.read_bytes()
        if actual != expected_bytes:
            diagnostics.append(_diag("SGV-PACKAGE-GENERATED-DRIFT", "INV-VALIDATOR-001", str(r), f"/{rel}", f"{rel} no longer matches canonical CONTRACT.json rendering", "Regenerate the package; do not hand-edit generated views."))

    records, manifest_diags = _manifest_records(r)
    diagnostics.extend(manifest_diags)
    actual_files = sorted(p.relative_to(r).as_posix() for p in r.rglob("*") if p.is_file() and p.name != "MANIFEST.json" and "out" not in p.relative_to(r).parts)
    if records:
        record_files = sorted(records)
        if actual_files != record_files:
            diagnostics.append(_diag("SGV-PACKAGE-MANIFEST-FILESET", "INV-VALIDATOR-001", str(r), "/MANIFEST.json/artifacts", f"manifest files {record_files} do not match package files {actual_files}", "Regenerate MANIFEST.json from the package."))
        for rel, item in records.items():
            p = r / rel
            if not p.is_file():
                continue
            data = p.read_bytes()
            if item.get("sha256") != _sha256_bytes(data) or item.get("bytes") != len(data) or item.get("mode") != _file_mode(p):
                diagnostics.append(_diag("SGV-PACKAGE-MANIFEST-HASH", "INV-VALIDATOR-001", str(r), f"/MANIFEST.json/artifacts/{rel}", f"manifest record for {rel} does not match current bytes/mode", "Regenerate MANIFEST.json from current artifact bytes."))
    return diagnostics
