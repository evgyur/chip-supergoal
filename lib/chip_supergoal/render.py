from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from typing import Any

from .model import Command, Contract, Phase, to_plain
from .research import research_gate, research_report, research_required


NOT_DECLARED = "not declared by CONTRACT.json"


def phase_entries_in_ordinal_order(contract: Contract) -> list[tuple[int, Phase]]:
    return sorted(
        enumerate(contract.phases),
        key=lambda item: (item[1].ordinal, item[1].id),
    )


def _view_plain(value: Any) -> Any:
    if isinstance(value, Command):
        return to_plain(value)
    if is_dataclass(value):
        return {field.name: _view_plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {key: _view_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_view_plain(item) for item in value]
    return value


def _compact_json(value: Any) -> str:
    """Return the lossless, deterministic representation used in list records."""
    return json.dumps(
        _view_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _json_block(value: Any) -> str:
    """Return a readable, lossless JSON block with deterministic key ordering."""
    return (
        "```json\n"
        + json.dumps(_view_plain(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```"
    )


def _declared_block(value: Any) -> str:
    if value is None or value == [] or value == {}:
        return NOT_DECLARED
    return _json_block(value)


def _json_bullets(items: list[Any]) -> list[str]:
    return [f"- {_compact_json(item)}" for item in items] or [f"- {NOT_DECLARED}"]


def _scalar(value: Any) -> str:
    if value is None or value == "":
        return NOT_DECLARED
    if isinstance(value, str):
        return value
    return _compact_json(value)


def render_thinking(contract: Contract) -> str:
    identity = {
        "contract_revision": contract.contract_revision,
        "profile": contract.profile,
        "protocol_version": contract.protocol_version,
        "schema_version": contract.schema_version,
    }
    return f"""# THINKING — {contract.goal.title}

## Goal
{contract.goal.objective}

## Goal contract
{_json_block(contract.goal)}

## Non-goals
{_declared_block(contract.goal.non_goals)}

## Contract identity
{_json_block(identity)}

## Source set
{_declared_block(contract.source_set)}

## Decisions
{_declared_block(contract.decisions)}

## Architecture contract
{_declared_block(contract.architecture.data)}

## Compatibility contract
{_declared_block(contract.compatibility)}

## Risk contract
{_declared_block(contract.risks)}
"""


def render_loop_design(contract: Contract) -> str:
    loop = contract.loop.data
    host = loop.get("host_model")
    reviewer = loop.get("reviewer")
    judge = loop.get("judge")
    verification = loop.get("verification_gates")
    checkpoints = loop.get("state_checkpoints")
    stops = loop.get("stop_conditions")
    boundaries = loop.get("boundaries")
    recovery = loop.get("failure_recovery")

    return f"""# LOOP_DESIGN.md

## Goal
{contract.goal.objective}

## Context sources
- Canonical source records follow; when empty they are {NOT_DECLARED}.
{_declared_block(contract.source_set)}

## Host model
- Contract host model: {_scalar(host)}.
- Protocol invariant: standard Hermes `/goal` interprets this package without adding undeclared host capabilities.

## Reviewer / judge model
- Contract reviewer: {_scalar(reviewer)}.
- Contract judge: {_scalar(judge)}.

## Verification gates
- Contract verification gates: {_scalar(verification)}.
- Compiler invariant: generated phase views expose every declared verifier and command record.

## State checkpoints
- Contract state checkpoints: {_scalar(checkpoints)}.
- Runtime invariant: `runtime/STATE.json` is the authoritative runtime state and `STATE.md` is its projection.

## Stop conditions
- Contract retry/iteration stop conditions: {_scalar(stops)}.

## Budget
- Compiler fact: this contract contains {len(contract.phases)} phase(s).
- Contract maximum iterations: {_scalar(loop.get('max_iterations'))}.
- Contract audit rounds: {_scalar(loop.get('audit_rounds'))}.
- Other budget fields remain in the complete loop contract below.

## Boundaries
- Contract secret, private, egress, production, and other boundaries: {_scalar(boundaries)}.

## Failure recovery
- Contract retry, rollback, recovery, or handoff rules: {_scalar(recovery)}.

## Human approvals
{_declared_block(contract.approvals)}

## Declared loop contract
{_declared_block(loop)}

## ASCII preview
```text
CONTRACT.json -> generated executor views -> Python package validation
runtime/STATE.json -> STATE.md projection
phase contracts -> declared verifiers -> final audit
```
"""


def _research_emitted(contract: Contract) -> bool:
    return bool(research_required(contract) or research_gate(contract))


def render_roadmap(contract: Contract) -> str:
    lines = [
        f"# ROADMAP — {contract.goal.title}",
        "",
        "## Decision package",
        f"- Goal ID: `{contract.goal.id}`",
        f"- Done condition: {contract.goal.done_condition}",
        f"- Research artifact: {'RESEARCH.md emitted' if _research_emitted(contract) else NOT_DECLARED}",
        "",
        "## Goal contract",
        _json_block(contract.goal),
        "",
        "## Source set",
        _declared_block(contract.source_set),
        "",
        "## Decisions",
        _declared_block(contract.decisions),
        "",
        "## Architecture contract",
        _declared_block(contract.architecture.data),
        "",
        "## Loop contract",
        _declared_block(contract.loop.data),
        "",
        "## Compatibility contract",
        _declared_block(contract.compatibility),
        "",
        "## Research record",
        _json_block(research_report(contract)) if _research_emitted(contract) else NOT_DECLARED,
        "",
        "## Risks",
        _declared_block(contract.risks),
        "",
        "## Approval contract",
        _declared_block(contract.approvals),
        "",
        "## Resolved delivery contract",
        _declared_block(contract.delivery.data),
        "",
        "## Phase map",
    ]
    ordered_phases = [phase for _, phase in phase_entries_in_ordinal_order(contract)]
    for phase in ordered_phases:
        dependencies = ", ".join(phase.depends_on) or "none"
        lines.append(f"- {phase.id}: {phase.name} — depends on {dependencies}")

    lines += ["", "## Phases"]
    for phase in ordered_phases:
        lines += [
            "",
            f"### {phase.id} — {phase.name}",
            f"Task: {phase.task}",
            f"Dependencies: {_compact_json(phase.depends_on)}",
            f"Risk tags: {_compact_json(phase.risk_tags)}",
            f"RPD policy: {_compact_json(phase.rpd)}",
            "",
            "**Work items:**",
            *_json_bullets(phase.work_items),
            "",
            "**Deliverables:**",
            *_json_bullets(phase.deliverables),
            "",
            "**Acceptance criteria:**",
            *_json_bullets(phase.criteria),
            "",
            "**Mandatory commands:**",
            *_json_bullets(phase.commands),
            "",
            "**Complete phase contract:**",
            _json_block(phase),
        ]

    review = contract.compatibility.get("rpd_plan_review")
    if review is not None:
        lines += ["", "## RPD_PLAN_REVIEW", _declared_block(review)]
    return "\n".join(lines) + "\n"


def render_state(contract: Contract) -> str:
    """Compatibility renderer; live packages use state.render_state_md instead."""
    return f"""# STATE projection guidance — {contract.goal.title}

`runtime/STATE.json` is the authority for runtime state. `STATE.md` is a generated
projection of that JSON state and is not a second control plane. This compile-time
compatibility renderer does not declare a baseline, delivery status, phase status,
or runtime event that is absent from the authoritative runtime record.
"""


def render_launch_goal(contract: Contract) -> str:
    marker = "SUPERGOAL" + "_GOAL_BODY:"
    context_files = [
        "CONTRACT.json",
        "THINKING.md",
        "LOOP_DESIGN.md",
        "ROADMAP.md",
        "runtime/STATE.json",
        "STATE.md",
        "phases/phase-*.md",
        "PROTOCOL.md",
    ]
    if _research_emitted(contract):
        context_files.insert(2, "RESEARCH.md")
    context_text = ", ".join(f"`{path}`" for path in context_files)
    preflight_commands = [
        "python scripts/sgctl.py validate-package . --strict",
        "python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated",
        *[
            f"python scripts/sgctl.py validate-phase-markdown phases/phase-{phase.ordinal:02d}.md"
            for _, phase in phase_entries_in_ordinal_order(contract)
        ],
    ]
    if _research_emitted(contract):
        preflight_commands.append(
            "python scripts/sgctl.py research-gate CONTRACT.json --format json"
        )
    delivery = _declared_block(contract.delivery.data)
    approvals = _declared_block(contract.approvals)
    body = (
        f"{marker} Resolve the package root at execution time as the parent directory of the "
        "LAUNCH_GOAL.md being executed. From that package root, read the declared context files "
        f"({context_text}). Run every Python command in the Preflight section from the package root. "
        f"Execute goal `{contract.goal.id}` from the phase selected by authoritative `runtime/STATE.json`; "
        "treat `STATE.md` only as its projection. Enforce exactly the resolved Delivery boundary and "
        "Approval boundary printed in this file; do not add undeclared operational defaults. Use standard "
        "Hermes `/goal` continuation only and do not create a custom runner or nested `/goal`. Dispatch status: "
        "continue until final audit passes, a contract-declared boundary blocks progress, or the host forces a "
        "yield. After runtime authority permits completion, host compatibility requires `AUDIT_COMPLETE`, "
        "`SUPERGOAL_RUN_COMPLETE`, and `Goal complete: yes` together in the final response. Those marker "
        "strings document compatibility and do not create runtime authority."
    )
    lines = [
        f"# LAUNCH_GOAL — {contract.goal.title}",
        "",
        "## Relocatable package locator",
        "- Package root: the parent directory of the LAUNCH_GOAL.md being executed.",
        "- Resolve the root at execution time; no compile-time output path is authoritative.",
        "",
        "## Launch context",
        *[f"- `{path}`" for path in context_files],
        "",
        "## Preflight",
        "- Run each command from the package root:",
        *[f"  - `{command}`" for command in preflight_commands],
        "",
        "## Delivery boundary",
        delivery,
        "",
        "## Approval boundary",
        approvals,
        "",
        body,
    ]
    return "\n".join(lines) + "\n"


def render_phase(contract: Contract, phase_index: int) -> str:
    phase = contract.phases[phase_index]
    command_ids = ", ".join(command.id for command in phase.commands) or NOT_DECLARED
    evidence = ", ".join(
        dict.fromkeys(criterion.evidence_tier for criterion in phase.criteria)
    ) or NOT_DECLARED
    dependencies = ", ".join(phase.depends_on) or "none"
    focuses = ", ".join(phase.rpd.focus) or "none"
    lines = [
        f"# {phase.id} — {phase.name}",
        "",
        "SUPERGOAL_PHASE_START",
        f"Phase: {phase.ordinal} of {len(contract.phases)} — {phase.name}",
        f"Task: {phase.task}",
        f"Mandatory commands: {command_ids}",
        f"Acceptance criteria: {len(phase.criteria)}",
        f"Evidence required: {evidence}",
        f"Depends on phases: {dependencies}",
        f"RPD required: {'yes' if phase.rpd.required else 'no'}",
        f"RPD focus: {focuses}",
        "",
        "## Work",
        *_json_bullets(phase.work_items),
        "",
        "## Deliverables",
        *_json_bullets(phase.deliverables),
        "",
        "## Acceptance criteria",
        *(_json_bullets(phase.criteria) if phase.criteria else [NOT_DECLARED]),
        "",
        "## Mandatory commands",
        *_json_bullets(phase.commands),
        "",
        "## Evidence required",
        *(_json_bullets(phase.criteria) if phase.criteria else [NOT_DECLARED]),
        "",
        "## Risk tags",
        _declared_block(phase.risk_tags),
        "",
        "## RPD policy",
        _json_block(phase.rpd),
        "",
        "## Complete phase contract",
        _json_block(phase),
    ]
    return "\n".join(lines) + "\n"
