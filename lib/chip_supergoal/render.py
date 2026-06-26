from __future__ import annotations

from .model import Contract
from .research import research_report, research_required


def render_thinking(contract: Contract) -> str:
    return f"""# THINKING — {contract.goal.title}

## Goal
{contract.goal.objective}

## Non-goals
{chr(10).join(f'- {x}' for x in contract.goal.non_goals) or '- none'}

## Constraints and permissions
- Profile: `{contract.profile}`
- Workspace root: `{contract.goal.workspace_root}`
- Executor: standard Hermes `/goal`; no production runner.

## Risks top 3
{chr(10).join(f'- {r.id}: {r.tag} — {r.mitigation or r.severity}' for r in contract.risks[:3]) or '- none'}

## Dependencies/order
- Phase order is derived from `CONTRACT.json` phase ordinals and dependencies.

## Assumptions
- Contract source is canonical; Markdown files are generated views.

## Memory hits applied
- none

## Tools/skills used
- chip-supergoal compiler

## Best practices applied
- deterministic rendering
- semantic validation
"""


def render_loop_design(contract: Contract) -> str:
    return f"""# LOOP_DESIGN.md

## Goal
{contract.goal.objective}

## Context sources
- CONTRACT.json is the canonical source of truth.
- Workspace root: `{contract.goal.workspace_root}`.

## Host model
- Host: standard Hermes `/goal` executor running generated PROTOCOL.md.

## Reviewer / judge model
- Reviewer/judge: embedded RPD/Senior gate with pass/fail mutation requests.

## Verification gates
- Programmatic gate: python3 -m unittest discover -s tests.
- Package gate: python3 scripts/sgctl.py validate-package .supergoal --strict.

## State checkpoints
- STATE.md is generated at compile time and becomes a runtime checkpoint.
- Future v3 STATE.json supersedes STATE.md when present.

## Stop conditions
- Retry at most 3 times per failed gate.
- Stop only for real blockers or after 3 audit rounds.

## Budget
- phases: {len(contract.phases)}
- max iterations: {max(3, len(contract.phases) + 2)}
- audit rounds: 3

## Boundaries
- secrets, credentials, private data, public egress, payment, DNS, and production changes follow profile policy.
- No custom production runner.

## Failure recovery
- On validation failure: patch, retry, or handoff with blocker.
- On state/path drift: recover from disk-bound goal identity.

## Human approvals
- Required only for money, DNS, secrets, grants, destructive production, or public/mass sends.

## ASCII preview
```text
CONTRACT.json -> COMPILE -> /goal -> PHASES -> FINAL AUDIT -> DONE
```
"""


def render_roadmap(contract: Contract) -> str:
    research = research_report(contract)
    research_line = f"{research['status']} via {research['provider']} — {research['summary'] or 'no summary'}" if research_required(contract) or contract.compatibility.get("research_gate") else "not required"
    lines = [f"# ROADMAP — {contract.goal.title}", "", "## Decision package", f"- Goal ID: `{contract.goal.id}`", f"- Done condition: {contract.goal.done_condition}", f"- Research evidence: {research_line}", "", "## Context summary", f"- Profile: `{contract.profile}`", f"- Contract revision: `{contract.contract_revision}`", "", "## Assumptions", "- Markdown is generated from CONTRACT.json.", "", "## Risk top 3"]
    lines += [f"- {r.id}: `{r.tag}` — {r.mitigation or r.severity}" for r in contract.risks[:3]] or ["- none"]
    lines += ["", "## Phase map"]
    for p in contract.phases:
        deps = ", ".join(p.depends_on) or "none"
        lines.append(f"- {p.id}: {p.name} — depends on {deps}")
    lines += ["", "## Phases"]
    for p in contract.phases:
        lines += ["", f"### {p.id} — {p.name}", f"Task: {p.task}", "Acceptance criteria:"]
        lines += [f"- {c.id}: {c.statement}" for c in p.criteria]
        lines += ["Mandatory commands:"]
        lines += [f"- {c.id}: `{c.command}`" for c in p.commands]
        lines += [f"Evidence: {', '.join(sorted({c.evidence_tier for c in p.criteria})) or 'direct_artifact'}"]
    return "\n".join(lines) + "\n"


