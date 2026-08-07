# Telegram `.md` SuperGoal launch UX

Use when creating or troubleshooting a SuperGoal launch in Telegram.

## Human-facing startup rule

Use `startup_pack_v4`: exactly `THINKING.md`, `ROADMAP.md`, and `LAUNCH_GOAL.md`. The authoritative inventory is `references/artifact-boundaries.md`; all package internals remain on disk.

`LAUNCH_GOAL.md` is sent last. This is intentional UX: Chip can reply `/goal` to the newest standalone document without searching through a summary or archive.

## `LAUNCH_GOAL.md` shape

Keep the file short and explicit:

```md
# <Run name> — SuperGoal launch

> SUPERGOAL_GOAL_BODY:
<raw GoalManager body only; concise execution condition pointing at package files>

DONE_CONDITION:
<human explanation>

OPERATOR_ACTION:
Reply to this file in Telegram with exactly: /goal

NOTES:
- This file is a launch artifact only.
- Posting it does not autostart execution.
```

## Extraction gate

When Telegram hydrates a replied document, `/goal` must store only the raw body after `SUPERGOAL_GOAL_BODY:` and stop before `DONE_CONDITION:`, `OPERATOR_ACTION:`, or `NOTES:`. If the stored goal contains the hydration wrapper or those section tails, clear it before continuation; that launch is invalid.

## Verification checklist

- startup receipt is `startup_pack_v4` and maps exactly the three canonical files to real message IDs;
- no extra package artifact is attached;
- archive passed extraction + strict validation;
- `LAUNCH_GOAL.md` is the final file and its mapped ID equals `launch_message_id`;
- gateway extraction test returns only the intended goal body;
- no prose or unrelated bot message obscures the launch target afterward.

## Bad UX

- paths or raw `MEDIA:` lines instead of documents;
- blank document messages with no filename caption;
- only a summary, only an archive, or only the old review subset;
- sending `LAUNCH_GOAL.md` before the archive/phases and then burying it;
- claiming launch from a GoalManager notice without checking stored goal state.
