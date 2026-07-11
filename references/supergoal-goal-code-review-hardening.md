# SuperGoal `/goal` code-review hardening lessons

Use when reviewing or fixing Hermes `/goal` / SuperGoal launch and continuation code after a refactor.

## Review standard

- Run at least one independent post-fix review after the first repair pass; the first fix often exposes a second-order control-plane bug.
- Treat P0/P1/P2 findings as blocking until fixed and re-verified. Do not stop at “tests pass” if the review found an untested race or false-completion path.
- Keep `GoalManager` as the official owner of goal state, turn budgets, continuation prompts, and judge outcomes. Parser helpers must not grow their own runner/session logic.

## Completion guards

- Handoff/blocker markers may carry same-line details: `FAILURE_HANDOFF: ...`, `AUDIT_HANDOFF — ...`, `BLOCKED_BY_APPROVAL — ...`. Parse them as non-fenced line prefixes, not exact-only standalone strings.
- Disk completion is safe only when `python scripts/sgctl.py validate-terminal`
  accepts the exact `reports/terminal-record.txt` against the current sealed
  package, authoritative `runtime/STATE.json`, recomputed audit, inventory, and
  delivery state. `STATE.md` labels and recorded transcript markers are never
  sufficient.
- Relative `.supergoal/...` paths must not steal completion from an explicit absolute root. Use cwd-relative `.supergoal` only when the goal text does not name a stronger root.

## Telegram clarify/button starts

- A SuperGoal Start button must enter the official `GoalManager` path for the clarify owner session, not the clicker’s separate group/user session.
- Never rely on queued `/goal ...` slash-command replay as fallback: gateway safety code can discard queued slash commands by design.
- If the button starts `/goal` while the planning turn is still blocked on clarify, suppress exactly one post-turn judge pass for the pre-goal planning answer and queue the first real continuation at that boundary.

## Launch-body parsing

- `SUPERGOAL_GOAL_BODY:` extraction should strip launch metadata (`DONE_CONDITION:`, `OPERATOR_ACTION:`, `NOTES:`, `Artifacts:`, `Файлы:`, `Кнопки`, headings, explicit `/goal` lines) without truncating valid numbered instructions inside the goal body.

## Verification minimum

- `python -m py_compile` for `hermes_cli/goals.py`, `hermes_cli/goal_policies.py`, `gateway/run.py`, `gateway/goal_launch.py`, `gateway/platforms/telegram.py`, `gateway/slash_commands.py`.
- Focused tests for `tests/hermes_cli/test_goals.py`, `tests/gateway/test_goal_reply_command.py`, `tests/gateway/test_telegram_clarify_buttons.py`.
- Broader goal matrix including startup recovery, status notices, max turns, verdict sends, Telegram documents.
- Package terminal regressions covering marker-only prose, stale state/audit, and exact terminal-record validation.
- `git diff --check`, conflict-marker scan, static added-line scan for obvious secrets/injection patterns, and a boundary probe proving parser helpers do not import/use `GoalManager`.
