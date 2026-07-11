# Process integrity for production Supergoal runs

Use this reference when a Supergoal touches production systems, deploys, auth, payments, routing, bots, cron, gateway behavior, or any user-visible service.

## Lesson captured

A production task can be technically completed while still failing the Supergoal contract if the agent manually edits, deploys, or advances `STATE.md` outside the `/goal` transcript. That breaks the point of Supergoal: visible, reproducible phase evidence and an audit the user can trust.

## Hard rule

If the user asks for Supergoal, or corrects the agent for acting outside Supergoal:

- `/chip-supergoal` remains planning-only.
- Do not edit product code, deploy, migrate, restart services, or mark phases complete in the planning chat.
- Safe recon and safe pre-flight checks are allowed only to prepare the plan/handoff.
- Existing manual edits are `dirty baseline`, not completed phases.
- A formal run counts only when `/goal` records package-bound phase evidence and
  `python scripts/sgctl.py validate-terminal` accepts the exact
  `reports/terminal-record.txt`. These transcript lines remain compatibility
  projections:
  - `SUPERGOAL_PHASE_START`
  - `SUPERGOAL_PHASE_VERIFY`
  - `SUPERGOAL_PHASE_DONE`
  - `AUDIT_COMPLETE`
  - `SUPERGOAL_RUN_COMPLETE`

## Dirty baseline handling

When manual work already exists:

1. Stop direct execution immediately.
2. Record the current git SHA and dirty tree in the new Supergoal artifacts.
3. Regenerate a pristine package or use legal state commands; never reset `STATE.md` by hand.
4. Add Phase 0: audit and reconcile dirty baseline.
5. The `/goal` run must decide what to keep, fix, revert, or deploy.
6. Do not summarize manual work as “Phase done”. Call it `manual execution evidence` or `dirty baseline evidence`.

## Production-specific completion bar

For production tasks, final audit must re-check both repo state and live state:

- full tests/lint/build/preflight;
- release SHA matches the deployed commit;
- service statuses are active;
- changed public/API routes are probed live;
- migrations/env/schema reload are verified where relevant;
- logs are checked for the changed path;
- smoke data is cleaned up;
- blockers prevent `finalize`/`validate-terminal`; `SUPERGOAL_RUN_COMPLETE` text never bypasses them.

## Messaging pattern

After plan approval, send one `SUPERGOAL_GOAL_BODY:` message and ask the user to reply exactly `/goal`. Do not keep working in the planning chat after printing the handoff.
