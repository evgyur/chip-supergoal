# Gateway `/goal` dispatch rail for Supergoal

Use this reference when Supergoal dispatch through Telegram/gateway behaves like it started but finishes immediately, or when long `/goal` copy/paste is unreliable.

## Durable rule

Supergoal has two phases with different reasoning budgets:

- planning/review may use `xhigh`;
- execution chains should run on session-scoped `high`.

Do not force execution to `xhigh` just because the planning pass used it.

## Required gateway behavior

Hermes gateway `/goal` must support the Telegram reply shortcut:

1. The assistant sends the long body as a normal message prefixed exactly with `SUPERGOAL_GOAL_BODY:`.
2. The user replies to that message with exactly `/goal`.
3. Gateway extracts `event.reply_to_text` as the goal body.
4. Gateway strips `SUPERGOAL_GOAL_BODY:` before storing the goal.
5. Gateway rejects prior `/goal` status lines as goal bodies, especially:
   - `✓ Goal done (...)`
   - `✓ Goal achieved...`
   - active/paused goal status lines.
6. For Supergoal execution dispatches, gateway sets session-scoped reasoning to `high`.

## Required judge guard

For Supergoal chains that explicitly require terminal markers, the judge must not mark the goal complete unless the final response contains the required markers, especially:

- `AUDIT_COMPLETE`
- `SUPERGOAL_RUN_COMPLETE`

This guard belongs in code, not only in prompt text. A weak or overly broad judge can otherwise close a chain after one turn because the response contains generic words like `done`.

## Focused verification

Run from the Hermes checkout:

```bash
git grep -n 'SUPERGOAL_GOAL_BODY\|_goal_text_from_reply_context\|set to high\|SUPERGOAL_RUN_COMPLETE' -- gateway/run.py hermes_cli/goals.py tests/gateway/test_goal_reply_command.py tests/hermes_cli/test_goals.py
python -m pytest tests/gateway/test_goal_reply_command.py tests/hermes_cli/test_goals.py -q -o 'addopts='
python -m pytest tests/gateway/test_goal_status_notice.py tests/gateway/test_goal_max_turns_config.py tests/gateway/test_goal_verdict_send.py tests/tui_gateway/test_goal_command.py -q -o 'addopts='
```

## Update preservation

If the live Hermes checkout is dirty and an update/reset could overwrite local patches, preserve this rail before updating. Treat a missing Supergoal `/goal` rail as a regression, not harmless drift.
