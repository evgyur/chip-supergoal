# Telegram launch-card UX for SuperGoal

The launch UX is file-first and unambiguous.

1. Send the exact three-file `startup_pack_v4` inventory through the scripted sender.
2. `THINKING.md` and `ROADMAP.md` are the only review documents in chat.
3. `LAUNCH_GOAL.md` is the final standalone document, captioned `[SuperGoal START · reply /goal to this file] LAUNCH_GOAL.md`.
4. Do not send a summary or status bubble afterward.

`LAUNCH_GOAL.md` remains the only actual `SUPERGOAL_GOAL_BODY:` surface. A launch card/button may mirror the action, but it must bind to the exact delivered `launch_message_id`; it cannot replace missing files or a missing receipt.

If the button/reply path says no goal exists, inspect the exact document extraction and stored goal body before retrying.
