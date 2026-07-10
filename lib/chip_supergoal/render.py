from __future__ import annotations

from .model import Contract
from .research import research_report, research_required


def _list_lines(items, *, fallback="none") -> str:
    values = [str(x).strip() for x in items if str(x).strip()]
    return "\n".join(f"- {x}" for x in values) if values else f"- {fallback}"


def render_thinking(contract: Contract) -> str:
    architecture = contract.architecture.data
    assumptions = architecture.get("assumptions", [])
    memory_hits = architecture.get("memory_hits", [])
    tools = architecture.get("tools_skills_used", ["chip-supergoal compiler"])
    best_practices = architecture.get("best_practices", [])
    if not best_practices:
        best_practices = [
            "deterministic rendering and semantic package validation",
            "historical eval before recurring rollout",
            "reversible production activation with one bounded approval",
        ]
    source_lines = [f"{s.id}: {s.authority} — {s.locator}" for s in contract.source_set]
    decision_lines = [str(x.get("summary") or x.get("id") or x) for x in contract.decisions]
    return f"""# THINKING — {contract.goal.title}

## Goal
{contract.goal.objective}

## Non-goals
{_list_lines(contract.goal.non_goals)}

## Constraints and permissions
- Profile: `{contract.profile}`
- Workspace root: `{contract.goal.workspace_root}`
- Executor: standard Hermes `/goal`; no nested goal or custom production runner.
- Data policy: {architecture.get('data_policy', 'private data and secrets stay out of generated/tracked artifacts')}

## Risks top 3
{_list_lines([f'{r.id}: {r.tag} — {r.mitigation or r.severity}' for r in contract.risks[:3]])}

## Dependencies/order
- Phase order is derived from `CONTRACT.json` ordinals and dependencies.
{_list_lines(decision_lines, fallback='no extra architecture decisions')}

## Assumptions
{_list_lines(assumptions, fallback='Contract source is canonical; runtime claims must be reverified during execution.')}

## Memory hits applied
{_list_lines(memory_hits, fallback='none')}

## Context evidence
{_list_lines(source_lines)}

## Tools/skills used
{_list_lines(tools)}

## Best practices applied
{_list_lines(best_practices)}
"""


def render_loop_design(contract: Contract) -> str:
    loop = contract.loop.data
    architecture = contract.architecture.data
    sources = [f"{s.id}: {s.authority}/{s.freshness} — {s.locator}" for s in contract.source_set]
    stop_conditions = loop.get("stop_conditions", [])
    approvals = [f"{a.id}: {a.scope}" for a in contract.approvals if a.required]
    verification = loop.get("verification_gates", [
        "phase mandatory commands and acceptance criteria",
        str(loop.get("judge") or "programmatic tests plus evidence-backed final audit"),
        "strict package validation and RPD/Senior mutation gates",
    ])
    checkpoints = loop.get("state_checkpoints", [
        str(loop.get("state") or "STATE.md plus phase reports"),
        "write phase evidence and event ledger before advancing",
        "continue through numbered phases until final audit or a real blocker",
    ])
    boundaries = loop.get("boundaries", [
        str(architecture.get("data_policy") or "secrets and raw private data never leave the approved local boundary"),
        "no cron, Telegram, gateway, provider, credential, grant, payment, or production-data mutation before its declared approval gate",
        "no custom runner, daemon, database, web UI, or nested /goal",
    ])
    recovery = loop.get("failure_recovery", [
        "On gate failure, inspect direct evidence, patch the smallest cause, and retry at most the declared limit.",
        "After two no-progress retries or any privacy/production-boundary breach, stop with FAILURE_HANDOFF and one concrete blocker.",
        "On rollout failure, execute the manifest rollback and verify the previous cron state before continuing.",
    ])
    return f"""# LOOP_DESIGN.md

## Goal
{contract.goal.objective}

## Context sources
- `CONTRACT.json` is the canonical planning contract.
{_list_lines(sources)}

## Host model
- Host: {loop.get('host_model', 'standard Hermes /goal executor')}.
- Service tier: normal; fast mode is not enabled by this package.

## Reviewer / judge model
- Reviewer: {loop.get('reviewer', 'embedded RPD/Senior gate; findings must mutate artifacts or become checked-holds')}.
- Judge: {loop.get('judge', 'programmatic pass/fail checks against phase acceptance criteria')}.

## Verification gates
{_list_lines(verification)}

## State checkpoints
{_list_lines(checkpoints)}

## Stop conditions
{_list_lines(stop_conditions, fallback='real blocker, exhausted retry budget, or verified completion')}

## Budget
- phases: {len(contract.phases)}
- phase repair rounds: {loop.get('max_iterations', 3)} maximum per failing phase
- audit rounds: {loop.get('audit_rounds', 3)}
- architecture budget: {loop.get('budget', 'no unbounded new orchestration layer')}

## Boundaries
{_list_lines(boundaries)}

## Failure recovery
{_list_lines(recovery)}

## Human approvals
{_list_lines(approvals, fallback='none beyond real sensitive gates declared in the contract')}

## ASCII preview
```text
INTAKE / RECON
  ↓
THINKING + RESEARCH
  ↓
LOOP_DESIGN.md
  ↓ gate: loop health + RPD_PLAN_REVIEW
ROADMAP + PHASE SPECS
  ↓ gate: strict validation + preflight
/goal EXECUTION
  ↓
PHASE N → tests/evidence → RPD_PHASE_REVIEW when risky
  ↓
FINAL AUDIT → RPD_FINAL_REVIEW
  ↓
AUDIT_COMPLETE → SUPERGOAL_RUN_COMPLETE
```
"""


