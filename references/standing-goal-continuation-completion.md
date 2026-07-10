# Standing-goal continuation and completion handling

Use this when Chip replies with `[Continuing toward your standing goal]` or a pasted `LAUNCH_GOAL.md` prompt.

## Rule

A continuation prompt is not a request for another status summary. It is an execution tick.

On each tick:

1. Read `.supergoal/STATE.md` first.
2. If `Status: COMPLETE` and final audit contains both `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE`, stop immediately with a minimal completion statement. Do not rerun phases, rewrite artifacts, or attach the same bundle again.
3. If `Status: IN_PROGRESS`, inspect `Current phase` and execute the next safe phase.
4. Do not stop after `SUPERGOAL_TURN_YIELD` when the next phase is safe and within the manifest. `TURN_YIELD` is a progress marker, not a blocker.
5. Continue phase-by-phase until either:
   - `AUDIT_COMPLETE` + `SUPERGOAL_RUN_COMPLETE` are written and verified;
   - a forbidden side effect would be required, then write `AUDIT_HANDOFF` and stop;
   - a real missing-context/tool blocker prevents safe progress.
6. If the scoped work is beta/live-proven but a repository-wide full-suite gate remains red in unrelated areas, do not silently widen the SuperGoal or loop forever. Re-run the suite, classify exact failures, write `FAILURE_CLASSIFICATION.md`, update `STATE.md`/`AUDIT.md`, and stop at the product/scope decision. See `references/full-suite-red-scope-boundary.md`.

## Goal identity first

When multiple similar SuperGoals exist, resolve the exact goal from the quoted `LAUNCH_GOAL.md` before acting.

Required identity check:

1. Extract the SuperGoal root path from the launch text.
2. Read that root’s `.supergoal/STATE.md`.
3. Use only that root’s phase reports/audit/evidence for status.
4. Do not merge completion status from a sibling goal with a similar name.

Example distinction:

- `polymarket-privy-supergoal` = `chip-polymarket` safe-lane skill/guardrail goal.
- `polymarket-privy-live-rail-supergoal` = runtime execution rail goal.

If Chip asks “этот goal закончен?” or “где аудит?”, answer for the quoted path only and include the exact audit paths/markers. See `references/goal-identity-and-audit-lookup.md` for the detailed audit lookup pattern.

## Pitfall from session

Bad behavior:

```text
Phase 0 done. Next: Phase 1. Stop.
```

This makes Chip manually push the goal again and reads as the goal loop being broken.

Correct behavior:

```text
Phase 0 done. Phase 1 is safe and in-manifest, so continue.
```

Only stop at complete or blocker.

## Repeated continuation after completion

If Chip sends the same continuation prompt after completion, first prevent the gateway from scheduling another synthetic tick:

1. Verify disk completion (`STATE.md` terminal phase/status + final audit has standalone `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE`).
2. Inspect the active Hermes `/goal` state for the current session when possible. If it is still `active`, mark that stale goal row `done` with a disk-backed reason before replying.
3. If you cannot update the goal state row, include the terminal markers as standalone lines in the reply so GoalManager's structured guard can mark the goal done. A bare `Goal complete. Stop.` is not enough for structured SuperGoals that require marker-pair completion.

Preferred compact reply after the stale goal state is closed:

```text
Goal complete. Stop.
```

Fallback compact reply when the active goal state could not be closed:

```text
AUDIT_COMPLETE
SUPERGOAL_RUN_COMPLETE
Goal complete: yes
```

If the continuation keeps repeating after a verified-complete goal and the current run has no access to the GoalManager/session-state write tools, keep the fallback marker pair in the reply instead of downgrading to a bare “Goal complete.” The marker pair is the only durable signal some structured standing-goal wrappers can parse.

Do not spam artifacts or re-explain the full run.

## Duplicated continuation blocks in one message

If one user message contains the same `[Continuing toward your standing goal]` block repeated many times, deduplicate it mentally and execute exactly one tick for the exact goal.

Do not:

- run the same phase multiple times;
- answer once per pasted block;
- treat repetition as separate approvals;
- switch to a sibling goal because it is more recent in the chat.

## Audit lookup output shape

For “where are the audit results?” use compact evidence:

```text
Да, этот goal закончен.

➊ статус
┈ STATE.md: COMPLETE
┈ AUDIT_COMPLETE: <file:line>
┈ SUPERGOAL_RUN_COMPLETE: <file:line>

➋ аудит
┈ final audit: <path>
┈ package/hash: <path/hash if present>

➌ boundary
┈ live mutation: yes/no
┈ readiness label: <safe-lane / guarded-live-disabled / live-enabled>
```

For safe-lane money/trading goals, explicitly state that skill/guardrail completion does not mean live trading is enabled.
