# Phase boundary state + characterization pattern

Use this when executing a SuperGoal phase that maps existing recovery/control-plane behavior before implementing runtime changes.

## Pattern

1. Treat Phase 1 as a state-map phase, not a stealth implementation phase.
2. Record the dirty baseline before editing and name pre-existing local diffs separately from phase-created files.
3. Add passing characterization tests for current behavior.
4. Add strict `xfail` tests for the intended later-phase behavior when the implementation is deliberately deferred.
5. Run focused tests immediately; a healthy result can be `N passed, M xfailed` when the xfails are documented future targets.
6. Write a concise report under `.supergoal/reports/` with:
   - canonical state stores and keys;
   - current lifecycle paths;
   - exact gap being pinned;
   - insertion points for the next phase;
   - test names and what each proves.
7. At phase boundary, record evidence and use `python scripts/sgctl.py state-transition` with the expected revision in the same turn; the runtime updates `runtime/STATE.json`, event journal, and `STATE.md` projection together.
8. Print `SUPERGOAL_PHASE_DONE` and `SUPERGOAL_TURN_YIELD`; do not start the next phase in the same assistant turn.

## Pitfall

Do not let a phase finish with only a report and tests while authoritative state still points at the completed phase. The `/goal` loop can otherwise resume the same phase and duplicate work. Never repair this by hand-editing the projection.

## Example result shape

```text
SUPERGOAL_PHASE_VERIFY
pass — state map written: .supergoal/reports/phase-1-state-map.md
pass — characterization tests added: tests/.../test_*.py
pass — current gap pinned with strict xfail targets

pytest ...
2 passed, 3 xfailed

SUPERGOAL_PHASE_DONE
SUPERGOAL_TURN_YIELD
Next state: phase 2
```
