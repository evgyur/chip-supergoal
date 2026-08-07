# Telegram SuperGoal artifact delivery correction

Use whenever a Chip-facing SuperGoal is dispatched or Chip reports missing, excessive, unlabeled, or path-only files.

## Canonical correction

Every new Chip-facing dispatch uses `startup_pack_v4` from `references/artifact-boundaries.md`.

## Required sequence

1. Generate and strictly validate the complete package on disk.
2. Resolve the exact current Telegram chat/topic with `hermes send --list telegram --json`.
3. Run `templates/delivery/send-review-md-files.sh` through a real native-document transport.
4. Send exactly `THINKING.md`, `ROADMAP.md`, `LAUNCH_GOAL.md`, in that order.
5. Caption the final file `[SuperGoal START · reply /goal to this file] LAUNCH_GOAL.md`.
6. Parse each real Telegram `message_id`, store the exact three-entry file→message-ID map, and fetch all three messages back from the same topic.
7. Only then emit `READY_TO_DISPATCH`. Send no prose after `LAUNCH_GOAL.md`.

## If delivery is wrong

Without an explicit resend request, resend exactly the current three-file pack only after canonical readback proves the prior effect absent. If Chip explicitly asks to resend, run the canonical sender with a fresh unique `SUPERGOAL_DELIVERY_RUN_ID=resend-<UTC timestamp>` so the resend has its own durable attempts and receipt. Never call `hermes send --file` / `-f` manually: this runtime can acknowledge it while producing text-only messages. The packaged `send-file-via-hermes-cli.sh` adapter is mandatory. `SUPERGOAL_FORCE_RESEND=1` may bypass an old aggregate receipt, but it must never bypass a `prepared` or `unknown_delivery` attempt. Ambiguous transport means `UNKNOWN_DELIVERY`: recover the real message ID read-only or block; never auto-resend. Fetch back every returned ID and require `has_media=true` plus `media_type=MessageMediaDocument`; a successful CLI response with `has_media=false` is delivery failure.

A complaint such as «где файлы», «слишком много файлов» or «пришли нормально» is an active delivery failure:

1. Send no explanation before transport.
2. Resolve the current topic exactly.
3. Run the real three-file sender in the same turn.
4. Verify all three message IDs and keep `LAUNCH_GOAL.md` last.
5. If transport or verification is unavailable, emit `SUPERGOAL_REVIEW_FILES_BLOCKED` with the concrete blocker.

## Hard failures

All of these are `SUPERGOAL_REVIEW_FILES_BLOCKED`:

- anything other than exactly three default attachments;
- missing `THINKING.md`, `ROADMAP.md`, or `LAUNCH_GOAL.md`;
- extra archive, phase, JSON, research, state, protocol, or loop attachments;
- wrong order or `LAUNCH_GOAL.md` not last;
- paths, links, bare `MEDIA:` lines, blank/unlabeled documents;
- guessed or absent message IDs;
- a receipt whose version is not `startup_pack_v4`.
