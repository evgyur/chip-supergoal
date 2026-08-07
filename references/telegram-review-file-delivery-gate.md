# Telegram startup-file delivery gate for SuperGoal packages

Before asking Chip to start any SuperGoal, deliver canonical `startup_pack_v4` into the exact current Telegram thread.

## Gate

1. Strict-validate the package on disk.
2. Send `THINKING.md` first.
3. Send `ROADMAP.md` second.
4. Send `LAUNCH_GOAL.md` last with a caption telling Chip to reply `/goal` to it.
5. Require the `startup_pack_v4` receipt with exactly three ordered files, hashes, message IDs, exact file→message-ID mapping, and matching `launch_message_id`.

Paths, bare `MEDIA:` lines, blank documents, guessed IDs, missing canonical files, or any extra attachment fail closed with `SUPERGOAL_REVIEW_FILES_BLOCKED`.

When Chip reports files missing, force-resend the whole current startup pack before explaining.
