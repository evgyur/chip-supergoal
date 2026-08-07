# Staged Project Flow runs inside one SuperGoal

Use when one standard Hermes `/goal` must supervise several Project Flow runs that have a hard evidence boundary between them—for example, a foundation audit/selection run followed by an implementation or quality run whose baseline must not exist until the first run closes.

## Core topology

```text
one GoalManager /goal
  -> Project Flow A (foundation/selection)
  -> machine-verified closure barrier
  -> Project Flow B (dependent implementation)
  -> SuperGoal final audit
```

“One `/goal`” means one GoalManager lifecycle and one `LAUNCH_GOAL.md`; it does **not** mean one Project Flow `STATE.yaml`. Give each run its own DecisionPackage, state path, project root, evidence ledger, and terminal predicate.

The SuperGoal is the controller/judge. Project Flow plus Shaw are the implementers. Do not let both layers execute the same slice.

## Deferred-materialization invariant

Before Flow A closes, Flow B may exist only as non-executable planning semantics in the sealed SuperGoal contract/phase specs. The following must remain absent:

- Flow B `STATE.yaml`;
- an ingestible Flow B DecisionPackage;
- Flow B tasks in Flow A state;
- a dependent candidate branch/worktree whose creation would assume the foundation verdict;
- activation of a feature/profile that the mission is itself supposed to build.

This distinction avoids a common false start: a planner pre-generates the second DecisionPackage, a resident supervisor discovers it, and downstream work begins on an unselected baseline.

## Closure predicate for Flow A

Do not invent an advisory `closed: true`. Derive closure from current authority:

1. Project Flow state validates.
2. The executable task IDs are exactly the allowed Flow A set; forbidden downstream prefixes are absent.
3. `todo`, `in_progress`, and blocking work are empty.
4. No active run/lease or unresolved completion writeback remains.
5. Every required task is in `done` with typed passing evidence.
6. The decision artifact contains exactly one admissible verdict.
7. The selected baseline/foundation SHA is materialized and reconstructible.
8. Required capability, platform, rollback, and P0/P1 gates are green.
9. Any reviewed source/plan has been transplanted onto the selected foundation without semantic drift.

Emit an immutable `foundation-closure` receipt containing state hash, verdict, selected and rollback authorities, capability/evidence hashes, source-plan hash, and unresolved P0/P1 counts. A receipt alone is not authority: the admission guard must recompute the predicates against the live artifacts.

## Atomic admission to Flow B

The first downstream SuperGoal phase owns one package-local guard such as `flow-boundary.py open-dependent`. It is a validator/state-transition helper, not an alternate phase runner.

Required sequence:

1. acquire a bounded lock;
2. verify Flow B root/state is absent;
3. recompute every Flow A closure predicate;
4. verify the closure receipt and selected-foundation binding;
5. materialize Flow B DecisionPackage from sealed phase semantics plus the selected-foundation receipt;
6. initialize and validate Flow B under a staging directory;
7. assert exact downstream task IDs, dependencies, Shaw executor routing, and write scopes;
8. atomically rename staging into the live Flow B root;
9. emit a `dependent-flow-opened` receipt.

On any failure, leave Flow B absent, quarantine/remove staging, keep the SuperGoal at the admission phase, and print a real blocker marker. Never create an empty state and “fill it later.”

## Phase shape

Prefer:

- non-numbered package preflight;
- one SuperGoal phase per Project Flow slice;
- the last Flow A phase produces the closure receipt;
- the first Flow B phase performs admission and then supervises its first slice;
- no ceremonial barrier-only phase unless it has an independently useful deliverable;
- one final SuperGoal audit after all Flow B slices.

Phase specs may be present from package compilation; Project Flow tasks must not be materialized early. This preserves planning completeness without claiming execution has begun.

## Dispatch ownership

Choose exactly one Project Flow dispatcher for each run:

- the GoalManager invokes one bounded orchestrator step and then verifies writeback; **or**
- a resident supervisor owns dispatch while GoalManager only observes/verifies.

Do not use both concurrently. Keep default WIP at 1 unless tasks have explicit dependencies, disjoint non-empty write scopes, and a proven parallel budget.

A Shaw command wrapper must return a single ResultEnvelope JSON object with typed evidence. Exit code or prose output alone proves launch, not completion.

## Bootstrap rule for self-upgrades

When the mission builds a new planner/profile/quality engine, compile the outer mission package with the current stable profile. Do not activate the not-yet-built feature to judge or dispatch its own implementation. Introduce and test the candidate profile only in its declared downstream phase; keep profile-off/legacy compatibility blocking from that point onward.

## Stop versus no-go

Separate execution-integrity blockers from decision outcomes:

- **Hard stop:** source/hash drift, no unique foundation verdict, missing required capability/platform evidence, unresolved P0/P1, invalid typed evidence, premature Flow B state, privacy/authority breach.
- **Continue to a no-go closeout:** candidate fails promotion, an optional semantic layer adds no value, calibration is insufficient, canary is inconclusive, or cost gates fail. The final phase should retain the baseline, remove unproved integration, preserve evaluation evidence, and prove rollback.

`promotion blocked` is not automatically `SuperGoal failed`.

## Final-audit probes

The final audit should be read-only/idempotent and prove:

- both Project Flow states validate;
- Flow A contains only its allowed tasks;
- Flow B creation event follows the verified Flow A closure event;
- the first dependent commit/worktree binds to the selected foundation SHA;
- no downstream task/diff/state existed before admission;
- profile-off/default compatibility remains green;
- decision-red outcomes were not reinterpreted as success;
- rollback and terminal-record validation pass;
- exactly one launch body exists and final markers are emitted only after audit authority passes.

Do not rerun mutating dispatch, worktree creation, deployment, migration, signing, or publication commands during final audit; verify those through immutable receipts and live readback.