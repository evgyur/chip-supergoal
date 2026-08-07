# Supergoal → /goal pipeline: continuous execution / forced-yield discipline

## Durable lesson

Chip expects a SuperGoal to run through all safe phases and final audit without stopping at normal phase boundaries. A phase boundary is a checkpoint for `STATE.md` and evidence, not a reason to return control.

`SUPERGOAL_TURN_YIELD` is still a marker, but it means **forced yield**: platform/tool budget cutoff, real safety/approval blocker, or other unavoidable pause. It must not be emitted as a courtesy stop after every `SUPERGOAL_PHASE_DONE`.

## Execution rule

Treat `/goal` as the scheduler and keep working until one terminal condition is reached:

1. Read `STATE.md` and the current `phase-N.md`.
2. Run the phase, print `SUPERGOAL_PHASE_VERIFY`, print `SUPERGOAL_PHASE_DONE`, update `STATE.md`.
3. Immediately continue to phase N+1 or `AUDIT`.
4. Stop only for:
   - `AUDIT_COMPLETE` + `SUPERGOAL_RUN_COMPLETE`;
   - forced platform/tool cutoff;
   - real safety/approval blocker;
   - unrecoverable verification failure after the recovery protocol.

## Async review and turn-budget discipline

A pending reviewer is a gate, not useful executor work. Do not burn GoalManager turns by polling its transcript, rereading unchanged runtime files, repeating status replies, or launching speculative next-phase scouts.

- Prefer synchronous/in-process RPD when it can finish inside the active executor turn.
- If asynchronous review is unavoidable, persist exactly one parked state with `review_id`, exact subject hash, terminal callback contract, and deadline; yield once.
- Duplicate standing-goal wrappers while the same review is pending must not consume an execution turn: do no tools, do not poll, do not repeat reports, and suppress the reply when the gateway supports `NO_REPLY`.
- Resume only on the terminal callback or one deadline diagnostic. Partial transcripts are not verdicts.
- Never mutate the reviewed subject or begin a dependent phase while the gate is open. Never start a second speculative reviewer merely to look busy.
- A package should budget at most one waiting turn per external gate. If its loop design requires repeated chat continuations just to wait, the package is defective and must be retired in favor of a fresh sibling.
- Combine adjacent safe phases and reviews when their evidence can be closed in one executor turn; phase count is not progress.

## False blockers

Do not stop for these when they are part of Chip's requested private verification:

- private DM smoke/readback to Chip's own bot or Chip DM;
- local tests, compile/lint/typecheck, repo cleanup;
- read-only service/config/log/usage/ledger inspections;
- direct low-risk smoke with an already configured scoped key;
- report/state writes and evidence packaging.

If they fail, repair/retry or classify as a verification failure. Do not ask for approval unless the repair would touch a real gate.

## Real gates

Real gates are money/topup/trading, DNS, secrets/credential disclosure or creation, grants/access changes, destructive production mutation, public/mass posts, permanent default-model switch, plugin disable, session reset, or missing credentials/external outage after retrieval attempts.

## Operator pitfall

If Chip says the goal stalled, do not explain the old one-phase protocol. Read `STATE.md`, reassess any blocker, and continue. If a prior generated package still encodes one-phase-per-turn, patch its `PROTOCOL.md` / `LAUNCH_GOAL.md` before resuming.

## Resuming / finishing an existing plan

When Chip asks to finish a partially completed SuperGoal:

1. Read existing `.supergoal/STATE.md`.
2. Preserve completed phases as evidence.
3. Patch stale executor text that says to stop after each phase.
4. Continue from the current phase through final audit.
5. Use `SUPERGOAL_TURN_YIELD` only if forced to yield or truly blocked.

## Marker contract

Successful phase checkpoint:

```text
SUPERGOAL_PHASE_START
SUPERGOAL_PHASE_VERIFY
SUPERGOAL_PHASE_DONE
```

Forced-yield/blocker checkpoint, only when needed:

```text
SUPERGOAL_TURN_YIELD
Goal complete: no
Next: <phase|AUDIT|blocked marker>
```

Final completion:

```text
AUDIT_COMPLETE
SUPERGOAL_RUN_COMPLETE
Goal complete: yes
```
