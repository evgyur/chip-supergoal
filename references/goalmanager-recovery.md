# GoalManager recovery

Use when a SuperGoal continuation, restart, stale wrapper, repeated complete message, or missing auto-continue behavior appears.

## Recovery order

1. Locate the exact package root for the active goal and run strict package validation.
2. Run `python scripts/sgctl.py state-show`; trust `runtime/STATE.json` and its event journal over chat memory, volatile GoalManager state, or `STATE.md` prose.
3. If `/goal resume` returns `No goal to resume` but the package validates, treat it as a missing volatile goal handle, not proof that work is gone. Continue from authoritative state or re-seed official `/goal` from `LAUNCH_GOAL.md`.
4. If authoritative state selects a numbered phase, resume it.
5. If `AUDITING`, run final audit.
6. If blocked, surface the exact blocker and stop.
7. If `DONE`, require `python scripts/sgctl.py validate-terminal` against `reports/terminal-record.txt` before treating it as completed. A DONE label or markers alone mean continue/recover, not success.

## Wrong-goal guard

If the visible chat wrapper disagrees with the goal/contract identity returned by `state-show`, pause and resolve the exact package root. Do not execute a stale/bogus goal.

## Completion-loop guard

Never print `SUPERGOAL_RUN_COMPLETE` again just to satisfy a repeated wrapper. Completion requires the current exact terminal record and a fresh unchanged `validate-terminal` success; otherwise continue recovery or report the blocker.
