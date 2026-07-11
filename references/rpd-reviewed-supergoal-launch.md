# RPD-reviewed SuperGoal launch refresh

Use when Chip asks for `/rpd` / xhigh review of a freshly created SuperGoal and then says “дай новый supergoal”.

## Problem pattern

A plan can be directionally right but still fail the SuperGoal quality bar because phase specs keep generic acceptance criteria. If `/rpd` mutates the plan, the launch artifact must be refreshed too; otherwise Chip may start an older body that does not mention the review evidence or mutated criteria.

## Required workflow

1. Run the `/rpd` review against live artifacts, not memory:
   - `.supergoal/LAUNCH_GOAL.md`
   - `.supergoal/ROADMAP.md`
   - `.supergoal/THINKING.md`
   - current `.supergoal/phases/phase-*.md`
2. If the review finds weak/generic acceptance criteria, patch the phase specs in place with phase-specific falsifiable criteria.
3. Re-run `python scripts/sgctl.py validate-phase-markdown <phase-file>` on every touched phase spec; the Bash wrapper is optional Unix compatibility only.
4. Write a compact review artifact under `.supergoal/reports/rpd-xhigh-plan-review-<ts>.md`.
5. Patch canonical contract/review input with the RPD decision and recompile all sealed views; never hand-edit `THINKING.md`, `ROADMAP.md`, or `STATE.md` independently.
6. Verify recompiled `LAUNCH_GOAL.md` references the RPD report and current phase specs.
7. Deliver the refreshed `LAUNCH_GOAL.md` as a native file and tell Chip to reply `/goal` to that file.

## Launch body checklist

The refreshed goal body should mention:

- repository/project root;
- `.supergoal/PROTOCOL.md`, `STATE.md`, `ROADMAP.md`, `THINKING.md`;
- the exact RPD report path;
- “do not treat `.supergoal/archive/` as active” when a stale completed goal was archived;
- approval gates for production/service/billing/bot side effects;
- the real completion condition: phase-specific criteria, required commands, risky-phase RPD evidence, `python scripts/sgctl.py finalize`, and successful `python scripts/sgctl.py validate-terminal` against `reports/terminal-record.txt`; marker lines are compatibility only.

## Pitfall

Do not answer only with “RPD says go”. If the plan was mutated, the operator needs a new launch artifact. The old `LAUNCH_GOAL.md` is stale by definition until rewritten.
