# RPD → SuperGoal handoff

Use this when Chip invokes `/rpd` or asks for xhigh/senior review, then immediately says “Create supergoal” / “сделай SG” in reply to the review.

## Lesson

Treat the quoted RPD verdict as the source task for the SuperGoal package. Do not ask Chip to restate the task when the reply context already names the decision, risks, and next action.

## Required flow

1. Identify the active object from the quoted/replied RPD text:
   - the verdict;
   - the minimal next action;
   - direct artifact paths or repo root;
   - blocked actions / approval boundaries.
2. Generate a fresh `.supergoal/` package for that object:
   - `THINKING.md` preserves the RPD evidence and assumptions;
   - `LOOP_DESIGN.md` defines the governed executor loop;
   - `ROADMAP.md` turns the RPD next action into phases;
   - `LAUNCH_GOAL.md` contains exactly one actual `SUPERGOAL_GOAL_BODY:` line;
   - phase specs include RPD requirements for risky phases.
3. If an existing `.supergoal/` directory is present in the target root, do not mix old artifacts into the new package.
   - If this is an active continuation/repair, resume from `python scripts/sgctl.py state-show` instead of creating a new package.
   - If this is a fresh package, remove or archive stale `.supergoal/` contents before writing the new package, then verify the final file list.
4. Validate before reporting ready:
   - run `python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated`;
   - run `python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md` for every phase;
   - probe that required files exist;
   - ensure only `LAUNCH_GOAL.md` has a line starting exactly `SUPERGOAL_GOAL_BODY:`;
   - list the final `.supergoal/` files so stale residue is visible.

## Output shape

Keep the final report short:

- package root;
- phase count;
- validation result;
- exact launch instruction;
- attach review_pack_v2 when delivery is expected: `THINKING.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `LAUNCH_GOAL.md`, plus non-empty `RESEARCH.md`.

Do not claim execution success. The generated `/goal` executor later earns completion only by creating and validating exact `reports/terminal-record.txt` with `python scripts/sgctl.py validate-terminal`; its `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE` lines are the compatibility projection.
