# Embedded RPD review gates

chip-supergoal is independent from any external `/rpd` skill. It embeds the review pattern directly so the planner and generated `/goal` protocol work after a plain skill install.

## Core contract

RPD is a mutation gate, not a commentary layer.

Every RPD finding must either:
- mutate `ROADMAP.md`, a phase spec, mandatory commands, acceptance criteria, or an audit-fix spec; or
- be marked `checked-holds` with evidence.

Free-floating concerns are invalid.

## Personas

### Pattern Hunter
Finds whether the plan repeats a known failure class or matches a proven pattern.

Required output:
- `finding`: same pattern as X / new pattern because Y
- `evidence`: file, command output, repo convention, transcript marker, or explicit `unverified`
- `mutation`: what changed, or `checked-holds`

### Gonzo Truth-Seeker
Names the hidden assumption the plan currently treats as fact.

Required output:
- `claim`: falsifiable assumption
- `status`: true / false / unverified
- `mutation`: what changed, or `checked-holds`

### Devil's Advocate
Stress-tests the plan against a concrete failure path.

Required output:
- `failure mode`: exact way this could break
- `evidence`: reproduced / checked by command / unverified
- `mutation`: what changed, or `checked-holds`

### Integrator
Traces ripple effects across files, services, configs, docs, generated artifacts, and user-visible flows.

Required output:
- `touchpoints`: checked / unchecked
- `split-brain risk`: concrete risk or `none found`
- `mutation`: what changed, or `checked-holds`

## RPD_PLAN_REVIEW

Runs inside `/chip-supergoal` after `ROADMAP.md` and phase specs are written, before the plan is shown to the user.

It must check:
1. Are acceptance criteria falsifiable?
2. Are risky phases marked with `RPD required: yes` and an accurate `RPD focus`?
3. Is any phase too broad to verify independently?
4. Does the roadmap rely on an unverified assumption that should become a question, command, or criterion?
5. Where can a partial failure cascade worst?

Output marker:

```text
RPD_PLAN_REVIEW
Pattern Hunter: ...
Gonzo: ...
Devil's Advocate: ...
Integrator: ...
Mutations applied: ...
Verdict: ready-for-review | revised-and-ready | blocked-needs-user-input
```

## RPD_PHASE_REVIEW

Runs inside the generated `/goal` session only when the phase spec declares `RPD required: yes` or the phase touches a risky area.

Risky areas:
- auth / authorization / session handling
- payments / billing / financial flows
- secrets / credentials / private data
- database migrations / destructive data changes
- production infrastructure / gateway / cron / routing
- recurring bugs or baseline-red recovery
- public launch or user-visible irreversible changes

Output marker:

```text
RPD_PHASE_REVIEW
Phase: N
Focus: <focus>
Pattern: ...
Assumption: ...
Stress test: ...
Integration: ...
Mutations applied before DONE: ... | checked-holds
```

## RPD_FINAL_REVIEW

Runs inside the generated `/goal` session after `AUDIT_VERIFY` and before `AUDIT_COMPLETE`.

It checks what could pass formal audit but still be weak: untested assumptions, unchecked touchpoints, user-visible edge paths, rollback gaps, and private/public leakage.

Output marker:

```text
RPD_FINAL_REVIEW
Pattern: ...
Assumption: ...
Stress test: ...
Integration: ...
Decision: complete | audit-fix-needed | handoff
```

If decision is `audit-fix-needed`, write `.supergoal/phases/audit-rpd-fix-<round>.md`, execute it inline, then rerun the audit round.
