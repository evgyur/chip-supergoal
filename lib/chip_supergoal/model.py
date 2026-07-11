from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

_ALLOWED_TOP_LEVEL = {
    "schema_version", "protocol_version", "contract_revision", "profile", "goal",
    "source_set", "decisions", "architecture", "loop", "risks", "approvals",
    "phases", "delivery", "compatibility",
}

@dataclass(frozen=True)
class Goal:
    id: str
    title: str
    objective: str
    request_digest: str
    workspace_root: str
    owner: str
    non_goals: list[str]
    done_condition: str
    created_at: str | None = None

@dataclass(frozen=True)
class Source:
    id: str
    kind: str
    locator: str
    authority: str
    freshness: str
    sensitivity: str = "internal"
    sha256: str | None = None
    used_by: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class Architecture:
    data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Loop:
    data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Risk:
    id: str
    tag: str
    severity: str = "P2"
    mitigation: str = ""

@dataclass(frozen=True)
class Approval:
    id: str
    class_name: str
    scope: str
    required: bool = True

@dataclass(frozen=True)
class Verifier:
    type: str
    command_id: str | None = None
    expected_exit: int | None = None
    expected_assertion: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.type, str) or not self.type:
            raise ValueError("verifier.type must be a nonempty string")
        if self.command_id is not None and (
            not isinstance(self.command_id, str) or not self.command_id
        ):
            raise ValueError("verifier.command_id must be a nonempty string or null")
        if self.expected_exit is not None and type(self.expected_exit) is not int:
            raise ValueError("verifier.expected_exit must be an integer or null")
        if self.command_id is not None and self.expected_exit is None:
            raise ValueError("command verifier requires verifier.expected_exit")
        if self.command_id is None and self.expected_exit is not None:
            raise ValueError("non-command verifier cannot declare verifier.expected_exit")
        if self.expected_assertion is not None and (
            not isinstance(self.expected_assertion, str)
            or not self.expected_assertion
        ):
            raise ValueError(
                "verifier.expected_assertion must be a nonempty string or null"
            )

@dataclass(frozen=True)
class Criterion:
    id: str
    statement: str
    verifier: Verifier
    evidence_tier: str
    blocking: bool = True

@dataclass(frozen=True)
class Command:
    id: str
    command: str
    purpose: str
    safety: str = "local_read_write"
    timeout_seconds: int = 120

@dataclass(frozen=True)
class Deliverable:
    id: str
    kind: str
    path: str
    change_expectation: str
    verification: str

@dataclass(frozen=True)
class RpdPolicy:
    required: bool
    focus: list[str]

@dataclass(frozen=True)
class Phase:
    id: str
    ordinal: int
    name: str
    task: str
    depends_on: list[str]
    work_items: list[dict[str, Any]]
    deliverables: list[Deliverable]
    criteria: list[Criterion]
    commands: list[Command]
    risk_tags: list[str]
    rpd: RpdPolicy

@dataclass(frozen=True)
class Delivery:
    data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Contract:
    schema_version: str
    protocol_version: str
    contract_revision: int
    profile: str
    goal: Goal
    source_set: list[Source]
    decisions: list[dict[str, Any]]
    architecture: Architecture
    loop: Loop
    risks: list[Risk]
    approvals: list[Approval]
    phases: list[Phase]
    delivery: Delivery
    compatibility: dict[str, Any]


