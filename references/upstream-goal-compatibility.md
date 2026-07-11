# Upstream `/goal` compatibility

Use this reference whenever `chip-supergoal` generates or updates a SuperGoal package. The target runtime is the standard Hermes Agent `/goal` / `GoalManager` loop, not a custom phase runner.

## Boundary

Hermes upstream `/goal` owns:

- persistent goal state in `SessionDB.state_meta` under `goal:<session_id>`;
- turn continuation by appending a normal user-role continuation prompt;
- judge calls after each assistant response;
- max-turn budget, pause/resume/clear/status, and restart recovery for active safe goals.

`chip-supergoal` owns:

- compiling the task into a disk-backed `.supergoal/` package;
- `PROTOCOL.md`, `ROADMAP.md`, `STATE.md`, phase specs, receipts, and audit rules;
- an upstream-compatible `LAUNCH_GOAL.md` containing exactly one launch body;
- transcript markers that make the standard judge continue or stop correctly.

Forbidden:

- no custom runner and no custom GoalManager replacement;
- no chain of nested `/goal` commands;
- no hidden alternate launch body in `ROADMAP.md`, `THINKING.md`, or `PROTOCOL.md`;
- no assumption that upstream `/goal` understands SuperGoal phases, receipts, audit, or approval state by itself.

## Compiler contract

`LAUNCH_GOAL.md` must compile the package into a self-contained standing goal. The launch body must tell the standard `/goal` executor to:

1. load `PROTOCOL.md`, `STATE.md`, `ROADMAP.md`, and `phases/phase-*.md` from the package root;
2. continue from authoritative `runtime/STATE.json` through package-local commands rather than chat memory or the `STATE.md` projection;
3. continue through numbered phases in the same run; phase boundaries are checkpoints, not stop points;
4. use `SUPERGOAL_TURN_YIELD` only for forced platform cutoff or a real blocker/gate, never as a courtesy phase stop;
5. treat the whole goal as incomplete until the exact package terminal record validates and its `AUDIT_COMPLETE` / `SUPERGOAL_RUN_COMPLETE` compatibility lines are printed in the same final response;
6. stop with explicit `BLOCKED_BY_APPROVAL`, `FAILURE_HANDOFF`, or `AUDIT_HANDOFF` only for real blockers.

## Judge-proof turn endings

Because the standard judge sees only the goal plus the last response snippet, a forced-yield or blocker turn must explicitly say the whole goal is not complete. Do not produce this footer after an ordinary phase when more safe work can continue.

Forced-yield/blocker footer:

```text
SUPERGOAL_TURN_YIELD
Goal complete: no
Next: <phase N+1|AUDIT|blocked marker>
Completion requires: a validated package terminal record whose final response contains AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE.
```

A normal phase `SUPERGOAL_PHASE_DONE` is not whole-goal completion and not a stop condition. Continue to the next phase/audit unless a real gate, real blocker, or platform cutoff exists.

Required final footer:

```text
AUDIT_COMPLETE
SUPERGOAL_RUN_COMPLETE
Goal complete: yes
```

This footer is emitted only as part of the exact package-generated terminal
record. Without a validated package terminal record, the footer is compatibility
text rather than completion authority and the judge must continue. If audit
passes but `SUPERGOAL_RUN_COMPLETE` is missing, the judge must also continue.
The executor proves that precondition with
`python scripts/sgctl.py validate-terminal` against
`reports/terminal-record.txt` before returning the footer.

## Blocker semantics

The upstream judge treats “blocked / needs user input” as done for the loop. Use that deliberately:

- `BLOCKED_BY_APPROVAL` for missing bounded approval/manifest;
- `FAILURE_HANDOFF` after the 3-strike failure path;
- `AUDIT_HANDOFF` after audit cannot close.

Every blocker response must include exact blocker, required user input, package path, and current `STATE.md` state. Do not use blocker markers for convenience pauses.

## Turn budget

Default upstream budget is 20 turns. Package generation should prefer <=20 executor turns total, including audit and expected retry rounds. If a task needs more, encode a visible warning in `THINKING.md` and `LAUNCH_GOAL.md` recommending `goals.max_turns` increase or task splitting.

## Compatibility test prompts

Use these as static/judge probes:

1. Phase done + `SUPERGOAL_TURN_YIELD` + `Goal complete: no` → continue.
2. `AUDIT_COMPLETE` without `SUPERGOAL_RUN_COMPLETE` → continue.
3. `SUPERGOAL_RUN_COMPLETE` without `AUDIT_COMPLETE` → continue.
4. Both final markers + `Goal complete: yes` without a validated package terminal record → continue.
5. `BLOCKED_BY_APPROVAL` with required manifest → done as blocked.
