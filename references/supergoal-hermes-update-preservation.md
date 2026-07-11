# SuperGoal Hermes update preservation

## Trigger

Use this when a SuperGoal `/goal` launch bug required patching Hermes gateway/GoalManager code and the user asks whether the fix will survive a Hermes update.

## Durable lesson

A live gateway patch is not durable until both layers are true:

1. The live Hermes checkout commits the code and pushes it to Chip's private Hermes fork (`private/main`) when the user wants it shipped, not just locally verified.
2. The server operations/update runbook documents the private rail so future upstream merges treat missing behavior as a private-patch regression, not harmless upstream drift.

Do not tell Chip “it is safe across updates” if the fix exists only as dirty files in `<runtime-dir>`.

## Current upstream-shaped preservation checklist

For SuperGoal launch-pipeline fixes, preserve this split instead of re-inlining everything into `gateway/run.py` / `hermes_cli/goals.py`:

- `hermes_cli/goals.py` stays the persistent `/goal` engine: persistence, turn budgets, continuation prompts, judge call, compression migration, parse-failure pause, and status transitions.
- `hermes_cli/goal_policies.py` owns host structured-completion compatibility: standalone footer markers, handoff/blocker prefixes, and blocked-state classification. For v3 packages it must defer completion authority to successful `python scripts/sgctl.py validate-terminal` against `reports/terminal-record.txt`, not a `STATE.md` label or marker pair.
- `gateway/goal_launch.py` owns launch parsing only: `SUPERGOAL_GOAL_BODY:` extraction, report-tail stripping, `.supergoal/...` artifact synthesis, bare reply filtering, pasted handoff detection, and SuperGoal dispatch detection.
- `gateway/run.py` keeps thin compatibility shims and the official `GoalManager` start/recovery path. It must not create a custom/nested SuperGoal runner.
- `gateway/platforms/telegram.py` hydrates replied document content into `event.reply_to_text` while preserving bare `event.text == "/goal"`; inline SuperGoal start buttons call the official `GoalManager` path and must not rely on queued slash-command replay.

## Required behavior to preserve

- Explicit `/goal status|pause|resume|clear|stop|done` still behave as normal control-plane commands.
- Bare `/goal` as a reply uses `reply_to_text` as the goal body.
- If the reply or hydrated file contains `SUPERGOAL_GOAL_BODY:`, extract only the body before `GoalManager.set()`.
- Extraction strips launch/report tails including `DONE_CONDITION:`, `OPERATOR_ACTION:`, `NOTES:`, `Artifacts:`, `Файлы:`, `Кнопки`, markdown headings, CRLF/no-blank-line boundaries, and explicit standalone `/goal` lines.
- Numbered instructions inside the goal body are valid and must not be truncated as button choices.
- A pasted full handoff starts only when it contains both `SUPERGOAL_GOAL_BODY:` and a standalone bare `/goal` line; `/goal status` in pasted text must not auto-dispatch.
- Telegram clarify button choice 1 / Start now must start the official `GoalManager` goal for the clarify owner session, not the clicker’s separate group session.
- If the button starts `/goal` while the planning turn is still blocked on clarify, skip exactly one post-turn judge pass and enqueue the first continuation at that post-turn boundary so the pre-goal planning answer is not counted as the first goal turn.
- Queued slash-command fallback is intentionally not used for SuperGoal button starts; gateway safety code discards queued slash commands by design.
- Telegram UX defaults to `review_pack_v2`: `THINKING.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `LAUNCH_GOAL.md`, plus non-empty `RESEARCH.md`; `LAUNCH_GOAL.md` is the canonical human launch document and default `SUPERGOAL_GOAL_BODY:` carrier.

## Commands that prove the preservation pattern

```bash
cd <runtime-dir>
python -m py_compile \
  hermes_cli/goals.py hermes_cli/goal_policies.py \
  gateway/run.py gateway/goal_launch.py gateway/platforms/telegram.py gateway/slash_commands.py
python -m pytest \
  tests/hermes_cli/test_goals.py \
  tests/gateway/test_goal_reply_command.py \
  tests/gateway/test_goal_startup_recovery.py \
  tests/gateway/test_goal_status_notice.py \
  tests/gateway/test_goal_max_turns_config.py \
  tests/gateway/test_goal_verdict_send.py \
  tests/gateway/test_telegram_clarify_buttons.py \
  tests/gateway/test_telegram_documents.py \
  -q -o 'addopts='
python - <<'PY'
from pathlib import Path
assert 'evaluate_structured_completion_guard' in Path('hermes_cli/goals.py').read_text()
assert 'is_structured_handoff_reason' in Path('hermes_cli/goals.py').read_text()
assert 'GoalManager' not in Path('gateway/goal_launch.py').read_text()
assert 'goal_launch' in Path('gateway/run.py').read_text()
PY
git diff --check
```

If shipping to the private fork:

```bash
git add \
  hermes_cli/goals.py hermes_cli/goal_policies.py \
  gateway/run.py gateway/goal_launch.py gateway/platforms/telegram.py \
  tests/hermes_cli/test_goals.py \
  tests/gateway/test_goal_reply_command.py \
  tests/gateway/test_goal_startup_recovery.py \
  tests/gateway/test_goal_status_notice.py \
  tests/gateway/test_goal_max_turns_config.py \
  tests/gateway/test_goal_verdict_send.py \
  tests/gateway/test_telegram_clarify_buttons.py \
  tests/gateway/test_telegram_documents.py
git commit -m "fix(gateway): stabilize upstream-shaped supergoal goal rail"
git push private HEAD:main
git rev-list --left-right --count HEAD...private/main
```

Server-doctor/update-runbook side:

```bash
# update references/hermes-private-update-workflow.md with the same upstream-shaped split
# commit and push only that docs/runbook change; do not sweep unrelated dirty files
```

## Final proof before retrying `/goal`

After restart and before asking Chip to retry, verify:

```text
gateway ActiveState=active
health ok
visible topic GoalManager status cleared/inactive before retry
LAUNCH_GOAL.md extracts clean Resume/Execute SuperGoal body
THINKING.md and ROADMAP.md contain no SUPERGOAL_GOAL_BODY
focused tests pass
```
