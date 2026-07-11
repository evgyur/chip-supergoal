# chip-supergoal — maintainer handoff

Public source bundle for the `chip-supergoal` Hermes skill.

## What this is
- Skill root: `chip-supergoal/`
- Purpose: Principal+/Architect+ SuperGoal planner/compiler skill for disk-backed `.supergoal/` packages and standard Hermes `/goal` execution handoff.

## First files to read
1. `README.md`
2. `docs/README.ru.md`
3. `SKILL.md`
4. `references/execution-state-machine.md`
5. `references/upstream-goal-compatibility.md`
6. `scripts/sgctl.py`

## Verify after cloning
Requires CPython 3.11.9 or newer.

```text
python -m pip install --disable-pip-version-check -r requirements-test.txt
python scripts/test.py
```

On Unix-only hosts, also run `bash scripts/test.sh` for shell syntax and style.

## Privacy boundary
The privacy gate scans every tracked file plus bounded untracked files outside
runtime/private state directories. Runtime caches and credentials remain outside
git; force-tracked runtime fixtures are never exempt from the tracked-file scan.
