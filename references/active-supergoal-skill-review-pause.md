# Active SuperGoal skill-library review pause

Use this when Chip interrupts an active SuperGoal with a direct request to review the conversation and update the skill library.

## Rule

A skill-library review is not another SuperGoal phase. Pause the phase loop for that turn, update the relevant loaded class-level skill(s), and reply with a compact library-update report. Do not emit `SUPERGOAL_PHASE_START`, `SUPERGOAL_PHASE_VERIFY`, `SUPERGOAL_PHASE_DONE`, or `SUPERGOAL_TURN_YIELD` in that reply.

If the interrupted SuperGoal was only planning creation/update of a skill and Chip then asks to “review the conversation and update the skill library”, do not hide behind the plan-only boundary. Apply the safe library update immediately: create or patch the class-level umbrella skill with the durable rules already proven in the conversation, add concise `references/` support files, then leave the SuperGoal state paused. The later `/goal` may still perform full hardening, but the explicit library-review request deserves a real skill update now.

## Direct stop behavior

A direct `stop`, `остановись`, or equivalent instruction during execution overrides the standing-goal continuation. Stop tool calls immediately, even if a phase is mid-command or a deliverable is incomplete. Do not use the stop turn to repair, validate, transition state, or continue marker bookkeeping.

Reply with only:

- the last verified phase/state;
- whether the goal is complete;
- any exact partial or invalid artifact the next continuation must repair;
- confirmation that no further side effects were performed after the stop.

On the next continuation, inspect and repair the named partial artifact before replaying mandatory commands. Never overwrite a critical activator/transaction tool with a placeholder: prepare complete content, syntax-check it, then atomically replace the destination so a stop cannot strand an avoidable invalid file.

## Resume behavior

The next host `[Continuing toward your standing goal]` message should resume from `.supergoal/STATE.md` exactly where the loop paused. Do not restart the SuperGoal, do not re-dispatch `/goal`, and do not redo completed phases unless `STATE.md` or evidence files show missing bookkeeping.

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