def render_roadmap(contract: Contract) -> str:
    research = research_report(contract)
    research_line = f"{research['status']} via {research['provider']} — {research['summary'] or 'no summary'}" if research_required(contract) or contract.compatibility.get("research_gate") else "not required"
    architecture = contract.architecture.data
    assumptions = architecture.get("assumptions", [])
    lines = [
        f"# ROADMAP — {contract.goal.title}", "", "## Decision package",
        f"- Goal ID: `{contract.goal.id}`",
        f"- Done condition: {contract.goal.done_condition}",
        f"- Research evidence: {research_line}",
        "", "## Context summary",
        f"- Profile: `{contract.profile}`",
        f"- Contract revision: `{contract.contract_revision}`",
        f"- Sources: `{len(contract.source_set)}`; phases: `{len(contract.phases)}`; approvals: `{len([a for a in contract.approvals if a.required])}`",
    ]
    if contract.decisions:
        lines += ["", "## Architecture decisions"]
        lines += [f"- {x.get('id', 'decision')}: {x.get('summary', x)}" for x in contract.decisions]
    lines += ["", "## Assumptions"]
    lines += [f"- {x}" for x in assumptions] or ["- Runtime claims are hypotheses until reverified by phase commands."]
    lines += ["", "## Risk top 3"]
    lines += [f"- {r.id}: `{r.tag}` — {r.mitigation or r.severity}" for r in contract.risks[:3]] or ["- none"]
    if contract.approvals:
        lines += ["", "## Human approval manifest"]
        lines += [f"- {a.id}: {'required' if a.required else 'not required'} — {a.scope}" for a in contract.approvals]
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
    review = contract.compatibility.get("rpd_plan_review", {})
    if review:
        lines += ["", "## RPD_PLAN_REVIEW"]
        for key in ["pattern_hunter", "gonzo", "devils_advocate", "integrator", "senior_gate", "overengineering_budget", "mutations_applied", "verdict"]:
            if review.get(key):
                label = key.replace("_", " ").title()
                lines.append(f"- {label}: {review[key]}")
    return "\n".join(lines) + "\n"


def render_state(contract: Contract) -> str:
    baseline = contract.compatibility.get("baseline_ref") or "workspace is non-git; P01 must establish a clean version-controlled baseline before implementation"
    delivery = contract.delivery.data.get("review_pack_version")
    delivery_state = f"{delivery} pending delivery receipt under out/" if delivery else "not requested"
    return f"""# STATE — {contract.goal.title}

Goal identity: `{contract.goal.id}`
Current phase: 1
Total phases: {len(contract.phases)}
Baseline ref: {baseline}
Status snapshot: READY_TO_DISPATCH
Goal complete: no
SUPERGOAL_RUN_COMPLETE: no
Delivery state: {delivery_state}

## Event ledger
- EVT-000001 compiled from CONTRACT.json revision {contract.contract_revision}; implementation phases remain pending.
"""


def render_launch_goal(contract: Contract) -> str:
    marker = "SUPERGOAL" + "_GOAL_BODY:"
    package_root = "this generated SuperGoal package root (the directory containing LAUNCH_GOAL.md)"
    body = (
        f"{marker} From the project root `{contract.goal.workspace_root}`, execute {package_root}. "
        "Read `PROTOCOL.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `STATE.md`, and `phases/phase-*.md` from that package root. "
        f"Goal ID `{contract.goal.id}`. "
        "Start from STATE.md current phase, continue through numbered phases, run the final audit, and finish only after "
        "AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE appear in the same final response with Goal complete: yes. "
        "Preserve the planner/compiler boundary: do not create a production runner or nested /goal; standard Hermes /goal remains the executor."
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
