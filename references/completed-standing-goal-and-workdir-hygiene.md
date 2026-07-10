# Completed standing-goal and workdir hygiene

Use when executing or resuming a disk-backed SuperGoal from repeated continuation prompts.

## Completion gate

Before doing any new work, inspect the package state and final audit markers:

- `STATE.md` has `status: COMPLETE` and `current_phase` at the final phase;
- `FINAL_AUDIT.md` exists;
- marker order is `RPD_FINAL_REVIEW` before `AUDIT_COMPLETE` before `SUPERGOAL_RUN_COMPLETE`;
- referenced evidence artifacts still exist.

If these hold, answer `Goal complete: yes` and stop. Do not re-run phases or invent “next steps” merely because the continuation wrapper repeats.

For **repeated identical continuation wrappers in the same chat**, avoid turning completion checks into a loop of fresh audits. After one current-session verification has already read `STATE.md`, `FINAL_AUDIT.md`, phase specs, and evidence paths, later identical wrappers should only do the minimum needed to confirm nothing materially changed (or use unchanged/read dedupe when available), then stop with the compact final report. If the same wrapper repeats again after that, do **not** call tools again just to re-read unchanged files; answer from the already-verified completion gate unless the user explicitly asks to re-verify, run tests, inspect fresh evidence, or the package path/goal changed. Do not re-run tests, live probes, read-only network calls, archives, phase validation, or local readback scripts merely to satisfy another wrapper.

## Workdir hygiene pitfall

When implementation is supposed to live under a disk-backed package root, tool cwd can still be the session cwd. Before writing scaffold files, explicitly bind the implementation root and verify outputs landed there.

Recommended pattern:

```bash
ROOT=/absolute/package/root
cd "$ROOT"
# create files under $ROOT only
```

After scaffold generation, verify:

```bash
find "$ROOT" -maxdepth 3 -type f | sort
# also check parent/session cwd for accidental stray generated dirs
```

If files were accidentally written to the session cwd, copy only byte-identical intended artifacts into the package root, then remove the stray generated paths. Do not leave duplicate `tests/`, package modules, manifests, or skill folders outside the intended root.

## Archive hygiene

Do not create the archive inside the directory being archived; `tar` may report “file changed as we read it”. Write the archive to `/tmp` or another external path, then record its checksum in the package artifacts.

## Final report shape

For repeated continuations after completion, keep the reply short:

```text
Goal complete: yes. Останавливаюсь.
┈ STATE.md = COMPLETE
┈ FINAL_AUDIT.md has AUDIT_COMPLETE + SUPERGOAL_RUN_COMPLETE
┈ live actions remain BLOCKED_BY_APPROVAL
```
