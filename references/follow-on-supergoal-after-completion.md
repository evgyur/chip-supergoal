# Follow-on SuperGoal after a completed package

Use when a completed SuperGoal has produced a real artifact, then Chip asks to plan or execute the **remaining stages**.

## Core rule

Do not mutate or reopen a completed `.supergoal/` package as if it were still in progress.

First verify completion:

- `python scripts/sgctl.py state-show` resolves the source package to `DONE`;
- `reports/final-audit.json` exists and recomputes cleanly against the sealed package;
- `reports/terminal-record.txt` exists and `python scripts/sgctl.py validate-terminal` succeeds;
- required delivery reservations are closed and referenced evidence artifacts exist.

If the user merely sends another continuation wrapper for the same unchanged
goal after that fresh validation, answer compactly and stop. Footer markers or
the `STATE.md` projection alone are not completion proof.

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
- source package identity and validated terminal-record hash;
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
7. archive to an absolute external path outside the package tree.

## Live-action boundary

If the follow-on plan approaches prod/money/security side effects, the package should explicitly distinguish:

- safe prework: local code, tests, docs, dry-runs, read-only probes, approval package generation;
- blocked live actions: deploy, wallet creation, signing, order submission, payments, DNS, destructive prod changes, etc.

The generated protocol should require `BLOCKED_BY_APPROVAL` before the side effect unless there is exact current approval for the target/action.

## Validation commands

```text
cd <follow-on-package-root>
python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated
python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md
python scripts/sgctl.py validate-package . --strict
```

Run phase validation once for every phase, and verify that only
`LAUNCH_GOAL.md` contains a line beginning `SUPERGOAL_GOAL_BODY:`. Bash wrappers
are optional Unix conveniences, not validation authority.

## Pitfall

A common bad move is to keep answering repeated continuation prompts with long summaries or to invent extra work after a current terminal record validates. Be firm:

- same goal repeated → `Goal complete: yes. Останавливаюсь.`
- explicit next stages → new package, new state, old package remains completed.
