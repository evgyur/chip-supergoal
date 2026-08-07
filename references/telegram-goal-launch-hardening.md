# Telegram Goal launch hardening

Use this when a SuperGoal is launched from Telegram through a native `.md` file or launch card.

## Contract

- Human-facing delivery uses `startup_pack_v4`: exactly `THINKING.md`, `ROADMAP.md`, then `LAUNCH_GOAL.md` last.
- Only `LAUNCH_GOAL.md` may contain `SUPERGOAL_GOAL_BODY:`.
- Other startup files are delivered for review/execution context but must never become reply launch targets.
- Bare reply `/goal` to `LAUNCH_GOAL.md` must keep `event.text == "/goal"`; hydrated document text belongs in `event.reply_to_text`, not in command args.
- If args/text contain `SUPERGOAL_GOAL_BODY:`, canonicalize with the extractor before `GoalManager.set()`.

## Extractor rules

The extracted goal body must stop before any human/instruction tail, including:

- `DONE_CONDITION:`
- `OPERATOR_ACTION:`
- `NOTES:`
- markdown section headers such as `## ...`
- `Artifacts` / `Файлы`
- obvious assistant-report tails such as `Не стартовал...`

Normalize CRLF and do not require a blank line before stop markers. Test no-blank-line and CRLF variants.

## Live proof checklist

Before claiming the launch works:

1. Verify gateway process restarted after the patch.
2. Verify health endpoint.
3. Trigger live launch through the intended path: reply `/goal` to `LAUNCH_GOAL.md` or press the launch-card button.
4. Inspect stored `GoalManager` state for the current `group:<chat>:<thread>` compression tip.
5. Confirm:
   - `status == active`
   - goal contains the canonical SuperGoal body
   - goal does not contain `[Content of replied-to ...]`
   - goal does not contain `DONE_CONDITION`, `OPERATOR_ACTION`, `NOTES`
   - state migrated across compression if the session rotated

A cleared/paused/stale goal is not a valid proof of a fresh launch.

## Pitfall

Do not manually continue phases just because the user pasted the goal text. If the active prompt is the gateway's `[Continuing toward your standing goal]` continuation, execute exactly one phase. Otherwise, first verify/start official GoalManager state and report the status.