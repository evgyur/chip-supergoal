# Telegram Markdown goal launch hardening

## User-facing contract

Dispatch `startup_pack_v4` exactly as defined by `references/artifact-boundaries.md`: `THINKING.md`, `ROADMAP.md`, then `LAUNCH_GOAL.md` last. Package internals are not default chat attachments.

Only `LAUNCH_GOAL.md` may contain a real `SUPERGOAL_GOAL_BODY:` line. Its caption tells Chip to reply `/goal` to that file. No later prose may obscure the reply target.

## Extraction gate

When `/goal` is a reply to the document, extract only the body after `SUPERGOAL_GOAL_BODY:` and stop before `DONE_CONDITION:`, `OPERATOR_ACTION:`, and `NOTES:`. Reject hydration wrappers, empty paths, or a body copied from another startup file.

## Delivery proof

`READY_TO_DISPATCH` requires the v3 receipt with all phase specs, ordered message IDs, exact file→message mapping, and `launch_message_id` equal to `LAUNCH_GOAL.md`. A visible GoalManager notice is not proof of stored-goal correctness or execution.
