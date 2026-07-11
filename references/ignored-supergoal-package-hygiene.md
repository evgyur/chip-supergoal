# Ignored `.supergoal/` package hygiene

Use this when creating or executing a SuperGoal package inside repos where `.supergoal/` is gitignored.

## Lesson

`git status --short` can show a clean tree while a full `.supergoal/` package exists under ignored files. That is correct for implementation cleanliness, but it can hide stale package artifacts during planning or make phase evidence look contradictory.

## Planner rule

Before creating a new package:

1. Inspect for an existing `.supergoal/` directory even if git status is clean.
2. If the user asked for a new SuperGoal and the existing package is stale/unrelated, delete or archive it before writing the new package.
   - Move the whole stale package to an explicitly named external quarantine outside the repo/package tree; never hide historical material inside the new package or weaken scans to accommodate it.
   - Recreate the package root only after the old root is absent and the external quarantine destination is verified.
3. After writing, verify the package directly, not through git status:
   - required files exist and are non-empty;
   - phase specs pass `python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md`;
   - exactly one actual launch line starts `SUPERGOAL_GOAL_BODY:`;
   - no non-launch artifact has a line starting `SUPERGOAL_GOAL_BODY:`.
4. When reporting git status, distinguish:
   - tracked implementation status (`git status --short`);
   - ignored package visibility (`git status --short --ignored .supergoal`).

## Executor rule

During phase verification, optional Unix `repo-state.sh` may report `0` when
only ignored runtime state changed. Use `python scripts/sgctl.py state-show` for
authoritative state and bind implementation-file observations through evidence;
the helper never proves state, audit, or completion.

## Good evidence wording

```text
tracked git status: clean
.supergoal package: ignored intentionally, verified directly
runtime/STATE.json: state-show reports phase 2; STATE.md projection matches
implementation changed_files_since_baseline: 0
```

This prevents a false conflict between “tracked tree clean” and “SuperGoal state updated”.
