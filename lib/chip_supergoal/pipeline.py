from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Callable

from .diagnostics import Diagnostic, diagnostic_metadata
from .model import Contract, canonical_json, contract_from_dict
from .normalize import semantic_errors
from .policy import load_risk_policy, risk_policy_errors
from .profiles import ProfileError, ResolvedContract, resolve_contract
from .research import validate_research_gate


REPOSITORY_RESOURCE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ContractPipelineResult:
    resolved: ResolvedContract | None
    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        if (self.resolved is None) == (not self.diagnostics):
            raise ValueError(
                "pipeline result must contain either a resolved contract or diagnostics"
            )

    @property
    def resolved_contract(self) -> ResolvedContract | None:
        return self.resolved

    @property
    def ok(self) -> bool:
        return self.resolved is not None


def repository_resource_root() -> Path:
    return REPOSITORY_RESOURCE_ROOT


def _diagnostic(
    code: str,
    *,
    artifact: str,
    pointer: str,
    message: str,
    remediation: str,
    stage: str,
    invariant: str = "INV-VALIDATOR-001",
) -> Diagnostic:
    metadata = diagnostic_metadata(code)
    if (invariant, stage) != (metadata.invariant, metadata.stage):
        raise ValueError(f"diagnostic metadata mismatch for {code}")
    return Diagnostic(
        code=code,
        severity="error",
        blocking_stage=metadata.stage,
        invariant_id=metadata.invariant,
        artifact=artifact,
        pointer=pointer,
        message=message,
        remediation=remediation,
    )


def _malformed_diagnostic(artifact: str) -> Diagnostic:
    return _diagnostic(
        "SGV-CONTRACT-MALFORMED",
        artifact=artifact,
        pointer="/",
        message="contract JSON or v3 model is malformed",
        remediation="Fix the contract JSON shape, version, and required fields.",
        stage="model",
    )


def _profile_diagnostic(artifact: str, exc: Exception) -> Diagnostic:
    text = str(exc)
    if "not found" in text:
        code = "SGV-PROFILE-NOT-FOUND"
        remediation = "Select an available profile or add the missing profile resource."
    elif "inheritance cycle" in text:
        code = "SGV-PROFILE-CYCLE"
        remediation = "Remove the cycle from the profile extends chain."
    elif "maximum profile inheritance depth" in text:
        code = "SGV-PROFILE-DEPTH"
        remediation = "Flatten the profile inheritance chain."
    elif "public-clean redaction" in text:
        code = "SGV-PROFILE-PUBLIC-AMBIGUITY"
        remediation = "Remove private locators from execution-significant fields."
    else:
        code = "SGV-PROFILE-INVALID"
        remediation = "Fix the profile shape, version, and enforcement fields."
    return _diagnostic(
        code,
        artifact=artifact,
        pointer="/profile",
        message="profile resolution failed",
        remediation=remediation,
        stage="profile",
    )


def _semantic_diagnostics(contract: Contract, artifact: str) -> list[Diagnostic]:
    return [
        _diagnostic(
            "SGV-CONTRACT-SEMANTIC",
            artifact=artifact,
            pointer="/phases",
            message=error,
            remediation="Fix the contract graph, identifiers, or phase ordinals.",
            stage="semantic",
        )
        for error in semantic_errors(contract)
    ]


def _risk_code(error: str) -> tuple[str, str, str]:
    if error.startswith("contract risk ") and "unknown risk tag" in error:
        return "SGV-RISK-UNKNOWN", "/risks", "Use a risk tag from the risk policy."
    if "uses unknown risk tag" in error:
        return "SGV-RISK-UNKNOWN", "/phases", "Declare and use a risk tag from the risk policy."
    if " is not declared in contract risks" in error:
        return "SGV-RISK-UNDECLARED", "/risks", "Declare the phase risk in contract risks."
    if " missing RPD focus:" in error:
        return "SGV-RISK-RPD-FOCUS-MISSING", "/phases", "Add every policy-required RPD focus."
    if re.search(r" risk \S+ requires RPD$", error):
        return "SGV-RISK-RPD-MISSING", "/phases", "Enable RPD for the risk-bearing phase."
    if " requires required " in error and " approval scoped to " in error:
        return "SGV-RISK-APPROVAL-MISSING", "/approvals", "Add the required approval with an allowed scope."
    if " requires a nonempty architecture.rollback " in error:
        return "SGV-RISK-ROLLBACK-MISSING", "/architecture/rollback", "Declare a concrete architecture or loop rollback path."
    return "SGV-RISK-POLICY", "/risks", "Bring the contract into compliance with the risk policy."


