# Manifest-complete portable SuperGoal archives

Use when packaging a compiled SuperGoal for Telegram or another portable handoff.

## The fileset rule

`MANIFEST.json.artifacts` is only the immutable plane. A strict-launchable package also needs its mutable runtime plane.

Build the archive from exactly:

1. every path in `MANIFEST.json.artifacts`;
2. every path in `MANIFEST.json.mutable_paths` that currently exists in the compiled package;
3. `MANIFEST.json` itself.

Do not add unrelated files, cache directories, `__pycache__`, `.pyc`, nested `out/`, planner notes, or the archive itself. Do not omit required mutable files such as:

- `STATE.md`;
- `runtime/STATE.json`;
- `runtime/events.jsonl`;
- `runtime/evidence.json`.

Optional lock/publication files are included only when present and declared under `mutable_paths`.

## Safe packaging sequence

1. Parse `MANIFEST.json`.
2. Verify every immutable artifact's byte count, SHA-256, regular-file type, containment, and mode before archiving.
3. Compute the expected set as `artifacts ∪ present mutable_paths ∪ {MANIFEST.json}`.
4. Compare it to the complete on-disk regular-file inventory. Any extra or missing file blocks packaging.
5. Write one top-level package directory into `tar.gz`; reject absolute paths, `..`, symlinks, hardlinks, and special files.
6. Preserve executable modes. Deterministic uid/gid/mtime is preferred.
7. Extract into a fresh private directory with path-traversal protection.
8. Recompute the extracted inventory and require exact equality with the expected set.
9. Run the extracted package's own `scripts/sgctl.py validate-package <extracted-root> --strict`.
10. Run the package secret scan and hash the final archive.

An archive built from immutable `artifacts + MANIFEST.json` alone can look manifest-correct yet fail extracted strict validation because the runtime state plane is missing. Treat extracted validation as the decisive portable-package check.

## Compiler archive-command pitfall

Some v3 `sgctl archive` commands package **runtime final artifacts** and require paths such as `out/final-artifacts-manifest.json`; they are not general distribution-packaging commands. Probe `sgctl archive --help` and its contract before use. If it governs final runtime artifacts rather than the package fileset, use the skill's dedicated complete-package template/script or a deterministic manifest-driven packager. Never weaken the fileset rule to make the wrong archive subcommand pass.
