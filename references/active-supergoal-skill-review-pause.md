# Active SuperGoal skill-library review pause

Use this when Chip interrupts an active SuperGoal with a direct request to review the conversation and update the skill library.

## Rule

A skill-library review is not another SuperGoal phase. Pause the phase loop for that turn, update the relevant loaded class-level skill(s), and reply with a compact library-update report. Do not emit `SUPERGOAL_PHASE_START`, `SUPERGOAL_PHASE_VERIFY`, `SUPERGOAL_PHASE_DONE`, or `SUPERGOAL_TURN_YIELD` in that reply.

If the interrupted SuperGoal was only planning creation/update of a skill and Chip then asks to “review the conversation and update the skill library”, do not hide behind the plan-only boundary. Apply the safe library update immediately: create or patch the class-level umbrella skill with the durable rules already proven in the conversation, add concise `references/` support files, then leave the SuperGoal state paused. The later `/goal` may still perform full hardening, but the explicit library-review request deserves a real skill update now.

## Resume behavior

The next host `[Continuing toward your standing goal]` message should resume from authoritative `runtime/STATE.json` through `python scripts/sgctl.py state-show`. Do not restart the SuperGoal, re-dispatch `/goal`, or redo completed phases unless package validation, state, or bound evidence proves missing bookkeeping; `STATE.md` is only a checked projection.

## Why

This prevents two bad outcomes:

- polluting the formal SuperGoal transcript with non-phase skill-maintenance work;
- ignoring Chip's explicit meta-workflow request because a goal wrapper is active.

## Output shape

Keep the reply short:

- skill patched
- support file added, if any
- durable lesson captured
- overlap/consolidation note if relevant

If no editable skill fits and protected skills are the only targets, say `Nothing to save.`
