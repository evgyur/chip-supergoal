# SuperGoal execution root hygiene

Use when executing a disk-backed SuperGoal package, especially after a planning package has already been generated.

## Durable lesson

A continuation that contains a concrete `SUPERGOAL_GOAL_BODY` is an execution request, not another planning request. Execute phases through final audit unless a real blocker or approval gate appears.

## Root discipline

Before generating implementation files, resolve one package root and one
implementation root and pass them as tool working directories on every platform:

```text
package root: <absolute-project-path>/.supergoal
implementation root: <absolute-project-path>
```

When using tools:

- set the tool `workdir` to the implementation root for command-based generation/checks;
- in Python helpers, pass the resolved root as an argument instead of trusting `Path.cwd()`;
- after generation, use native file tools or the sealed manifest to verify outputs before tests.

## Common failure pattern

A helper run from the default Hermes cwd can create `chip_hlcopy/`, `tests/`, `manifests/`, or `pyproject.toml` under the generic workspace directory instead of the SuperGoal project root. If this happens:

1. copy or regenerate the files into the intended root;
2. run tests from the intended root;
3. remove only byte-identical stray generated files/directories;
4. record the cleanup in final audit only if relevant.

## Archive hygiene

Do not create an archive inside the package. The cross-platform authority is:

```text
python scripts/sgctl.py archive --out <absolute-external-archive.zip> --manifest out/final-artifacts-manifest.json
```

Clean transient caches only with bounded platform-native operations after the
resolved roots are verified; never sweep through junctions, symlinks, virtual
environments, or unrelated workspace directories.

## Final audit minimum

Final audit must show:

- phase completion evidence;
- aggregate commands and outputs;
- secret/no-live-path scan;
- `RPD_FINAL_REVIEW`;
- a recomputed final audit;
- `python scripts/sgctl.py validate-terminal` success.
