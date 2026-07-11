from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable

SEVERITIES = {"info", "warning", "error", "blocker", "corruption"}
BLOCKING_SEVERITIES = {"error", "blocker", "corruption"}


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
