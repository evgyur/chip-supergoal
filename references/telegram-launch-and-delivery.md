# Telegram launch and delivery

Use when a SuperGoal package must be launched through Telegram.

## Launch surface

`LAUNCH_GOAL.md` is the sole launch surface with a real `SUPERGOAL_GOAL_BODY:` line. It is the third and final startup document, with caption:

```text
[SuperGoal START · reply /goal to this file] LAUNCH_GOAL.md
```

Do not use `ROADMAP.md` or `THINKING.md` as hidden launch surfaces. Do not send prose after the launch document.

## Current-thread target verification

1. Resolve the intended chat/topic from active conversation metadata and seal it in `CONTRACT.json.delivery.telegram_thread` as `telegram:<chat_id>:<thread_id>`.
2. Run `hermes send --list telegram --json` and match the exact chat ID plus thread ID. Never fall back to a home channel for a topic request.
3. If ambiguous, block rather than guess.
4. Run `templates/delivery/send-review-md-files.sh`. It reads the sealed contract target and rejects any `SUPERGOAL_DELIVERY_TARGET` override that differs.
5. Upload exactly three native documents: `THINKING.md`, `ROADMAP.md`, `LAUNCH_GOAL.md`.
6. Transport acceptance writes only `out/review-md-files-transport-receipt.json`; it is not completion evidence.
7. Fetch back all three exact message IDs in the sealed topic through a canonical Telegram read path, verify sender, order, filenames, media type, chat/thread, attachment sizes, and downloaded SHA-256 bytes, then write `chip-supergoal.telegram-readback.v1` JSON.
8. Run `templates/delivery/verify-startup-delivery-readback.py` against the contract, transport receipt, and readback JSON. Only its `readback_verified=true` final receipt closes delivery.
9. Links, paths, prose claims, bare `MEDIA:` lines, extra attachments, fewer than three attachments, or transport acceptance without destination readback are not delivery evidence.

## Startup delivery gate

The canonical `startup_pack_v4` inventory lives in `references/artifact-boundaries.md`. The receipt path remains `.supergoal/out/review-md-files-delivery-receipt.json` and must contain:

- `kind="startup-files"`, `pack_version="startup_pack_v4"`, and `readback_verified=true`;
- target exactly equal to the sealed `CONTRACT.json.delivery.telegram_thread`;
- exact ordered files `["THINKING.md", "ROADMAP.md", "LAUNCH_GOAL.md"]`;
- exactly three hashes, three message IDs, and the matching three-entry file→message-ID map;
- `launch_message_id` equal to the third message ID;
- non-empty sender identity;
- three ordered readback items proving exact message IDs, filenames, document media, chat/thread IDs, positive attachment sizes, and downloaded attachment hashes.

Any other inventory blocks `READY_TO_DISPATCH`.

## Idempotency and correction

Use target + the exact three-file hash set for idempotency. Do not resend automatically unless Chip reports missing files or `SUPERGOAL_FORCE_RESEND=1` is set. An earlier pack-version receipt never suppresses a v4 send.

## Final artifacts

Executor final artifacts are separate from planner startup delivery. Send them only when Chip explicitly asks for final artifacts; they do not change the three-file planner default.
