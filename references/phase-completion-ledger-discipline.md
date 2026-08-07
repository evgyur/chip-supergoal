# Phase completion ledger discipline

Use when executing an existing `.supergoal/phases/phase-*.md` file, especially a file-first package with mutable state under `out/runtime/`.

## Pitfall

A phase can look complete because code, tests, or a report exists while the coordination ledger still points at the previous phase. A second common false-green is shell evidence that records only the exit status of the final command, hiding an earlier mandatory-command failure.

## Required closeout sequence

Before printing `SUPERGOAL_PHASE_DONE` or yielding:

1. **Run the exact mandatory command forms.**
   - Preserve `cmd1 && cmd2` semantics exactly.
   - Use `set -o pipefail` for pipelines.
   - If commands are run separately, capture and report every exit code; never let a later successful `git diff --check` overwrite an earlier failed verifier.
   - A nearby command or manual inspection is supporting evidence, not a substitute for the manifested command.
2. **Save direct evidence.**
   - RED output when using TDD;
   - focused and full-suite results;
   - probe/side-effect/privacy evidence when relevant;
   - artifact SHA-256 and the release/manifest SHA that the artifact was built from.
3. **Run the phase RPD review.** Record findings, mutations, holds, and verdict before closeout.
4. **Update the mutable ledger transactionally.** For file-first runtimes this means all of:
   - `TODO.md`: phase done with owner and compact evidence;
   - `STATUS.md`: next phase, next action, fresh verification, no invented blocker;
   - `CHECKS.md`: every criterion and mandatory command mapped to direct evidence;
   - `REVIEW.md`: phase RPD block;
   - `RUN_LOG.md`: append-only completion/failure-probe event;
   - `MEMORY.md`: only reusable task-local facts/decisions.
   Legacy packages may use `STATE.md` and reports instead; update the equivalent fields rather than maintaining two competing truths.
5. **Verify ledger coherence.** Re-read the files, run package/phase validators, and confirm exactly one next owner. Do not claim a phase done while its checklist is pending or the next phase is already being edited without a claim.

## Ledger mutation transport guard

Treat a multi-file patch result as non-atomic unless the tool explicitly proves every hunk succeeded. Large generated patches, compacted context, or copied tool previews can inject literal placeholders such as `...[truncated]` into state files or advance `STATUS.md` while `TODO.md` and `CHECKS.md` remain stale.

After every phase-boundary mutation:

1. Re-read `TODO.md`, `STATUS.md`, `CHECKS.md`, `REVIEW.md`, `RUN_LOG.md`, and the changed section of `MEMORY.md` from disk. Do not trust the patch preview.
2. Search the mutable runtime for literal corruption markers: `\[truncated\]`, `...`, unresolved template tokens, malformed headings, and duplicate phase claims. Interpret `...` narrowly so ordinary prose is not rejected.
3. Assert the transition tuple is coherent: previous phase `done`; next phase `in_progress`; `STATUS.active_todo` equals that next phase; the previous checks and mandatory commands are terminal; exactly one owner exists; `RUN_LOG.md` has completion then claim events in order.
4. If any hunk failed, stop implementation immediately. Repair the ledger one file at a time, re-read it, and only then mutate candidate code for the next phase. Never let a partially advanced `STATUS.md` stand while continuing work.
5. Keep inserted evidence lines compact. Put long hashes/reports in phase evidence files and reference them from the ledger instead of sending one oversized patch payload.

This guard is about durable state integrity, not a permanent claim that any patch tool is unreliable.

## Package-validator ABI discovery

Do not invoke a remembered validator flag. Run package-local `scripts/sgctl.py validate-package -h` first and use the exact exposed interface. Current v2/v3 packages accept the package root as a positional argument, for example:

```bash
python3 "$ROOT/scripts/sgctl.py" validate-package "$ROOT" --strict --format json
```

A failed guessed form such as `validate-package --package "$ROOT"` is not evidence about package validity; correct the invocation from `--help`, rerun, and retain only the successful exact command.

## Provenance freshness

A canary or render is evidence only for the release and project manifest it names. If a release manifest, schema-bound input, template hash, toolchain pin, or candidate commit changes afterward, invalidate the old provenance receipt. Safest path: regenerate the project and rerun the canary. If a phase permits a narrower proof, explicitly demonstrate that the artifact-producing inputs are unchanged and regenerate the binding receipt; never silently reuse the stale result.

## Failure-probe rule

When an exact gate fails:

1. record the failed criterion and unaffected evidence;
2. build a tight reproduction;
3. identify root cause before mutation;
4. apply one fix;
5. rerun the complete mandatory command, not only the narrowed probe.

Keep durable lessons about the fix pattern. Do not encode transient host setup as a permanent tool limitation.

## Forced turn/tool-cap closeout

If the runtime forces a turn end before the whole goal finishes:

- finish the current phase transaction if its evidence is complete;
- otherwise leave it honestly `in_progress` with the exact last verified gate;
- leave the next phase unclaimed;
- state `not-ready`, the completed phase range, the next concrete phase, and whether there is a real technical/approval blocker;
- do not call a turn/tool budget a product blocker, and do not emit `SUPERGOAL_RUN_COMPLETE`.

## Output pattern

The visible yield is compact: completion state, strongest evidence, exact next phase, and blocker status. Full goal completion still requires final audit, `AUDIT_COMPLETE`, and `SUPERGOAL_RUN_COMPLETE`.
