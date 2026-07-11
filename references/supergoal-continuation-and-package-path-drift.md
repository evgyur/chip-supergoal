# SuperGoal continuation and package path drift

Use when executing or resuming a SuperGoal from a gateway `/goal` continuation.

## Completed wrapper / compression split-brain

If a continuation targets a completed SuperGoal root, do not execute phases again and do not keep repeating completion markers—but first prove completion from package authority.

Check disk state first:

- `python scripts/sgctl.py state-show` reports the exact package identity and `DONE` lifecycle;
- `python scripts/sgctl.py validate-terminal` accepts `reports/terminal-record.txt` against current state and `reports/final-audit.json`;
- handoff/final report exists if the protocol required it.

If compression or gateway state created a new active `goal:<session>` row for that completed root, close that stale active row as `done` with a disk-backed reason. This prevents auto-resume from re-injecting the stale wrapper.

Do not restart a completed root unless Chip explicitly names a new root or a new goal.

## Package path drift

Some generated packages keep human review files at project root (`ROADMAP.md`, `THINKING.md`, `LAUNCH_GOAL.md`) while protocol/phases/state live under `.supergoal/`. A continuation may still say `.supergoal/ROADMAP.md`.

Do not block on that mismatch by itself. Verify package reality:

1. Read `.supergoal/MANIFEST.json` if present.
2. Run package-local `python scripts/sgctl.py validate-package . --strict` and `python scripts/sgctl.py validate-terminal`; do not substitute an obsolete `validate-supergoal.sh`.
3. Use the actual path expected by the package validator.
4. Record the correction in the phase report.

Example: if validator checks root `ROADMAP.md`, use root `ROADMAP.md` even if the continuation text says `.supergoal/ROADMAP.md`.

## Live-activation SuperGoals

When the SuperGoal is a live-capability rail, `делай` / `continue` can authorize implementing fail-closed code phases, but it is not exact approval for money/custody mutation. Keep live actions blocked until the protocol’s exact current-chat approval packet is present and readback is possible.
