# Supergoal → /goal pipeline: continuous execution / forced-yield discipline

## Durable lesson

Chip expects a SuperGoal to run through all safe phases and final audit without stopping at normal phase boundaries. A phase boundary is a package-local state/evidence checkpoint, not a reason to return control.

`SUPERGOAL_TURN_YIELD` is still a marker, but it means **forced yield**: platform/tool budget cutoff, real safety/approval blocker, or other unavoidable pause. It must not be emitted as a courtesy stop after every `SUPERGOAL_PHASE_DONE`.

## Execution rule

Treat `/goal` as the scheduler and keep working until one terminal condition is reached:

1. Run `python scripts/sgctl.py state-show`, then read the authoritative current `phase-N.md`.
2. Run the phase, print `SUPERGOAL_PHASE_VERIFY`, print `SUPERGOAL_PHASE_DONE`, and transition package state through `python scripts/sgctl.py state-transition ...`; never hand-edit `STATE.md`.
3. Immediately continue to phase N+1 or `AUDIT`.
4. Stop only for:
   - successful `python scripts/sgctl.py validate-terminal` against the exact `reports/terminal-record.txt`;
   - forced platform/tool cutoff;
   - real safety/approval blocker;
   - unrecoverable verification failure after the recovery protocol.

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

If Chip says the goal stalled, do not explain the old one-phase protocol. Read authoritative state through `state-show`, reassess any blocker, and continue. If an old generated package encodes stale behavior, recompile it rather than hand-patching sealed views.

## Resuming / finishing an existing plan

When Chip asks to finish a partially completed SuperGoal:

1. Run `python scripts/sgctl.py state-show` for the existing package.
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

Final compatibility projection (only the exact record created by `python scripts/sgctl.py finalize` and accepted by `python scripts/sgctl.py validate-terminal`):

```text
AUDIT_COMPLETE
SUPERGOAL_RUN_COMPLETE
Goal complete: yes
```

The full authority is `reports/terminal-record.txt`, including its identity and
audit-hash lines; the three displayed footer lines alone must continue.
