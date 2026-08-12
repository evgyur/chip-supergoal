# Embedded RPD v2 review gates

chip-supergoal is independent from any external `/rpd` skill. It embeds the hard RPD protocol directly so the planner and generated `/goal` protocol work after a plain skill install.

RPD v2 imports the durable invariants from the standalone `/rpd` protocol without importing that skill itself: context discipline, evidence tiers, mutation-only findings, Senior Gate for risky work, overengineering budget, and anti-theater synthesis.

## Core contract

RPD is a mutation gate, not a commentary layer.

Every RPD finding must either:
- mutate `ROADMAP.md`, `THINKING.md`, a phase spec, mandatory commands, acceptance criteria, or an audit-fix spec; or
- be marked `checked-holds` with an evidence tier.

Free-floating concerns are invalid. Persona output must collapse into one risk model, one mutation set, and one verdict.

## Evidence tiers

Never present weaker evidence as stronger evidence. Every material RPD claim must carry one tier:

1. `direct artifact` — file:line, command/test output, git diff/status, endpoint response, DOM/screenshot, log, DB/query result.
2. `provided context` — user prompt, uploaded file, chat excerpt, screenshot summary; useful but not independently verified.
3. `external/current source` — current docs/web/API source with URL/date or captured tool output.
4. `assumption` — explicitly labeled with the falsifier/check needed.

Memory and previous plans are not proof of current state.

## Context discipline for SuperGoal

Before RPD judges a plan, phase, or final audit, it must identify the current source set:

- user-provided objective and constraints;
- current project artifacts: `AGENTS.md` / `CLAUDE.md` / `.cursorrules` when present, README/config/package files, tests, logs, task-relevant docs;
- `.supergoal/ROADMAP.md`, `STATE.md`, phase specs, reports, and command outputs;
- current runtime facts only when verified by command/API/browser output.

Older audits, stale phase text, memory, or prior summaries are hypotheses until checked. If the canonical source is unclear and materially changes the plan, RPD must block or mutate the plan to verify it before dispatch/completion.

## Personas

Personas do not produce essays. They produce a finding, evidence tier, and mutation or checked-hold.

### Pattern Hunter
Finds whether the plan repeats a known failure class, matches a proven pattern, or is a false pattern match.

Required output:
- `finding`: `same root cause as X` / `no valid precedent found` / `new pattern because Y`
- `evidence`: tier + artifact/source
- `mutation`: what changed, or `checked-holds`

### Gonzo Truth-Seeker
Names the hidden assumption the plan currently treats as fact.

Required output:
- `claim`: falsifiable assumption
- `status`: true / false / unverified
- `evidence`: tier + artifact/source or falsifier
- `mutation`: what changed, or `checked-holds`

### Devil's Advocate
Stress-tests the plan against a concrete failure path.

Required output:
- `failure mode`: exact way this could break, with inputs/steps when reproducible
- `evidence`: reproduced / checked by command / assumption with next check
- `mutation`: mitigation added, or `checked-holds`

### Integrator
Traces ripple effects across files, services, configs, docs, generated artifacts, user-visible flows, deployment, and rollback.

Required output:
- `touchpoints`: checked / unchecked
- `canonical truth`: source of truth for the affected surface
- `split-brain risk`: concrete risk or `none found`
- `mutation`: what changed, or `checked-holds`

## Senior Gate

Run Senior Gate when a plan/phase/final audit touches production, money, privacy, credentials, auth, payments, model/provider routing, gateway/cron/routing, architecture/migration, public launch, recurring bugs, or claimed completion after a risky run.

The gate is not a persona essay. It is a compact quality-pressure check:

- `elegance/effectiveness`: simpler correct path, or `no issue found` with evidence.
- `overengineering`: unnecessary layer/fallback/agent/shim, or `no issue found` with evidence.
- `principal review`: fragility, rollback gap, privacy leak, verification gap, or `no issue found` with evidence.

For material findings, mark severity `P0/P1/P2/P3` and include an evidence ledger. A Senior Gate finding must mutate a plan/spec/check or block completion; it cannot remain advice.

## Overengineering budget

