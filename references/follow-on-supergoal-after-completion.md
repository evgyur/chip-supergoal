# Follow-on SuperGoal after a completed package

Use when a completed SuperGoal has produced a real artifact, then Chip asks to plan or execute the **remaining stages**.

## Core rule

Do not mutate or reopen a completed `.supergoal/` package as if it were still in progress.

First verify completion:

- `STATE.md` has `status: COMPLETE` and final phase reached;
- `FINAL_AUDIT.md` exists;
- marker order is `RPD_FINAL_REVIEW` → `AUDIT_COMPLETE` → `SUPERGOAL_RUN_COMPLETE`;
- referenced evidence artifacts exist.

If the user merely sends another continuation wrapper for the same goal, answer `Goal complete: yes` and stop.

If the user explicitly asks for **remaining / next stages**, create a **new sibling package** whose implementation root points at the existing artifact workspace.

## Recommended layout

Example:

```text
completed package:       <workspace>/chip-hlcopy-supergoal/.supergoal
implementation root:     <workspace>/chip-hlcopy-supergoal
follow-on package:       <workspace>/chip-hlcopy-remaining-supergoal/.supergoal
```

The follow-on `STATE.md` should record:

- source package path;
- source package completion markers;
- implementation root;
- baseline evidence/tests;
- approval boundaries.

## Planning pattern

A follow-on package should:

1. cite the completed package and final audit as source state;
2. preserve the old package's final audit and not edit it as an active phase ledger;
3. write new `THINKING.md`, `RESEARCH.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `STATE.md`, `PROTOCOL.md`, `LAUNCH_GOAL.md`, and phase specs;
4. include `RPD_PLAN_REVIEW.md` when money/prod/security stages are in the future path;
5. validate all phase specs and loop design;
6. produce exactly one `SUPERGOAL_GOAL_BODY:` line;
7. archive outside the package tree, usually `/tmp/<name>.tgz`.

## Live-action boundary

If the follow-on plan approaches prod/money/security side effects, the package should explicitly distinguish:

- safe prework: local code, tests, docs, dry-runs, read-only probes, approval package generation;
- blocked live actions: deploy, wallet creation, signing, order submission, payments, DNS, destructive prod changes, etc.

The generated protocol should require `BLOCKED_BY_APPROVAL` before the side effect unless there is exact current approval for the target/action.

## Validation commands

```bash
PYTHONPATH=<installed-chip-supergoal>/lib bash .supergoal/scripts/validate-loop-design.sh .supergoal/LOOP_DESIGN.md
for f in .supergoal/phases/phase-*.md; do
  PYTHONPATH=<installed-chip-supergoal>/lib bash .supergoal/scripts/validate-phase.sh "$f"
done
grep -R '^SUPERGOAL_GOAL_BODY:' .supergoal | wc -l  # must be 1
```

## Pitfall

A common bad move is to keep answering repeated continuation prompts with long summaries or to invent extra work after `SUPERGOAL_RUN_COMPLETE`. Be firm:

- same goal repeated → `Goal complete: yes. Останавливаюсь.`
- explicit next stages → new package, new state, old package remains completed.
