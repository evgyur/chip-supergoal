from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Iterable

SEVERITIES = {"info", "warning", "error", "blocker", "corruption"}
BLOCKING_SEVERITIES = {"error", "blocker", "corruption"}


@dataclass(frozen=True)
class DiagnosticMetadata:
    invariant: str
    stage: str


_CATALOG_VERSION = "1.0"
_EXPECTED_CODE_COUNT = 76
_CATALOG_PATH = Path(__file__).resolve().parents[2] / "spec/diagnostic-catalog.json"
_TOP_LEVEL_KEYS = {"catalog_version", "expected_code_count", "diagnostics"}
_ENTRY_KEYS = {"code", "invariant", "stage", "remediation_class"}
_CODE_PATTERN = re.compile(r"^SGV-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
_INVARIANT_PATTERN = re.compile(r"^INV-[A-Z0-9]+-[0-9]{3}$")


def load_diagnostic_catalog(path: str | Path) -> dict[str, DiagnosticMetadata]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("diagnostic catalog cannot be loaded") from exc
    if not isinstance(raw, dict) or set(raw) != _TOP_LEVEL_KEYS:
        raise ValueError("diagnostic catalog has unsupported top-level shape")
    if raw.get("catalog_version") != _CATALOG_VERSION:
        raise ValueError("diagnostic catalog version is unsupported")
    if type(raw.get("expected_code_count")) is not int or raw["expected_code_count"] != _EXPECTED_CODE_COUNT:
        raise ValueError("diagnostic catalog expected code count is invalid")
    entries = raw.get("diagnostics")
    if not isinstance(entries, list) or len(entries) != _EXPECTED_CODE_COUNT:
        raise ValueError("diagnostic catalog entry count is invalid")

    metadata: dict[str, DiagnosticMetadata] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise ValueError("diagnostic catalog entry has unsupported shape")
        code = entry.get("code")
        invariant = entry.get("invariant")
        stage = entry.get("stage")
        remediation_class = entry.get("remediation_class")
        if not isinstance(code, str) or not _CODE_PATTERN.fullmatch(code):
            raise ValueError("diagnostic catalog code is invalid")
        if not isinstance(invariant, str) or not _INVARIANT_PATTERN.fullmatch(invariant):
            raise ValueError("diagnostic catalog invariant is invalid")
        if not isinstance(stage, str) or not stage:
            raise ValueError("diagnostic catalog stage is invalid")
        if not isinstance(remediation_class, str) or not remediation_class:
            raise ValueError("diagnostic catalog remediation class is invalid")
        if code in metadata:
            raise ValueError("diagnostic catalog contains duplicate codes")
        metadata[code] = DiagnosticMetadata(invariant, stage)
    return metadata


@lru_cache(maxsize=1)
def _runtime_diagnostic_catalog() -> dict[str, DiagnosticMetadata]:
    return load_diagnostic_catalog(_CATALOG_PATH)


def diagnostic_metadata(code: str) -> DiagnosticMetadata:
    try:
        return _runtime_diagnostic_catalog()[code]
    except KeyError:
        raise ValueError(f"unknown diagnostic code: {code}") from None


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
        metadata = diagnostic_metadata(self.code)
        if (self.invariant_id, self.blocking_stage) != (metadata.invariant, metadata.stage):
            raise ValueError(f"diagnostic metadata mismatch for {self.code}")
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