def _unknown_keys(data: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise ValueError(f"unknown {label} field(s): {', '.join(extra)}")

def _goal(data: dict[str, Any]) -> Goal:
    allowed = {"id","title","objective","request_digest","workspace_root","owner","non_goals","done_condition","created_at"}
    _unknown_keys(data, allowed, "goal")
    return Goal(**{k: data.get(k) for k in allowed if k in data})

def _source(data: dict[str, Any]) -> Source:
    allowed = {"id","kind","locator","authority","freshness","sensitivity","sha256","used_by"}
    _unknown_keys(data, allowed, "source")
    return Source(**{k: data.get(k) for k in allowed if k in data})

def _risk(data: dict[str, Any]) -> Risk:
    allowed = {"id","tag","severity","mitigation"}
    _unknown_keys(data, allowed, "risk")
    return Risk(**{k: data.get(k) for k in allowed if k in data})

def _approval(data: dict[str, Any]) -> Approval:
    allowed = {"id","class_name","scope","required"}
    _unknown_keys(data, allowed, "approval")
    return Approval(**{k: data.get(k) for k in allowed if k in data})

def _criterion(data: dict[str, Any]) -> Criterion:
    allowed = {"id","statement","verifier","evidence_tier","blocking"}
    _unknown_keys(data, allowed, "criterion")
    verifier_data = dict(data["verifier"])
    _unknown_keys(verifier_data, {"type","command_id","expected_exit","expected_assertion"}, "verifier")
    return Criterion(id=data["id"], statement=data["statement"], verifier=Verifier(**verifier_data), evidence_tier=data["evidence_tier"], blocking=data.get("blocking", True))

def _command(data: dict[str, Any]) -> Command:
    allowed = {"id","command","purpose","safety","timeout_seconds"}
    _unknown_keys(data, allowed, "command")
    return Command(**{k: data.get(k) for k in allowed if k in data})

def _deliverable(data: dict[str, Any]) -> Deliverable:
    allowed = {"id","kind","path","change_expectation","verification"}
    _unknown_keys(data, allowed, "deliverable")
    return Deliverable(**{k: data.get(k) for k in allowed if k in data})

def _phase(data: dict[str, Any]) -> Phase:
    allowed = {"id","ordinal","name","task","depends_on","work_items","deliverables","criteria","commands","risk_tags","rpd"}
    _unknown_keys(data, allowed, "phase")
    rpd = data.get("rpd", {})
    _unknown_keys(rpd, {"required","focus"}, "rpd")
    return Phase(
        id=data["id"], ordinal=data["ordinal"], name=data["name"], task=data["task"],
        depends_on=list(data.get("depends_on", [])), work_items=list(data.get("work_items", [])),
        deliverables=[_deliverable(x) for x in data.get("deliverables", [])],
        criteria=[_criterion(x) for x in data.get("criteria", [])],
        commands=[_command(x) for x in data.get("commands", [])],
        risk_tags=list(data.get("risk_tags", [])), rpd=RpdPolicy(required=bool(rpd.get("required", False)), focus=list(rpd.get("focus", []))),
    )

def contract_from_dict(data: dict[str, Any], *, strict: bool = True) -> Contract:
    if strict:
        _unknown_keys(data, _ALLOWED_TOP_LEVEL, "contract")
    if data.get("schema_version") != "3.0" or data.get("protocol_version") != "3.0":
        raise ValueError("only contract/protocol version 3.0 is supported")
    return Contract(
        schema_version=data["schema_version"], protocol_version=data["protocol_version"],
        contract_revision=int(data["contract_revision"]), profile=data["profile"],
        goal=_goal(dict(data["goal"])), source_set=[_source(dict(x)) for x in data.get("source_set", [])],
        decisions=list(data.get("decisions", [])), architecture=Architecture(dict(data.get("architecture", {}))),
        loop=Loop(dict(data.get("loop", {}))), risks=[_risk(dict(x)) for x in data.get("risks", [])],
        approvals=[_approval(dict(x)) for x in data.get("approvals", [])],
        phases=[_phase(dict(x)) for x in data.get("phases", [])],
        delivery=Delivery(dict(data.get("delivery", {}))), compatibility=dict(data.get("compatibility", {})),
    )

def load_contract(path: str | Path, *, strict: bool = True) -> Contract:
    return contract_from_dict(json.loads(Path(path).read_text(encoding="utf-8")), strict=strict)

def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def to_plain(obj: Any) -> Any:
    if isinstance(obj, Contract):
        return {
            "approvals": [to_plain(x) for x in obj.approvals],
            "architecture": dict(obj.architecture.data),
            "compatibility": dict(obj.compatibility),
            "contract_revision": obj.contract_revision,
            "decisions": list(obj.decisions),
            "delivery": dict(obj.delivery.data),
            "goal": to_plain(obj.goal),
            "loop": dict(obj.loop.data),
            "phases": [to_plain(x) for x in obj.phases],
            "profile": obj.profile,
            "protocol_version": obj.protocol_version,
            "risks": [to_plain(x) for x in obj.risks],
            "schema_version": obj.schema_version,
            "source_set": [to_plain(x) for x in obj.source_set],
        }
    if isinstance(obj, Goal):
        return _drop_none({
            "created_at": obj.created_at,
            "done_condition": obj.done_condition,
            "id": obj.id,
            "non_goals": list(obj.non_goals),
            "objective": obj.objective,
            "owner": obj.owner,
            "request_digest": obj.request_digest,
            "title": obj.title,
            "workspace_root": obj.workspace_root,
        })
    if isinstance(obj, Source):
        return _drop_none({
            "authority": obj.authority,
            "freshness": obj.freshness,
            "id": obj.id,
            "kind": obj.kind,
            "locator": obj.locator,
            "sensitivity": obj.sensitivity,
            "sha256": obj.sha256,
            "used_by": list(obj.used_by),
        })
    if isinstance(obj, Risk):
        return {"id": obj.id, "mitigation": obj.mitigation, "severity": obj.severity, "tag": obj.tag}
    if isinstance(obj, Approval):
        return {"class_name": obj.class_name, "id": obj.id, "required": obj.required, "scope": obj.scope}
    if isinstance(obj, Phase):
        return {
            "commands": [to_plain(x) for x in obj.commands],
            "criteria": [to_plain(x) for x in obj.criteria],
            "deliverables": [to_plain(x) for x in obj.deliverables],
            "depends_on": list(obj.depends_on),
            "id": obj.id,
            "name": obj.name,
            "ordinal": obj.ordinal,
            "risk_tags": list(obj.risk_tags),
            "rpd": to_plain(obj.rpd),
            "task": obj.task,
            "work_items": list(obj.work_items),
        }
    if isinstance(obj, Command):
        return {"command": obj.command, "id": obj.id, "purpose": obj.purpose, "safety": obj.safety, "timeout_seconds": obj.timeout_seconds}
    if isinstance(obj, Criterion):
        return {"blocking": obj.blocking, "evidence_tier": obj.evidence_tier, "id": obj.id, "statement": obj.statement, "verifier": to_plain(obj.verifier)}
    if isinstance(obj, Verifier):
        return _drop_none({"command_id": obj.command_id, "expected_assertion": obj.expected_assertion, "expected_exit": obj.expected_exit, "type": obj.type})
    if isinstance(obj, Deliverable):
        return {"change_expectation": obj.change_expectation, "id": obj.id, "kind": obj.kind, "path": obj.path, "verification": obj.verification}
    if isinstance(obj, RpdPolicy):
        return {"focus": list(obj.focus), "required": obj.required}
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_plain(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if isinstance(obj, list):
        return [to_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    return obj

def canonical_json(contract: Contract) -> str:
    return json.dumps(to_plain(contract), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