def _risk_diagnostics(
    contract: Contract, policy: dict, artifact: str
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for error in risk_policy_errors(contract, policy):
        code, pointer, remediation = _risk_code(error)
        diagnostics.append(
            _diagnostic(
                code,
                artifact=artifact,
                pointer=pointer,
                message=error,
                remediation=remediation,
                stage="policy",
                invariant=(
                    "INV-RPD-001"
                    if code
                    in {
                        "SGV-RISK-RPD-FOCUS-MISSING",
                        "SGV-RISK-RPD-MISSING",
                    }
                    else "INV-VALIDATOR-001"
                ),
            )
        )
    return diagnostics


def validate_contract_source(
    source: bytes | Contract,
    *,
    artifact: str = "CONTRACT.json",
    resource_root: str | Path | None = None,
    risk_policy_path: str | Path | None = None,
    resource_reader: Callable[[Path], bytes] | None = None,
) -> ContractPipelineResult:
    root = Path(resource_root) if resource_root is not None else repository_resource_root()
    try:
        source_bytes = (
            canonical_json(source).encode("utf-8")
            if isinstance(source, Contract)
            else bytes(source)
        )
        loaded = json.loads(source_bytes)
        if not isinstance(loaded, dict):
            raise ValueError("contract JSON must be an object")
        contract = contract_from_dict(loaded, strict=True)
    except Exception:
        return ContractPipelineResult(None, (_malformed_diagnostic(artifact),))

    try:
        resolved = resolve_contract(
            contract,
            root / "profiles",
            source_bytes,
            read_file=resource_reader,
        )
    except ProfileError as exc:
        return ContractPipelineResult(None, (_profile_diagnostic(artifact, exc),))
    except (AttributeError, KeyError, TypeError, ValueError):
        return ContractPipelineResult(None, (_malformed_diagnostic(artifact),))

    try:
        diagnostics = _semantic_diagnostics(resolved.contract, artifact)
    except (AttributeError, KeyError, TypeError, ValueError):
        return ContractPipelineResult(None, (_malformed_diagnostic(artifact),))
    policy_path = Path(risk_policy_path) if risk_policy_path is not None else root / "spec/risk-policy.json"
    try:
        policy = (
            json.loads(resource_reader(policy_path))
            if resource_reader is not None
            else load_risk_policy(policy_path)
        )
        if not isinstance(policy, dict) or not isinstance(policy.get("risk_tags"), dict):
            raise ValueError("risk policy must contain a risk_tags object")
    except Exception:
        diagnostics.append(
            _diagnostic(
                "SGV-RISK-POLICY-MALFORMED",
                artifact=str(policy_path),
                pointer="/",
                message="risk policy is malformed",
                remediation="Restore a valid repository risk-policy.json resource.",
                stage="policy",
            )
        )
        return ContractPipelineResult(None, tuple(diagnostics))

    try:
        diagnostics.extend(_risk_diagnostics(resolved.contract, policy, artifact))
    except Exception:
        diagnostics.append(
            _diagnostic(
                "SGV-RISK-POLICY-MALFORMED",
                artifact=str(policy_path),
                pointer="/risk_tags",
                message="risk policy is malformed",
                remediation="Restore valid rule objects in risk-policy.json.",
                stage="policy",
            )
        )
        return ContractPipelineResult(None, tuple(diagnostics))
    diagnostics.extend(validate_research_gate(resolved.contract, artifact=artifact))
    if diagnostics:
        return ContractPipelineResult(None, tuple(diagnostics))
    return ContractPipelineResult(resolved, ())


def contract_diagnostics(
    path: str | Path,
    *,
    resource_root: str | Path | None = None,
    risk_policy_path: str | Path | None = None,
    read_file: Callable[[Path], bytes] | None = None,
) -> ContractPipelineResult:
    source_path = Path(path)
    try:
        source_bytes = read_file(source_path) if read_file is not None else source_path.read_bytes()
    except Exception:
        return ContractPipelineResult(
            None, (_malformed_diagnostic(str(source_path)),)
        )
    return validate_contract_source(
        source_bytes,
        artifact=str(source_path),
        resource_root=resource_root,
        risk_policy_path=risk_policy_path,
        resource_reader=read_file,
    )