Any new layer, abstraction, fallback, data flow, agent/subagent, compatibility shim, or generated runtime state must have:

- necessity;
- simpler alternative rejected;
- removal condition.

If the budget is missing, RPD must either delete/shrink the mechanism or mutate the plan/spec to justify and verify it.

## Ponytail binding

Before the roadmap exists, the planner runs `PONYTAIL_SCOPE_GATE` from `references/ponytail-scope-gate.md`. It decides direct work vs SuperGoal and records the minimum owner boundary plus phase/helper/reviewer budget.

`RPD_PLAN_REVIEW` then runs `PONYTAIL_FINAL_CHECK` inside its existing seat. Compare the draft with that pre-plan budget and delete unjustified growth. Check phases, helpers, reviewers, receipts, manifests, services, repositories, schemas, approval gates, and control planes. A kept addition must serve the stated outcome or a reachable trust boundary; hypothetical future scale is not enough.

This is one shrink pass, not another agent/model, protocol marker family, or review round. Ponytail does not weaken auth, privacy, payment, routing, data-loss, rollback, or public-effect verification.

## Mandatory post-draft Senior challenge

Run this immediately after the first complete `ROADMAP.md` + phase-spec draft and before treating the package as launchable:

> Критически оцени все свои решения. Это план на 100 из 100 или его можно усилить? Мне не нужен план внедрения ради внедрения. Senior-план должен допускать: «мы проверили и не внедряем».

This is a decision gate, not motivational copy.

Required behavior:

- Score the current draft from `0` to `100` and name the exact deductions. The score is a pressure-test summary, not evidence and not a target to inflate.
- A `100/100` score is allowed only when no material gap, unsupported assumption, unnecessary layer, or simpler sufficient alternative remains after evidence review.
- Compare the proposed implementation against both `minimal-change` and `do-nothing / do-not-implement` alternatives.
- Choose exactly one verdict: `implement`, `strengthen-and-rereview`, or `do-not-implement`.
- `strengthen-and-rereview` must mutate the artifacts and rerun this gate within the planner stop-loss.
- `do-not-implement` is a valid successful planning outcome when expected value, evidence, reversibility, timing, or complexity does not justify implementation. Preserve the checked evidence and rationale in `THINKING.md` and `ROADMAP.md`; do not emit `READY_TO_DISPATCH`, manufacture implementation phases, or launch `/goal` unless Chip changes the desired outcome.

## Subagent context receipt

If SuperGoal planning/review spawns subagents, each child must receive and return:

```text
context receipt
┈ docs read:
┈ scope:
┈ key constraints:
┈ skipped old context:
┈ unchecked context:
```

Do not accept subagent findings from stale or partial context as direct evidence.

## RPD_PLAN_REVIEW

Runs inside `/chip-supergoal` after `ROADMAP.md` and phase specs are written, before the plan is shown to the user.

It must check:
1. Does `LOOP_DESIGN.md` define a bounded execution loop with host/reviewer/judge roles, verification gates, state, stop conditions, budget, boundaries, egress/redaction, and failure recovery?
2. Are acceptance criteria falsifiable and mapped to evidence tiers?
3. Are risky phases marked with `RPD required: yes` and an accurate `RPD focus`?
4. Is any phase too broad to verify independently?
5. Does the roadmap rely on an unverified assumption that should become a question, command, criterion, or research gate?
6. Where can a partial failure cascade worst?
7. Is the canonical source of truth identified for project state, docs, runtime/config, and generated SuperGoal artifacts?
8. Did new layers/fallbacks/agents/shims pass the overengineering budget?
9. Does this plan require Senior Gate, and if yes, were severity + evidence ledger recorded?
10. After critically re-evaluating every decision, what exact deductions keep the current draft below `100/100`?
11. Does `minimal-change` or `do-nothing / do-not-implement` satisfy the objective better than the proposed implementation?
12. Is the evidence-backed verdict `implement`, `strengthen-and-rereview`, or `do-not-implement`?
13. Against the pre-plan `PONYTAIL_SCOPE_GATE`, what can be deleted or replaced by an existing primitive, and did the draft stay inside its phase/helper/reviewer budget?

