# File-first runtime state for SuperGoal

Use this contract when a SuperGoal must survive context compaction, gateway restarts, and subagent handoffs.

## Architecture

Keep compiled planning artifacts immutable:

- `CONTRACT.json`
- `ROADMAP.md`
- `LOOP_DESIGN.md`
- `PROTOCOL.md`
- `phases/phase-NN.md`
- `runtime-seed/*.md`
- `MANIFEST.json`

Keep mutable coordination only under `out/runtime/`:

- `PLAN.md` — current execution plan and phase order
- `TODO.md` — stable IDs, state, owner, blocker
- `MEMORY.md` — verified facts, decisions, constraints, mistakes to avoid
- `STATUS.md` — current phase, active TODO, owner, blocker, next action, completion state
- `RUN_LOG.md` — append-only evidence-bound events
- `CHECKS.md` — acceptance criteria, commands, results, evidence pointers
- `REVIEW.md` — plan/phase/final review findings and verdicts

Do not collapse these back into one `RUNTIME_STATE.md`. The files have different update rates and different readers; separating them reduces stale state and gives subagents bounded inputs.

## Initialization

Run:

```bash
bash .supergoal/scripts/init-runtime.sh .supergoal
```

The initializer must:

1. create the seven-file bundle atomically from `runtime-seed/` when absent;
2. verify an existing bundle without replacing it;
3. reject incomplete or symlinked state;
4. preserve live state on repeated runs and races;
5. keep `out/runtime/` outside manifest drift checks.

Never edit manifested seeds during execution.

## Start/read protocol

At every run, read in this order:

1. `STATUS.md`
2. `TODO.md`
3. `PLAN.md`
4. relevant sections of `MEMORY.md`
5. latest `RUN_LOG.md` entries
6. `CHECKS.md` and `REVIEW.md` for the active phase

Claim exactly one stable TODO ID before mutating project files. The same owner and TODO ID must appear in `TODO.md` and `STATUS.md`.

## Subagent handoff

Files are not automatically injected into subagents. Every delegation must include:

- package workdir;
- absolute paths to all seven runtime files;
- one claimed TODO ID;
- exact allowed writes;
- required verification command/evidence;
- writeback contract.

A subagent without this envelope works without durable context and must not be treated as a valid loop participant.

## End/writeback protocol

Before returning or advancing:

1. update the claimed item in `TODO.md`;
2. update phase, owner, blocker and next action in `STATUS.md`;
3. append one evidence-bound event to `RUN_LOG.md`;
4. persist criterion/command results in `CHECKS.md`;
5. persist review findings/verdict in `REVIEW.md`;
6. add only durable task-local facts/decisions to `MEMORY.md`;
7. verify the files tell one coherent story.

If any write fails, keep the phase incomplete and repair state before continuing.

## Verification

For compiler/runtime changes, require all of:

- focused RED→GREEN regression for emitted seed files;
- compiled-package manifest contains every `runtime-seed/*.md` file;
- initializer creates all seven live files;
- second initializer run preserves a live-state probe;
- generated `PROTOCOL.md` and `LAUNCH_GOAL.md` name the bundle and handoff rules;
- generated package contains no stale `RUNTIME_STATE.md` references;
- strict package validation;
- full skill tests and user-story probes;
- skill workflow guard.

## Interaction pitfall

When Chip asks whether SuperGoal was “переделан”, do not answer with an architectural assessment or proposal. Implement the requested runtime contract, compile a real package, initialize it, run strict validation and tests, then answer **ready/not ready** with proof.