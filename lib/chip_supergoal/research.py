from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .diagnostics import Diagnostic
from .model import Contract

RESEARCH_TRIGGER_TAGS = {
    "auth",
    "payments",
    "security",
    "compliance",
    "migration",
    "gateway",
    "sdk",
    "api",
    "build-vs-buy",
    "greenfield",
}
RESEARCH_PROVIDERS = {"perplex", "official-docs", "context7", "web", "manual"}


def research_gate(contract: Contract) -> dict[str, Any]:
    raw = contract.compatibility.get("research_gate", {})
    return dict(raw) if isinstance(raw, dict) else {}


def research_required(contract: Contract) -> bool:
    gate = research_gate(contract)
    tags = {r.tag for r in contract.risks}
    for phase in contract.phases:
        tags.update(phase.risk_tags)
    inferred = bool(tags & RESEARCH_TRIGGER_TAGS)
    return bool(gate.get("required") is True or inferred)


def research_status(contract: Contract) -> str:
    gate = research_gate(contract)
    if not research_required(contract):
        return "not_required"
    return str(gate.get("status") or "blocked")


def research_sources(contract: Contract) -> list[dict[str, Any]]:
    gate = research_gate(contract)
    sources = gate.get("sources", [])
    return [dict(x) for x in sources if isinstance(x, dict)] if isinstance(sources, list) else []


def research_report(contract: Contract) -> dict[str, Any]:
    gate = research_gate(contract)
    required = research_required(contract)
    status = research_status(contract)
    provider = str(gate.get("provider") or ("perplex" if required else "none"))
    sources = research_sources(contract)
    return {
        "schema_version": "1.0",
        "required": required,
        "status": status,
        "provider": provider,
        "query": str(gate.get("query") or contract.goal.objective),
        "summary": str(gate.get("summary") or ""),
        "sources": sources,
        "planning_implications": list(gate.get("planning_implications", [])) if isinstance(gate.get("planning_implications", []), list) else [],
        "provider_unavailable_reason": str(gate.get("provider_unavailable_reason") or ""),
        "skipped_reason": str(gate.get("skipped_reason") or ""),
    }


def render_research_markdown(contract: Contract) -> str:
    report = research_report(contract)
    provider_line = f"- Skill `perplex`: {'used' if report['provider'] == 'perplex' and report['status'] == 'satisfied' else 'preferred'}"
    if not report["required"]:
        provider_line = "- Skill `perplex`: skipped-with-reason"
    lines = [
        "# Research gate record",
        "",
        f"Status: {report['status']}",
        f"Required: {'yes' if report['required'] else 'no'}",
        f"Provider: {report['provider']}",
        f"Query: {report['query']}",
        "",
        "## Trigger",
        f"- {'Research required by contract/risk triggers before roadmap compilation.' if report['required'] else 'Research not required for this contract.'}",
        "",
        "## Research tool priority",
        provider_line,
        "- Official docs / Context7: fallback or verification source",
        "- Generic web search: fallback-only",
        "",
        "## Summary",
        f"- {report['summary'] or ('blocked until research evidence is attached' if report['required'] else 'not required')}",
        "",
        "## Fallback justification",
        f"- {report['provider_unavailable_reason'] or ('not needed; Perplex used or research not required' if report['provider'] == 'perplex' or not report['required'] else 'missing')}",
        "",
        "## Sources",
    ]
    if report["sources"]:
        for src in report["sources"]:
            title = src.get("title") or src.get("url") or "source"
            url = src.get("url") or src.get("locator") or ""
            provider = src.get("provider") or report["provider"]
            lines.append(f"- [{provider}] {title} — {url}")
    else:
        lines.append("- none")
    lines += ["", "## Planning implications"]
    if report["planning_implications"]:
        lines += [f"- {x}" for x in report["planning_implications"]]
    else:
        lines.append("- none")
    lines += ["", "## Unverified assumptions"]
    if report["required"] and report["status"] != "satisfied":
        lines.append("- Assumption: research evidence missing")
        lines.append("  - Impact: roadmap cannot be considered strict-ready")
        lines.append("  - Handling: blocked until Perplex/official-docs research is attached")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_research_report(contract: Contract, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(research_report(contract), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _research_diag(code: str, artifact: str, pointer: str, message: str, remediation: str) -> Diagnostic:
    return Diagnostic(code=code, severity="error", blocking_stage="preflight", invariant_id="INV-RESEARCH-001", artifact=artifact, pointer=pointer, message=message, remediation=remediation)


def validate_research_gate(contract: Contract, *, artifact: str = "CONTRACT.json") -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    required = research_required(contract)
    gate = research_gate(contract)
    if not required:
        return diags
    status = research_status(contract)
    provider = str(gate.get("provider") or "")
    sources = research_sources(contract)
    summary = str(gate.get("summary") or "").strip()
    if status != "satisfied":
        diags.append(_research_diag("SGV-RESEARCH-REQUIRED", artifact, "/compatibility/research_gate/status", f"research is required but status is {status}", "Run Perplex/official-docs research and set research_gate.status=satisfied with sources."))
    if provider not in RESEARCH_PROVIDERS:
        diags.append(_research_diag("SGV-RESEARCH-PROVIDER", artifact, "/compatibility/research_gate/provider", "research provider is missing or unsupported", "Use provider perplex, official-docs, context7, web, or manual."))
    if provider != "perplex" and not gate.get("provider_unavailable_reason"):
        diags.append(_research_diag("SGV-RESEARCH-PERPLEX-FIRST", artifact, "/compatibility/research_gate/provider", "Perplex is preferred; non-Perplex provider needs provider_unavailable_reason", "Use Perplex first, or record why it was unavailable."))
    if len(sources) < 1:
        diags.append(_research_diag("SGV-RESEARCH-SOURCES", artifact, "/compatibility/research_gate/sources", "research gate has no sources", "Attach at least one source with title/url/provider."))
    for idx, src in enumerate(sources):
        src_provider = str(src.get("provider") or "")
        if src_provider not in RESEARCH_PROVIDERS:
            diags.append(_research_diag("SGV-RESEARCH-SOURCE-PROVIDER", artifact, f"/compatibility/research_gate/sources/{idx}/provider", "source provider is missing or unsupported", "Set each source provider to perplex, official-docs, context7, web, or manual."))
        if not (src.get("url") or src.get("locator")) or not src.get("title"):
            diags.append(_research_diag("SGV-RESEARCH-SOURCE-SHAPE", artifact, f"/compatibility/research_gate/sources/{idx}", "source must include title and url/locator", "Record source title and URL/locator."))
    if provider == "perplex" and sources and not any(str(src.get("provider") or "") == "perplex" for src in sources):
        diags.append(_research_diag("SGV-RESEARCH-PERPLEX-SOURCE", artifact, "/compatibility/research_gate/sources", "provider is perplex but no source is marked perplex", "Include at least one source with provider=perplex."))
    if len(summary.split()) < 8:
        diags.append(_research_diag("SGV-RESEARCH-SUMMARY", artifact, "/compatibility/research_gate/summary", "research summary is too thin", "Summarize what changed in the plan because of the research."))
    return diags