Output marker:

```text
RPD_PLAN_REVIEW
Senior challenge: Критически оцени все свои решения. Это план на 100 из 100 или его можно усилить? Мне не нужен план внедрения ради внедрения. Senior-план должен допускать: «мы проверили и не внедряем».
Plan score: <0-100>/100 — <exact deductions; 100 only with no material gap>
Implementation necessity: <proposed implementation vs minimal-change vs do-not-implement>
Ponytail final check: <holds | shrunk: ... | direct-work instead | blocked>
Pattern Hunter: <finding + evidence tier + mutation|checked-holds>
Gonzo: <assumption + true|false|unverified + evidence tier + mutation|checked-holds>
Devil's Advocate: <failure mode + evidence tier + mitigation mutation|checked-holds>
Integrator: <touchpoints + canonical truth + split-brain risk + mutation|checked-holds>
Senior Gate: <required|skipped with reason; P0/P1/P2/P3 findings or checked-holds>
Overengineering budget: <new layers/fallbacks/agents/shims checked + mutations|checked-holds>
Mutations applied: <list or none — checked-holds>
Verdict: implement | strengthen-and-rereview | do-not-implement | blocked-needs-user-input
```

## RPD_PHASE_REVIEW

Runs inside the generated `/goal` session only when the phase spec declares `RPD required: yes` or the phase touches a risky area.

Risky areas:
- auth / authorization / session handling
- payments / billing / financial flows
- secrets / credentials / private data
- database migrations / destructive data changes
- production infrastructure / gateway / cron / routing / model-provider routing
- recurring bugs or baseline-red recovery
- public launch or user-visible irreversible changes
- architecture/migration decisions that create a new source of truth

Output marker:

```text
RPD_PHASE_REVIEW
Phase: N
Focus: <focus>
Evidence map: <direct artifact / provided context / external source / assumption claims>
Pattern: <finding + evidence tier + mutation|checked-holds>
Assumption: <claim + true|false|unverified + evidence tier + mutation|checked-holds>
Stress test: <failure mode + mitigation mutation|checked-holds>
Integration: <touchpoints + canonical truth + split-brain risk + mutation|checked-holds>
Senior Gate: <required|skipped with reason; findings + evidence ledger|checked-holds>
Overengineering budget: <checked + mutations|checked-holds>
Mutations applied before DONE: <list or none — checked-holds>
```

Findings must be fixed before `SUPERGOAL_PHASE_DONE`; otherwise the phase is blocked.

## RPD_FINAL_REVIEW

Runs inside the generated `/goal` session after `AUDIT_VERIFY` and before `AUDIT_COMPLETE`.

It checks what could pass formal audit but still be weak: untested assumptions, unchecked touchpoints, user-visible edge paths, rollback gaps, public/private leakage, stale canonical sources, overbuilt layers, and trust-prior overuse.

Output marker:

```text
RPD_FINAL_REVIEW
Evidence map: <direct artifacts / trust-prior / assumptions>
Pattern: <known/repeat failure class or checked-holds>
Assumption: <completion claim still unverified, or checked-holds>
Stress test: <path that can still break, or checked-holds>
Integration: <unchecked downstream touchpoint + canonical truth, or checked-holds>
Senior Gate: <required|skipped with reason; P0/P1/P2/P3 findings + evidence ledger|checked-holds>
Overengineering budget: <checked + mutations|checked-holds>
Decision: complete | audit-fix-needed | handoff
```

If decision is `audit-fix-needed`, write `.supergoal/phases/audit-rpd-fix-<round>.md`, execute it inline, then rerun the audit round. If decision is `handoff`, update `STATE.md` to `BLOCKED` and do not print `SUPERGOAL_RUN_COMPLETE`.

## Anti-theater rule

- Do not print four separate persona essays.
- Do not expose long internal reasoning.
- Collapse RPD into one root cause, one risk model, one mutation set, and one verdict.
- If the artifact cannot be inspected, say which claim is `assumption` and add the falsifier/check.
- A review that never mutates weak specs and never records checked-holds with evidence is theater; tighten the plan/spec before showing it.
