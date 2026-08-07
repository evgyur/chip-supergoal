# Standing-goal continuous execution and restart recovery

Session lesson: Chip strongly expects a launched SuperGoal to run from its current `STATE.md` phase through final audit without stopping at phase summaries. `SUPERGOAL_TURN_YIELD` means persist state and continue, not stop.

## Execution rule

When continuing a SuperGoal:

1. Resolve the package's canonical mutable state before trusting the continuation wrapper. For sealed packages, this may be `.supergoal/out/RUNTIME_STATE.md` while `.supergoal/out/STATE.md` remains immutable. Reconcile it with phase reports/evidence and the actual git/worktree/live preflight state.
2. Treat the gateway/GoalManager continuation summary as a locator, not authoritative phase truth. If it says `P03` while disk-backed runtime state and verified artifacts prove `P04`–`P06` already happened, do not move backward, replay completed phases, or overwrite newer evidence. Record the stale-wrapper mismatch and continue from the newest mutually consistent disk-backed state.
3. Execute the current phase and immediately continue to the next safe phase.
4. Do not answer with only a phase status if more phases remain.
5. Stop only when one of these is true:
   - final audit has run;
   - mandatory artifact delivery receipts are green;
   - both `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE` are present;
   - a real approval/safety blocker prevents the next phase.

A user reply like `?` during a standing goal is usually a signal that the agent paused incorrectly. Inspect state and continue; do not switch to explanation-only mode.

## Resume truth and durable runner proof

`Goal resumed` is an operational claim, not a conversational acknowledgement.

Before emitting it, prove at least one of these in the same turn:

- an executor process is running and has a verifiable handle;
- a durable continuation job is enabled and its run is `queued` or `running`;
- the current phase was actually mutated and verified with tool output.

Keep lifecycle words exact:

- `paused/on-demand` — requires a new user message;
- `scheduled` — future tick exists but has not been queued;
- `queued` — scheduler accepted a run but execution has not started;
- `running` — executor is active;
- `resumed` — running work has restarted from canonical state;
- `complete` — terminal audit contract is satisfied.

Never collapse `scheduled` or `queued` into `running/resumed`. A gateway-generated “send any message to continue” card proves the opposite of continuous execution: the goal is waiting for a trigger.

For a standing goal that must outlive the chat turn, create or repair the durable continuation mechanism before ending the turn. Its prompt must be self-contained, bind the canonical package/worktree paths, forbid recursive scheduling and unsafe production effects, identify the current exact blocker/next action, and require verified state checkpoints. Record the job/process handle in mutable runtime state. If delivery is intentionally local/silent, say so; do not imply the user will receive progress messages.

If the user challenges a false status, first acknowledge the incorrect claim plainly, then execute a real recovery action. Do not answer with another promise-only status.

## Hard tool/turn budget continuation

A tool-iteration cap is a transport boundary, not a goal blocker and not permission to reset the mission.

- At phase start and after every hard commit, checkpoint the canonical mutable runtime state with the actual commit, dirty-file summary, last green command, current phase, and exact next action.
- Keep enough budget near the cap for one state checkpoint and an honest final handoff; do not spend the last calls on cosmetic status probes.
- If the runtime interrupts before a checkpoint, the next continuation must reconcile package state with Git HEAD, dirty diff, evidence files, and live read-only state before acting.
- Do not replay stale planner phases or create another successor package when the existing runtime state and worktree can be reconciled.
- The cap response must say the goal is incomplete, name the current phase and verified commit, distinguish committed from uncommitted work, state whether production effects occurred, and say whether user input is actually required.
- Never label the cap itself `BLOCKED_BY_APPROVAL`; resume automatically on the next standing-goal continuation.

## Clean successor SuperGoal pattern

If Chip asks for a new SuperGoal after a messy/partial/manual run:

- create a new root instead of continuing the polluted root;
- import completed reports/evidence from the previous root;
- record the target repo's actual baseline at Phase 0;
- make Phase 1 repair baseline drift before adding more capability;
- explicitly state in `LAUNCH_GOAL.md` that `SUPERGOAL_TURN_YIELD` is not permission to stop.

Do not replay completed phases; preserve them as evidence.

## Gateway restart auto-resume pattern

Active `/goal` sessions must auto-resume after gateway restart even if the last persisted conversation tail contains uncheckpointed assistant tool calls. Withholding creates the exact failure mode Chip objected to: goal stalls and asks for manual poke.

Safer behavior:

- auto-resume the active goal;
- inject an in-band startup recovery note into the continuation prompt;
- tell the resumed agent to inspect persisted state/artifacts first;
- forbid blindly repeating irreversible side effects;
- continue from canonical state files, not from stale chat text.

Regression locations used in this session:

- `gateway/run.py` startup goal recovery classification;
- `tests/gateway/test_goal_startup_recovery.py` open-tool-tail auto-resume case.
