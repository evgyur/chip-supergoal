# Phase marker bookkeeping after interrupted SuperGoal turns

Use this when a SuperGoal phase was actually verified on disk, authoritative state advanced through package-local commands, but the visible chat transcript missed one or more required markers because the assistant turn was interrupted, compacted, or delivered incompletely. `STATE.md` is only the checked projection.

## Contract

The `/goal` evaluator reads the visible transcript, not only files. A phase is not visibly complete unless the assistant prints the required marker blocks:

- `SUPERGOAL_PHASE_START`
- `SUPERGOAL_PHASE_VERIFY`
- `MEMORY_SAVED: <name|none>`
- `SUPERGOAL_PHASE_DONE`
- `SUPERGOAL_TURN_YIELD`

## Recovery pattern

1. Run `python scripts/sgctl.py state-show` first.
2. If authoritative state has already advanced past phase N and bound report/evidence files exist, do not redo phase N work.
3. Print a bookkeeping-only marker block for phase N using real evidence from the report, command logs, and authoritative state.
4. Include `MEMORY_SAVED: none` unless a real durable learning was saved.
5. Continue the authoritative next phase in the same run when safe. Use `SUPERGOAL_TURN_YIELD` only for a real blocker or host-forced cutoff.

## What not to do

- Do not transition the phase complete a second time merely to repair transcript bookkeeping.
- Do not invent command output. Quote only evidence already captured in report/logs or rerun a safe verifier if evidence is missing.
- Do not turn bookkeeping into a courtesy phase stop; continuous safe execution still applies.
- Do not ask Chip to send `/goal` again if the standing-goal wrapper is active.

## Good visible wording

`SUPERGOAL_PHASE_VERIFY` should say explicitly that this is transcript bookkeeping for an already-recorded phase, then list the evidence paths and pass/fail criteria. This makes the evaluator and Chip see why no new product edits happened in this turn.
