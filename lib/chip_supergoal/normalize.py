from __future__ import annotations

import re
from .model import Contract
from .graph import phase_graph_errors
from .policy import risk_policy_errors

ID_PATTERNS = {
    "goal": re.compile(r"^sg-[0-9]{8}-[a-z0-9-]+$"),
    "phase": re.compile(r"^P[0-9]{2}$"),
    "criterion": re.compile(r"^P[0-9]{2}-C[0-9]{2}$"),
    "command": re.compile(r"^P[0-9]{2}-CMD[0-9]{2}$"),
}

_OUTCOME_FIELDS = {"outcome", "evidence", "threshold", "in_scope", "out_of_scope", "stop_and_ask"}
_EXECUTION_PROFILE_FIELDS = {
    "owner", "planner_effort", "integrator_effort", "engineering_mode", "worker_model",
    "worker_mode", "max_parallel_scouts", "max_review_rounds", "phase_routes",
}


def loop_contract_errors(contract: Contract) -> list[str]:
    """Validate the measurable outcome and bounded Shawl/Luna route."""
    loop = contract.loop.data
    errors: list[str] = []

    outcome = loop.get("outcome_definition")
    if not isinstance(outcome, dict):
        errors.append("loop.outcome_definition must be an object")
    else:
        extra = sorted(set(outcome) - _OUTCOME_FIELDS)
        if extra:
            errors.append(f"loop.outcome_definition has unknown fields: {', '.join(extra)}")
        for key in ["outcome", "threshold", "stop_and_ask"]:
            if not isinstance(outcome.get(key), str) or not outcome[key].strip():
                errors.append(f"loop.outcome_definition.{key} must be a non-empty string")
        for key in ["evidence", "in_scope", "out_of_scope"]:
            value = outcome.get(key)
            if not isinstance(value, list) or not value or not all(isinstance(x, str) and x.strip() for x in value):
                errors.append(f"loop.outcome_definition.{key} must be a non-empty string array")

    profile = loop.get("execution_profile")
    if not isinstance(profile, dict):
        errors.append("loop.execution_profile must be an object")
        return errors
    extra = sorted(set(profile) - _EXECUTION_PROFILE_FIELDS)
    if extra:
        errors.append(f"loop.execution_profile has unknown fields: {', '.join(extra)}")
    expected = {
        "owner": "Sol", "engineering_mode": "shawl", "worker_model": "gpt-5.6-luna", "worker_mode": "scout",
    }
    for key, value in expected.items():
        if profile.get(key) != value:
            errors.append(f"loop.execution_profile.{key} must equal {value!r}")
    for key in ["planner_effort", "integrator_effort"]:
        if profile.get(key) not in {"high", "max"}:
            errors.append(f"loop.execution_profile.{key} must be high or max")
    scouts = profile.get("max_parallel_scouts")
    rounds = profile.get("max_review_rounds")
    if not isinstance(scouts, int) or isinstance(scouts, bool) or not 1 <= scouts <= 3:
        errors.append("loop.execution_profile.max_parallel_scouts must be an integer from 1 to 3")
    if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= 3:
        errors.append("loop.execution_profile.max_review_rounds must be an integer from 1 to 3")
    routes = profile.get("phase_routes")
    phase_ids = {phase.id for phase in contract.phases}
    if not isinstance(routes, dict):
        errors.append("loop.execution_profile.phase_routes must be an object")
    else:
        if set(routes) != phase_ids:
            errors.append("loop.execution_profile.phase_routes must cover every phase exactly")
        for phase_id, route in routes.items():
            if route not in {"direct", "shawl"}:
                errors.append(f"loop.execution_profile.phase_routes.{phase_id} must be direct or shawl")
        for phase in contract.phases:
            if (phase.rpd.required or phase.risk_tags) and routes.get(phase.id) != "shawl":
                errors.append(f"{phase.id} is risky/RPD-required and must route through shawl")
    return errors


def stable_id_errors(contract: Contract) -> list[str]:
    errors: list[str] = []
    if not ID_PATTERNS["goal"].match(contract.goal.id):
        errors.append(f"invalid goal id: {contract.goal.id}")
    seen: set[str] = set()
    for phase in contract.phases:
        if not ID_PATTERNS["phase"].match(phase.id):
            errors.append(f"invalid phase id: {phase.id}")
        for item_id in [phase.id, *(c.id for c in phase.criteria), *(c.id for c in phase.commands), *(d.id for d in phase.deliverables)]:
            if item_id in seen:
                errors.append(f"duplicate id: {item_id}")
            seen.add(item_id)
        command_ids = {c.id for c in phase.commands}
        for criterion in phase.criteria:
            if not ID_PATTERNS["criterion"].match(criterion.id):
                errors.append(f"invalid criterion id: {criterion.id}")
            if criterion.verifier.command_id and criterion.verifier.command_id not in command_ids:
                errors.append(f"{criterion.id} references missing command {criterion.verifier.command_id}")
        for command in phase.commands:
            if not ID_PATTERNS["command"].match(command.id):
                errors.append(f"invalid command id: {command.id}")
            if not command.command or command.command.upper() == "TBD":
                errors.append(f"{command.id} has placeholder command")
            if command.timeout_seconds <= 0:
                errors.append(f"{command.id} timeout must be positive")
    return errors

def semantic_errors(contract: Contract, risk_policy: dict | None = None) -> list[str]:
    errors = []
    errors.extend(stable_id_errors(contract))
    errors.extend(phase_graph_errors(contract))
    errors.extend(loop_contract_errors(contract))
    if risk_policy is not None:
        errors.extend(risk_policy_errors(contract, risk_policy))
    return errors
