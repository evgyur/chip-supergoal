# Planner → critic → repair canary loop

The loop is enabled only by the `quality-canary` profile. It is host-side control logic, not a second runtime and not a provider adapter.

## Routes

- `b_only`: deterministic planning and lint only. Critic and judge calls MUST remain zero.
- `b_plus_c`: deterministic lint, one required critic pass, at most two repair rounds, re-lint after each repair, and a judge only when the frozen policy requires it.

## Persisted record

Persist only normalized finding codes, severities, evidence pointers, subject hashes, and the hash-chained mutation ledger. Never persist prompts, hidden reasoning, scratchpads, or raw chain-of-thought.

Each repair must produce a new subject object. The host hashes the before/after projections and immediately reruns deterministic lint. A repeated blocking finding signature is `no_progress` and stops the loop. A third repair round is invalid.

## Failure semantics

Unresolved P0/P1 findings, a missing required critic/judge, an invalid repair payload, a failed judge, or a repeated blocking signature returns `blocked`. Policy thresholds are never weakened to manufacture green.

## Dispatch authority

A green quality report is necessary but insufficient. Stage 6 dispatch requires an explicit, current human approval receipt bound to the exact plan subject and quality report hashes. The canary report itself always records `dispatch_authorized: false`.

## Layer budget

- Necessity: P07 requires one bounded host-side seam that can enforce call counts, re-lint, ledger sealing, and Stage-6 authority in one place.
- Simpler alternative rejected: prose-only routing cannot prove zero calls, two-round limits, or hash-bound approvals in tests.
- Removal condition: delete the canary layer if P08 shows no attributable gain, any P0/P1 regression, budget breach, or profile-isolation failure.

## Rollback

Disable the `quality-canary` profile or remove `canary.py` from the sealed runtime module list. Legacy profiles and their compiler output remain unchanged.