def render_state(contract: Contract) -> str:
    return f"""# STATE — {contract.goal.title}

Goal identity: `{contract.goal.id}`
Current phase: 1
Total phases: {len(contract.phases)}
Baseline ref: compile-time baseline not captured
Status snapshot: COMPILED
Delivery state: not requested

## Event ledger
- EVT-000001 compiled from CONTRACT.json revision {contract.contract_revision}.
"""


def render_launch_goal(contract: Contract) -> str:
    marker = "SUPERGOAL" + "_GOAL_BODY:"
    package_root = "this generated SuperGoal package root (the directory containing LAUNCH_GOAL.md)"
    approval_scopes = "; ".join(
        f"{a.class_name}: {a.scope.rstrip('.')}" for a in contract.approvals if a.required
    )
    approval_clause = (
        f" Contract-required approval scopes: {approval_scopes}."
        if approval_scopes
        else ""
    )
    body = (
        f"{marker} From the project root `{contract.goal.workspace_root}`, execute {package_root}. "
        "Read `PROTOCOL.md`, `THINKING.md`, `RESEARCH.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `STATE.md`, and `phases/phase-*.md` from that package root. "
        "Before phase 1, run available package preflight from the package root: `python scripts/sgctl.py validate-package .` when package-local `scripts/sgctl.py` exists, plus `scripts/validate-loop-design.sh` and `scripts/validate-phase.sh` when present. Fix preflight failures before implementation unless the user explicitly bypassed them. "
        f"Goal ID `{contract.goal.id}`. "
        "Start from STATE.md current phase, continue through numbered phases, run the final audit, and finish only after "
        "AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE appear in the same final response with Goal complete: yes. "
        "If review-file delivery is required and no valid receipt exists, print `SUPERGOAL_REVIEW_FILES_BLOCKED` with the missing receipt/artifact and stop. "
        "Do not mutate live production, DNS, secrets, grants, payment rails, destructive migrations, or public/mass-send channels without a bounded approval manifest naming the exact target, action, verification, and rollback. "
        f"{approval_clause} "
        "Preserve the planner/compiler boundary: do not create a production runner or nested /goal; standard Hermes /goal remains the executor. "
        "Dispatch status: continue until final audit passes or a real safety/approval blocker is printed."
    )
    return f"# LAUNCH_GOAL — {contract.goal.title}\n\n{body}\n"


def render_phase(contract: Contract, phase_index: int) -> str:
    p = contract.phases[phase_index]
    commands = "; ".join(c.command for c in p.commands)
    evidence = ", ".join(sorted({c.evidence_tier for c in p.criteria})) or "direct_artifact"
    deps = ", ".join(p.depends_on) or "none"
    focus = p.rpd.focus[0] if p.rpd.focus else "none"
    lines = [f"# {p.id} — {p.name}", "", "SUPERGOAL_PHASE_START", f"Phase: {p.ordinal} of {len(contract.phases)} — {p.name}", f"Task: {p.task}", f"Mandatory commands: {commands}", f"Acceptance criteria: {len(p.criteria)}", f"Evidence required: {evidence}", f"Depends on phases: {deps}", f"RPD required: {'yes' if p.rpd.required else 'no'}", f"RPD focus: {focus}", "", "## Work"]
    lines += [f"- {w.get('text', w)}" for w in p.work_items] or ["- Execute the phase task."]
    lines += ["", "## Acceptance criteria"]
    lines += [f"- {c.statement}" for c in p.criteria]
    lines += ["", "## Mandatory commands"]
    lines += [f"- {c.command}" for c in p.commands]
    lines += ["", "## Evidence required"]
    lines += [f"- {evidence} evidence for {c.id}" for c in p.criteria]
    return "\n".join(lines) + "\n"
