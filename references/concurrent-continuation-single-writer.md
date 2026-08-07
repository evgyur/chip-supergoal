# Concurrent continuation: single-writer worktree discipline

Use this when a standing `/goal`, cron continuation, interactive Hermes turn, or delegated coding worker can touch the same checkout.

## Invariant

A mutable worktree has exactly one writer at a time. Scheduler-level `workdir` serialization only orders scheduler jobs; it does not serialize them against the current chat session, GoalManager, delegated agents, or external coding CLIs.

## Before editing

1. Read mutable runtime state and identify every possible writer: current turn, GoalManager, continuation cron, background terminal process, delegated agent, and external coding CLI.
2. Pick one writer. Pause or stop other durable writers before the first patch. Record the paused job handle and intended resume condition in runtime state.
3. Check live process/job state and file mtimes. Do not infer quiescence from `git status` alone: another writer may create or replace a file immediately afterward.
4. Re-read the complete target file after the worktree is stable. Partial pagination is not sufficient before a whole-file rewrite.

## Collision circuit breaker

A tool warning that a sibling modified the file after the last read is a hard stop, not advisory noise.

- Do not overwrite with `write_file`.
- Do not keep applying patches while the sibling is active.
- Pause the durable writer you control; wait until target mtimes stabilize; then re-read the complete file and current diff.
- Preserve the sibling's implementation, reconcile intent, and use targeted patches only.
- If the other writer cannot be identified or stopped, leave the worktree unchanged and report a concurrency blocker.

After reconciliation, rerun the affected focused tests, lint, `git diff --check`, and any candidate/package smoke. Evidence produced before the collision does not attest the reconciled tree.

## Continuation handoff

Before resuming a cron/GoalManager writer:

1. Update runtime state with exact completed work, current blocker, last green commands/counts, dirty-tree status, and production-effects status.
2. Verify the durable job is enabled and has a future tick; distinguish `scheduled`, `queued`, and `running`.
3. Resume only after the interactive writer has stopped mutating the checkout.

## Background command visibility

`notify_on_complete` is user-visible delivery. Do not enable it for exploratory internal coding-agent runs whose raw stderr/stdout is not a useful user artifact.

- Prefer the active Hermes provider/delegation path when it already works.
- Before using a standalone coding CLI, run a small non-mutating auth preflight and confirm its credential boundary separately from Hermes provider auth.
- Use user-visible completion notifications only for bounded tasks whose final output is intentionally safe and useful to deliver.
- If a raw internal log is delivered accidentally, explain ownership directly, state whether side effects occurred, and fix the execution route rather than blaming a separate bot.

## Verification checklist

- [ ] One writer owns the worktree.
- [ ] No sibling-modification warnings remain unresolved.
- [ ] Full target files were re-read after stabilization.
- [ ] Focused tests and diff checks were rerun after reconciliation.
- [ ] Runtime state names the current blocker and continuation handle.
- [ ] Continuation is resumed only after interactive mutation ends.
