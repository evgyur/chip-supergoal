# SuperGoal execution root hygiene

Use when executing a disk-backed SuperGoal package, especially after a planning package has already been generated.

## Durable lesson

A continuation that contains a concrete `SUPERGOAL_GOAL_BODY` is an execution request, not another planning request. Execute phases through final audit unless a real blocker or approval gate appears.

## Root discipline

Before generating implementation files, set a single implementation root and use it everywhere:

```bash
SG=/absolute/path/to/project/.supergoal
ROOT=/absolute/path/to/project
```

When using tools:

- prefer `terminal(..., workdir=ROOT)` for command-based generation/checks;
- in Python helper scripts, use `Path('/absolute/root')`, not `Path.cwd()` unless the workdir is guaranteed;
- after generation, verify with `find ROOT -maxdepth ...` before running tests.

## Common failure pattern

A helper run from the default Hermes cwd can create `chip_hlcopy/`, `tests/`, `manifests/`, or `pyproject.toml` under the generic workspace directory instead of the SuperGoal project root. If this happens:

1. copy or regenerate the files into the intended root;
2. run tests from the intended root;
3. remove only byte-identical stray generated files/directories;
4. record the cleanup in final audit only if relevant.

## Archive hygiene

Do not create a tarball inside the directory being archived; `tar` can fail with `file changed as we read it`. Write archives to `/tmp` or a sibling path:

```bash
cd "${WORKSPACE_ROOT:-$HOME/workspace}"
tar --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.hypothesis' \
  -czf /tmp/<project>-scaffold.tgz <project>
sha256sum /tmp/<project>-scaffold.tgz
```

Clean transient caches before packaging:

```bash
rm -rf .pytest_cache .hypothesis
find . -type d -name __pycache__ -prune -exec rm -rf {} +
```

## Final audit minimum

Final audit must show:

- phase completion evidence;
- aggregate commands and outputs;
- secret/no-live-path scan;
- `RPD_FINAL_REVIEW`;
- `AUDIT_COMPLETE`;
- `SUPERGOAL_RUN_COMPLETE`.
