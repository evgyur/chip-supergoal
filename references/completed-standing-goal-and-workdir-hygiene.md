# Completed standing-goal and workdir hygiene

Use when executing or resuming a disk-backed SuperGoal from repeated continuation prompts.

## Completion gate

Before doing any new work, validate package-owned completion authority:

- `python scripts/sgctl.py state-show` reports terminal `runtime/STATE.json` state;
- `reports/final-audit.json` recomputes against current evidence and inventory;
- `python scripts/sgctl.py validate-terminal` accepts the exact terminal record;
- required delivery reservations are closed and receipts remain valid.

If these hold, return the already-validated terminal outcome and stop. Marker
prose or `STATE.md` alone is never completion proof.

For **repeated identical continuation wrappers in the same chat**, avoid turning completion checks into a loop of fresh audits. After one current-session `validate-terminal` success, later identical wrappers should only confirm the package identity has not changed, then stop with the compact final report. Do not re-run tests, live probes, archives, or phase validation merely to satisfy another wrapper.

## Workdir hygiene pitfall

When implementation is supposed to live under a disk-backed package root, tool cwd can still be the session cwd. Before writing scaffold files, explicitly bind the implementation root and verify outputs landed there.

Recommended pattern:

```text
cd <absolute-package-root>
python scripts/sgctl.py validate-package . --strict
```

After scaffold generation, verify:

```text
python -c "from pathlib import Path; import json; print('\n'.join(item['path'] for item in json.loads(Path('MANIFEST.json').read_text(encoding='utf-8'))['files']))"
```

Also inspect the parent/session directory for accidental generated siblings.

If files were accidentally written to the session cwd, copy only byte-identical intended artifacts into the package root, then remove the stray generated paths. Do not leave duplicate `tests/`, package modules, manifests, or skill folders outside the intended root.

## Archive hygiene

Do not create the archive inside the package. Use
`python scripts/sgctl.py archive --out <absolute-external-archive.zip> --manifest out/final-artifacts-manifest.json`;
the packaged authority verifies the external ZIP destination and writes the
result manifest inside the package-owned mutable output plane.

## Final report shape

For repeated continuations after completion, keep the reply short:

```text
Goal complete: yes. Останавливаюсь.
┈ runtime state = DONE
┈ validate-terminal = passed against current package and audit
┈ live actions remain BLOCKED_BY_APPROVAL
```
