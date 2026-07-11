# Goal identity and audit lookup for overlapping SuperGoals

Use this when Chip references a `LAUNCH_GOAL.md`, asks “этот goal закончен?”, or several similar SuperGoals exist for the same domain.

## Problem pattern

Overlapping goals can share nouns but target different artifacts, for example:

- `chip-polymarket safe-lane SuperGoal` — skill/library guardrails only, no runtime trading.
- `Polymarket execution rail through chip-privy` — runtime/control-plane implementation.

Do not answer from the most recent topic or memory alone. Resolve the exact goal identity from the quoted `LAUNCH_GOAL.md` and its path.

## Required workflow

1. Extract the goal root from the quoted launch text, usually:
   - `Goal: Implement ... in /path/to/supergoal ...`
2. Run `python scripts/sgctl.py state-show` in that package and bind the reported goal/contract identity to the replied launch file.
3. Treat it as complete only when `python scripts/sgctl.py validate-terminal` accepts the exact `reports/terminal-record.txt` against current `runtime/STATE.json` and `reports/final-audit.json`.
4. Verify any named external archive/result and required delivery receipt.
5. Report the result for that exact goal only. Do not merge status from a sibling goal.
6. If the goal is not complete, read `Current phase` and continue only that phase.

## Output shape for “where is the audit?”

Use a compact evidence-first answer:

```text
Да, этот goal закончен.

➊ статус
┈ runtime/STATE.json: DONE
┈ validate-terminal: passed
┈ terminal record: <path + hash>

➋ аудит
┈ final audit: <path>
┈ phase audit: <path if relevant>

➌ результат
┈ verdict: PASS/BLOCKED
┈ delivered: <1–3 concrete artifacts>
┈ live mutation: yes/no
```

If it is a safe-lane/skill goal, explicitly say it does not mean live trading is enabled.

## Duplicated continuation blocks

If one user message contains the same `[Continuing toward your standing goal]` block repeated many times, deduplicate it mentally and execute exactly one tick for the exact goal. Do not run the same phase multiple times and do not answer once per pasted block.

## Pitfall

Bad: “Polymarket is done” when the safe-lane skill goal is complete but the execution rail is still in progress.

Good: “The safe-lane `chip-polymarket` goal is complete; the live execution rail is a separate goal and is currently phase N.”
