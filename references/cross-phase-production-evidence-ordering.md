# Cross-phase production evidence ordering

Use this when a SuperGoal mixes local implementation, immutable candidate review, approval, deployment, and live readback.

## Core invariant

Every acceptance criterion must be satisfiable in the phase where it appears using only actions that phase is allowed to perform. A dependency graph is invalid when an early phase requires evidence that can only exist after a later production mutation.

Typical bad shape:

1. pre-approval code phase requires `canonical collector hash == production active collector hash`;
2. production deployment is intentionally deferred to a later approval phase;
3. executor either stalls, changes production too early, or silently defers the criterion and continues.

All three outcomes break the contract.

## Correct split

Separate evidence into distinct criteria:

- **Implementation phase:** source tests, token/secret safety, local overlap probes, candidate metadata verifier, no-live-action flags.
- **Immutable candidate phase:** packaged bytes equal reviewed source; candidate release metadata/artifact SHA; exact-SHA independent review.
- **Production phase:** backup, exact approval, install/switch/restart, canonical/package/active hash equality, process cwd, restart-stability dwell, live readback, rollback proof.
- **Observation phase:** natural post-watermark events/fills and complete accounting; never force a trade to satisfy it.

If a small reversible collector-only deployment is intentionally allowed before the full cutover, declare it as its own production phase with backup, rollback, exact target, and live verification. Do not smuggle it into a local code phase.

## Executor response to a discovered ordering defect

- Do not mark the phase complete with a pending criterion.
- Do not proceed out of order while pretending dependencies are closed.
- Do not mutate production merely to satisfy a planner mistake.
- Record the contradiction in runtime state.
- Amend/recompile before launch when still in planning. If execution is already running, create an explicit contract amendment or stop at the approval boundary; preserve completed evidence and invalidate only affected review/approval receipts.
- Keep candidate work moving only when the runtime protocol explicitly permits safe parallel preparation; label the earlier phase `IN_PROGRESS`, not done.

## Candidate-ready versus installed-ready

Keep these as named sub-states instead of flattening them into one `ready=true`:

- staged read-only history can close a cohort candidate while `databaseReady=false`;
- a built collector can pass candidate tests while `productionActiveHashEqual=false`;
- candidate-snapshot recipient resolution can pass while the active canonical cohort remains unchanged;
- an explicit `APPLIED` marker is still unverified until current symlink, exact release metadata, service process cwd, and stable PID/restart readback agree.

Never describe staged evidence as persisted or tautologically compare a worktree file to itself as “active hash” proof. Bind any later approval to the amended candidate fingerprint when moving criteria changes package identity.

## Review checklist

Before dispatch, inspect every criterion containing: `active`, `production`, `current symlink`, `live hash`, `service cwd`, `restart`, `database applied`, `message sent`, or `exchange fill`.

For each, answer:

1. Which phase creates this evidence?
2. Is that phase allowed to perform the required side effect?
3. Has exact candidate identity already been frozen and reviewed?
4. Is approval minted only after every safe blocking check?
5. Does rollback evidence live in the same phase as the mutation?

Move any criterion whose answer conflicts with phase authority. Production equality is post-deploy evidence; candidate equality is pre-deploy evidence. Never conflate them.
