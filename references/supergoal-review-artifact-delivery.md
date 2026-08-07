# SuperGoal startup artifact delivery

Compatibility reference for older callers. The active policy is `startup_pack_v4` in `references/artifact-boundaries.md` and `references/telegram-supergoal-artifact-delivery-correction.md`.

## Required behavior

- Deliver into the exact current Chip DM/engineering/SuperGoal thread; do not over-apply the `chiptg` preview guard.
- Send exactly `THINKING.md`, `ROADMAP.md`, and `LAUNCH_GOAL.md` separately.
- Send `LAUNCH_GOAL.md` last with a `/goal` reply caption.
- Require an exact three-entry file→message-ID receipt.
- A summary, file paths, bare `MEDIA:` lines, extra attachments, or a missing canonical file is blocked.

If Chip reports missing files, force-resend the complete current startup pack first. Do not answer with another explanation while the files remain absent.
