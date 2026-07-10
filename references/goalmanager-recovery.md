# GoalManager recovery

Use when a SuperGoal continuation, restart, stale wrapper, repeated complete message, or missing auto-continue behavior appears.

## Recovery order

1. Locate `.supergoal/STATE.md` for the active goal.
2. Trust `STATE.md` over chat memory and over GoalManager's volatile session state.
3. If `/goal resume` returns `No goal to resume` but a valid SuperGoal package/`STATE.md` exists, treat the command result as a missing volatile goal handle, not proof that the work is gone. Continue from `STATE.md` in ordinary task mode or re-seed `/goal` from `LAUNCH_GOAL.md`.
4. If `Current phase` is numeric, resume that phase.
5. If `AUDIT`, run final audit.
6. If `BLOCKED`, surface the blocker and stop.
7. If `DONE`, do not re-run work; answer with the completion evidence or package location.

## Wrong-goal guard

If the visible chat wrapper points to a different goal than `STATE.md`, pause and ask for the correct package path or goal identity. Do not execute a stale/bogus goal.

## Completion-loop guard

Never print `SUPERGOAL_RUN_COMPLETE` again just to satisfy a repeated wrapper. Completion requires current package evidence; otherwise summarize that the goal is already complete or blocked.
