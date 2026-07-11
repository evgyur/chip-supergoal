from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable

SEVERITIES = {"info", "warning", "error", "blocker", "corruption"}
BLOCKING_SEVERITIES = {"error", "blocker", "corruption"}


@dataclass(frozen=True)
class DiagnosticMetadata:
    invariant: str
    stage: str


_PACKAGE_SECURITY_CODES = {
    "SGV-PACKAGE-CASE-COLLISION",
    "SGV-PACKAGE-PATH-ESCAPE",
    "SGV-PACKAGE-SECRET",
    "SGV-PACKAGE-SPECIAL-FILE",
    "SGV-PACKAGE-SYMLINK",
    "SGV-PACKAGE-ZIP-HASH-MISMATCH",
    "SGV-PACKAGE-ZIP-TRAVERSAL",
}


def diagnostic_metadata(code: str) -> DiagnosticMetadata:
    parts = code.split("-")
    family = parts[1] if len(parts) > 1 else ""
    if code == "SGV-CONTRACT-MALFORMED":
        return DiagnosticMetadata("INV-VALIDATOR-001", "model")
    if code == "SGV-CONTRACT-SEMANTIC":
        return DiagnosticMetadata("INV-VALIDATOR-001", "semantic")
    if family == "PROFILE":
        return DiagnosticMetadata("INV-VALIDATOR-001", "profile")
    if family == "RESEARCH":
        return DiagnosticMetadata("INV-RESEARCH-001", "preflight")
    if family == "RISK":
        invariant = "INV-RPD-001" if len(parts) > 2 and parts[2] == "RPD" else "INV-VALIDATOR-001"
        return DiagnosticMetadata(invariant, "policy")
    if family == "STATE":
        invariant = "INV-AUDIT-001" if code == "SGV-STATE-TERMINAL-REOPEN" else "INV-RECOVERY-001"
        return DiagnosticMetadata(invariant, "runtime")
    if code in _PACKAGE_SECURITY_CODES:
        return DiagnosticMetadata("INV-ARCHIVE-001", "archive")
    if code == "SGV-PACKAGE-LAUNCH-MARKER":
        return DiagnosticMetadata("INV-LAUNCH-001", "preflight")
    if family == "PACKAGE":
        return DiagnosticMetadata("INV-VALIDATOR-001", "preflight")
    if code == "SGV-LOOP-LAUNCH-BODY":
        return DiagnosticMetadata("INV-LAUNCH-001", "preflight")
    if family == "PHASE" and len(parts) > 2 and parts[2] == "RPD":
        return DiagnosticMetadata("INV-RPD-001", "preflight")
    return DiagnosticMetadata("INV-VALIDATOR-001", "preflight")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    blocking_stage: str
    invariant_id: str
    artifact: str
    pointer: str
    message: str
    remediation: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unsupported severity: {self.severity}")
        if not self.code.startswith("SGV-"):
            raise ValueError(f"diagnostic code must start with SGV-: {self.code}")
        if not self.invariant_id.startswith("INV-"):
            raise ValueError(f"invariant_id must start with INV-: {self.invariant_id}")
        for field_name in ("blocking_stage", "artifact", "pointer", "message", "remediation"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")

    @property
    def blocking(self) -> bool:
        return self.severity in BLOCKING_SEVERITIES

    def to_dict(self) -> dict[str, Any]:
        data = {
            "code": self.code,
            "severity": self.severity,
            "blocking_stage": self.blocking_stage,
            "invariant_id": self.invariant_id,
            "artifact": self.artifact,
            "pointer": self.pointer,
            "message": self.message,
            "remediation": self.remediation,
        }
        if self.details:
            data["details"] = self.details
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def render_human(self) -> str:
        return (
            f"{self.code} [{self.severity}] {self.artifact}{self.pointer}: {self.message}\n"
            f"invariant: {self.invariant_id}; stage: {self.blocking_stage}; fix: {self.remediation}"
        )


def diagnostics_to_json(diagnostics: Iterable[Diagnostic]) -> str:
    return json.dumps([d.to_dict() for d in diagnostics], ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def has_blocking(diagnostics: Iterable[Diagnostic]) -> bool:
    return any(d.blocking for d in diagnostics)


class ContractValidationError(ValueError):
    def __init__(self, diagnostics: Iterable[Diagnostic]):
        self.diagnostics = tuple(diagnostics)
        if not self.diagnostics:
            raise ValueError("ContractValidationError requires diagnostics")
        super().__init__("contract validation failed")
