# Planner/executor state hygiene

Use when Chip says “make SuperGoal”, when a package follows work already done in the same chat, or when GoalManager opens a package and immediately sees `COMPLETE`.

## Invariant

`chip-supergoal` is a planner/compiler. A fresh launchable package starts with pending execution state. The planner may inspect, research, validate planning artifacts, and run preflight characterization tests, but it must not impersonate the executor by marking implementation phases complete.

## Fresh package contract

A launchable package must contain at least:

- `THINKING.md`
- `LOOP_DESIGN.md`
- `ROADMAP.md`
- `STATE.md`
- `PROTOCOL.md`
- `LAUNCH_GOAL.md`
- `phases/phase-*.md`

For a normal new mission:

```text
Status: READY_TO_DISPATCH
Current phase: 1
Goal complete: no
SUPERGOAL_RUN_COMPLETE: no
```

Do not create planner-authored completion evidence such as:

- completed phase ledgers without an executor transcript;
- `FINAL_AUDIT.md` claiming implementation success;
- `AUDIT_COMPLETE` or `SUPERGOAL_RUN_COMPLETE`;
- a `STATE.md` whose current phase is `COMPLETE`/`DONE`;
- delivery receipts marked sent before the delivery action occurs.

## Work already happened before “make SuperGoal”

Do not backfill a fake completed SuperGoal around the work.

Choose one honest route:

1. **Remaining work exists:** create a new follow-on package starting at phase 1 for the remaining implementation/verification work. Cite the earlier artifacts as baseline evidence, not completed phase markers.
2. **Only independent verification remains:** create an audit/verification SuperGoal whose numbered phases actually re-run the checks and produce fresh evidence.
3. **Nothing remains:** say the work is already complete and that a new SuperGoal would be fake ceremony; do not manufacture one unless Chip explicitly asks for a re-audit package.

Never manually implement first, mark the package complete, then tell Chip that `/goal` has nothing to execute.

## Required preflight

Before `READY_TO_DISPATCH`:

1. Verify `PROTOCOL.md` exists.
2. For nested roots, render every protocol/state/phase path against the exact package directory.
3. Validate loop design and every phase.
4. Assert exactly one `SUPERGOAL_GOAL_BODY:` line.
5. Re-read `STATE.md` and assert the first pending phase is executable.
6. Keep implementation artifacts and predecessor final audits immutable; use a sibling follow-on package.

## Recovery when GoalManager no-ops immediately

If Chip launches and GoalManager finds `STATE.md` already complete because the planner prematurely advanced it:

1. Own the planner error directly.
2. Inspect whether implementation evidence really exists.
3. If remaining work exists, repair by creating a fresh follow-on package or resetting only an unexecuted package to phase 1 with a ledger entry.
4. Do not rerun completed implementation merely to print markers.
5. Do not defend the no-op as correct behavior when the package itself violated the planner/executor boundary.

## User-facing rule

For Chip, “Make SuperGoal” means: produce a canonical executable package with `PROTOCOL.md`, pending `STATE.md`, validated phases, review files, and one launch handoff. It does not mean “do the work manually and label it complete.”
