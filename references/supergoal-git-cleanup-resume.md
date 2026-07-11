# SuperGoal git cleanup and resume without losing phase truth

Use when a SuperGoal run is interrupted by a request to clean local git, reset a dirty tree, fast-forward `prod`, or preserve WIP before continuing phases.

## Durable lesson

A clean product branch can accidentally remove code changes from already-completed SuperGoal phases while `.supergoal/` remains on disk because it is ignored. This creates split-brain:

- `python scripts/sgctl.py state-show` reports the expected authoritative phase state;
- reports/evidence under `.supergoal/` still exist;
- the clean tracked tree no longer contains the deliverables because they were moved to a WIP branch or reset.

Do not continue the next phase until tracked deliverables for completed phases are present in the active worktree again.

## Safe sequence

1. Before cleanup, preserve dirty tracked/untracked product work into a WIP branch or patch:

```bash
git switch -c wip/<task>-<date>
git add -A
git commit -m "wip: preserve <task> work"
```

2. Return the deploy/main branch to a clean state only after preservation:

```bash
git switch prod
git fetch origin --prune
git reset --hard origin/prod
```

3. Because `.supergoal/` is usually gitignored, explicitly verify both layers before resuming with platform-neutral commands:

```text
git status --short --branch
python .supergoal/scripts/sgctl.py state-show .supergoal
python .supergoal/scripts/sgctl.py validate-package .supergoal --strict
```

4. For every phase already listed in `Completed phases`, check that its tracked deliverables exist in the current worktree, not only in the preserved WIP branch.

5. If a completed phase's deliverables are absent, rehydrate the minimal required files from the WIP branch before running the next phase:

```bash
git checkout wip/<task>-<date> -- path/to/deliverable path/to/test
```

Then rerun that phase's mandatory verifier and record the result through
`record-evidence`; advance state with `state-transition` rather than editing
`STATE.md` manually.

6. Do not cherry-pick or restore a huge unrelated WIP branch wholesale. Use the phase specs and evidence reports as the allowlist. Avoid dragging unrelated production changes, assets, submodules, skills, meeting materials, or old experiments into the SuperGoal branch.

## Verification before `SUPERGOAL_PHASE_DONE`

For the current resumed phase, include evidence that:

- authoritative `runtime/STATE.json` and its `STATE.md` projection match the actual tree;
- restored phase dependencies are present;
- the phase's mandatory command passed after rehydration;
- targeted cleanliness/secret scan covers the restored files;
- any broad `repo-state` noise caused by an old baseline or unrelated `origin/prod` drift is called out honestly instead of hidden.

## Pitfalls

- Do not treat `.supergoal/STATE.md` as enough proof. It is ignored and can outlive a reset.
- Do not delete the WIP branch until the SuperGoal final audit has either merged/adopted or explicitly rejected its relevant deliverables.
- Do not continue directly to the next numbered phase if the active tree lacks deliverables from prior completed phases.
- Do not deploy from a tree that only has `.supergoal` evidence but not the tracked product changes.
