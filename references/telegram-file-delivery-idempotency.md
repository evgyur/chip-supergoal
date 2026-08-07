# Telegram file delivery idempotency for Chip SuperGoals

## Trigger

Use when a SuperGoal/ТЗ package or final artifacts must be sent to Telegram as native files.

## Lesson

A delivery gate must prevent both missing files and duplicate files. A previous run sent the same 3 review files twice because a `hermes send` timeout led to manual `send_message` fallback and then a script retry.

## Required pattern

- Planning startup delivery is `startup_pack_v4`: exactly `THINKING.md`, `ROADMAP.md`, then `LAUNCH_GOAL.md` last.
- Scripted delivery writes a receipt with target, ordered files, per-file hashes, message IDs, exact file→message-ID mapping, and `launch_message_id`.
- Before sending, script checks existing receipt. If `ok=true`, `sent=true`, target matches, and file hashes match, exit 0 with `skipped_duplicate_send=true`; do not resend.
- Use `SUPERGOAL_FORCE_RESEND=1` only after Chip explicitly asks for resend.
- Dry runs must not overwrite the real success receipt; write a separate `*-dry-run.json` receipt.
- If manual fallback is unavoidable, immediately write the same success receipt (`manual_fallback=true`, target + file hashes) and do not run the send script again for the same artifacts.

## User-facing behavior

If Chip asks why files duplicated, acknowledge the duplicate as an agent/script idempotency failure, not user confusion. Fix the gate, verify `skipped_duplicate_send=true`, and do not send more files while explaining.
