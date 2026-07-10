# GoalManager completion-loop incidents

Use when a completed SuperGoal keeps receiving host-generated `[Continuing toward your standing goal]` wrappers, or when a no-op attempt renders as a visible `(empty)` message.

## Session lesson

A completed SuperGoal can still spam a shared chat if the host `/goal` loop keeps scheduling synthetic continuation messages after the task is already complete. Skill-level wording such as “answer only once” is not enough when the control plane continues to deliver wrappers.

Observed bad sequence:

1. SuperGoal had already reached `STATE.md: COMPLETE`, `AUDIT_COMPLETE`, and `SUPERGOAL_RUN_COMPLETE`.
2. Gateway kept injecting `[Continuing toward your standing goal]` wrappers.
3. Agent replied repeatedly with variants of `Goal complete. Stop.`.
4. A later “silent/no-op” attempt returned an empty final response, but Telegram rendered it as `(empty)`.
5. User correctly complained about spam.

## Correct handling in chip-supergoal

- First classify whether the incoming message is a stale host wrapper or a fresh human instruction.
- If it is only a repeated post-complete wrapper and the runtime can truly suppress delivery, no-op silently.
- If the runtime requires a visible final, never return an empty string. Use the shortest explicit marker: `COMPLETE — no-op.`
- If Chip says `Make supergoal` after this class of incident, treat it as a request to create a new files-first SuperGoal for the control-plane/root fix, not to resume the old completed goal.
- Do not reopen the old domain SuperGoal; use it only as incident context.

## Stronger fix direction

For Hermes `/goal` spam or `(empty)` incidents, plan a code-level fix in Hermes control-plane code rather than another prompt-only patch:

- `hermes_cli/goal_policies.py` + `hermes_cli/goals.py`: deterministic narrow terminal-completion fast path before flaky aux judge. Cover both final-response markers and disk state: nested package paths like `<repo>/.supergoal/<package>/STATE.md`, `Status: SUPERGOAL_RUN_COMPLETE`, `AUDIT_COMPLETE: yes`, `SUPERGOAL_RUN_COMPLETE: yes`, and explicit blocked/needs-user-input finals. Do not treat `SUPERGOAL_RUN_COMPLETE: no` / `Goal complete: no` as terminal.
- `gateway/run.py`: stale synthetic continuation queue hygiene after `done`/`paused`; preserve real user pending messages.
- `tui_gateway/server.py`: parity with gateway continuation behavior.
- Tests: `tests/hermes_cli/test_goals.py`, `tests/gateway/test_goal_status_notice.py`, `tests/gateway/test_goal_verdict_send.py`, `tests/tui_gateway/test_goal_command.py`.

## Files-first planning pattern

When generating a SuperGoal for this class of issue, produce human review files first:

- `THINKING.md`
- `ROADMAP.md`
- `LAUNCH_GOAL.md`
- `.supergoal/PROTOCOL.md`
- `.supergoal/STATE.md`
- `.supergoal/phases/phase-*.md`
- `.supergoal/scripts/validate-phase.sh`

The launch goal should explicitly require `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE`, forbid public push, and block live gateway restart unless the active install/service is identified and focused tests pass.
