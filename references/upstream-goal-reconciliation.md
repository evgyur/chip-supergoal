# Upstream-shaped Hermes `/goal` reconciliation

Use this reference when a SuperGoal run targets Hermes `/goal` itself or another persistent goal engine and the aim is to reduce private drift without breaking SuperGoal behavior.

## Target architecture

```text
standard GoalManager / /goal engine
+ generic structured-completion policy helper
+ thin gateway launch adapter
+ focused private regression matrix
```

Do **not** build a custom SuperGoal runner. SuperGoal is a compiler/planner into official `/goal`; the engine remains GoalManager.

## Safe phase sequence

1. **Baseline before edits**
   - Record `HEAD`, branch, tracked status, and ignored `.supergoal/` presence separately.
   - Run the focused private matrix before changing code.
   - Write an invariant ledger before refactor: host terminal markers, package `validate-terminal` authority, blocker states, authoritative runtime-state guard, compression migration, reply/body extraction, button direct-start, startup recovery.

2. **Extract core policy first**
   - Move deterministic pre-judge marker/blocker/disk-state checks out of `GoalManager` into a pure helper such as `hermes_cli/goal_policies.py`.
   - Keep neutral naming: `structured completion`, `required terminal markers`, `handoff/blocker`, not only `SuperGoal`.
   - Keep the helper stdlib-only; no gateway/Telegram/SessionDB/GoalManager imports.
   - `GoalManager` should still own persistence, judge calls, turn budget, subgoals, and continuation prompts.

3. **Extract gateway launch parsing second**
   - Move SuperGoal launch-body parsing out of massive gateway runner code into a thin adapter helper such as `gateway/goal_launch.py`.
   - Helper owns only launch extraction: explicit body marker, `.supergoal` artifact synthesis, bare reply filtering, pasted handoff extraction, and dispatch detection.
   - Goal creation must still call official `GoalManager` path (`_handle_goal_command()` / `GoalManager.set()`), not a custom/nested runner.

4. **Verify and classify drift**
   - Run focused matrix: `tests/hermes_cli/test_goals.py`, goal reply/startup/status/max-turn/verdict tests, Telegram clarify/document tests.
   - Run `git diff --check` and a privacy scan over added lines.
   - Classify remaining private diff as `generic-upstream-candidate`, `private-adapter`, `already-upstream`, or `obsolete`.
   - For every remaining shim/fallback, record: necessity, simpler alternative rejected, removal condition.

5. **Final phase / audit**
   - Do not restart the live gateway unless explicitly approved.
   - Re-run final focused checks and report changed files, verification output, residual risk, and deploy/restart status.

## Regression classes to preserve

- Marker mentions in prose or fenced examples must not satisfy terminal completion.
- `FAILURE_HANDOFF`, `AUDIT_HANDOFF`, and `BLOCKED_BY_APPROVAL` stop as blocked/handoff, not achieved success.
- A v3 package can stop repeated continuations only after `validate-terminal` succeeds for the canonical current root; a disk `STATE.md` label or stale root cannot.
- Active goals migrate across context-compression parent/child sessions.
- Bare `/goal` replies can launch from explicit SuperGoal body marker or visible `.supergoal` artifacts without copying the whole report.
- Telegram reply-to text documents preserve `/goal` as command text and put document body in `reply_to_text`.
- Inline buttons start official GoalManager directly; synthetic slash replay is fragile.
- Startup active-goal recovery uses `GoalManager.next_continuation_prompt()` and stays alert-only for stale/shared/risky side-effect tails.

## Evidence shape

Useful compact evidence for phase reports:

```text
focused matrix: 161 passed
py_compile: exit 0
git diff --check: 0 output lines
privacy scan: 0 secret/private-id/path hits
helper probe: no gateway/Telegram/SessionDB/GoalManager dependency
custom runner probe: no custom/nested goal runner markers
```

## Pitfalls

- Plain `git status --short` can hide ignored `.supergoal/`; use `git status --short --ignored .supergoal` or `find .supergoal -maxdepth 3 -type f`.
- Do not patch `STATE.md` or timestamps manually; package-local state transitions own canonical event time and projection.
- Moving marker guards only to gateway is insufficient: CLI/API and post-compression GoalManager paths still need deterministic pre-judge policy.
- “Smaller diff” is not a success metric if it reopens premature completion, restart, reply, or compression failures.
