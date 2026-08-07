# Nested package and preflight guardrails

Use this when a SuperGoal lives under `<repo>/.supergoal/<slug>/` instead of directly at `<repo>/.supergoal/`, or when assembling a plan-first package without `sgctl compile`.

## 1. Keep validator dependencies together

`validate-phase.sh` and `validate-loop-design.sh` are wrappers, not standalone validators. They resolve their package root and invoke:

- `scripts/sgctl.py`
- `lib/chip_supergoal/`

When copying validators into a generated package, copy those dependencies too. Verify from the package copy, not from the installed skill:

```bash
python3 "$SUPERGOAL_ROOT/scripts/sgctl.py" validate-loop-design "$SUPERGOAL_ROOT/LOOP_DESIGN.md" --instantiated
for f in "$SUPERGOAL_ROOT"/phases/phase-*.md; do
  bash "$SUPERGOAL_ROOT/scripts/validate-phase.sh" "$f"
done
```

A wrapper that only works because it reaches back into the installed skill is not a portable package.

## 2. Bind nested paths without self-replacement

The protocol template contains relative `.supergoal/...` paths. For a nested package, bind them to the actual `SUPERGOAL_ROOT` before dispatch.

Do **not** first insert an absolute path containing `.supergoal/` and then globally replace `.supergoal/`: the replacement will rewrite its own inserted path and corrupt it.

Safe options:

1. Render from explicit placeholders such as `{{SUPERGOAL_ROOT}}`.
2. Replace template-relative paths before inserting any absolute-root paragraph.
3. Use exact targeted replacements, then assert the expected root occurs and no malformed duplicate prefix exists.

Minimum launch checks:

```text
- exactly one SUPERGOAL_GOAL_BODY in LAUNCH_GOAL.md
- none in LOOP_DESIGN.md
- protocol references the actual package STATE/ROADMAP/phases/scripts
- phase count matches STATE and ROADMAP
- original dirty checkout boundary is explicit when a clean worktree is used
```

## 3. Distinguish strict and plan-first packages

`sgctl validate-package` expects compiler artifacts such as `CONTRACT.json` and `MANIFEST.json`.

- **Strict/compiler-built package:** generate with `sgctl compile`; run `validate-package --strict`.
- **Plan-first/manual package:** do not claim strict package validation. Run phase validation, instantiated loop validation, launch-contract checks, baseline commands and package-file checks. State this evidence honestly.

Do not create fake CONTRACT/MANIFEST files merely to silence the validator.

## 4. Treat ignored-artifact dependencies as baseline defects

A clean checkout verifier must not require stale files under ignored `.supergoal/out/`.

If preflight fails only because such an artifact is absent:

1. reproduce and record the exact dependency;
2. add a phase-1 repair that makes the verifier generate its fixture in a temporary directory or use a tracked fixture;
3. a copied ignored artifact may unblock planner preflight, but label it as seeded compatibility evidence, not proof that the verifier is self-contained;
4. final acceptance must rerun the verifier in a fresh checkout with no preseeded ignored artifacts.

## 5. Dirty checkout isolation

If the current checkout has unrelated changes, create a dedicated clean worktree/branch for the SuperGoal. Put the package in that worktree, record both statuses, and explicitly forbid reset/stage/commit/clean operations against the original checkout. Final audit must prove the unrelated dirty files are unchanged.

## 6. Git worktrees and monorepo recon

A linked Git worktree has a `.git` **file**, not a `.git` directory. Recon helpers must detect repository state with:

```bash
git rev-parse --is-inside-work-tree >/dev/null 2>&1
```

Do not use `[[ -d .git ]]`; it silently reports “not a git repo” in valid worktrees and drops branch/history evidence.

For monorepos, a missing root `package.json` or lockfile does not mean “no package manager”. Probe nested manifests to a bounded depth and record each package root separately. Repo-map “largest source files” must exclude binary/media/database/archive extensions; `wc -l` on MP4/PDF/ZIP/DB files creates fake complexity hotspots.

## 7. Stale audit baselines

When a remediation SuperGoal starts from an audit/report SHA older than current remote heads:

1. create the execution worktree from the current approved integration branch, not the stale audit checkout;
2. preserve the report as an input/regression checklist;
3. make phase 1 classify every finding as `confirmed`, `already-fixed`, `stale`, or `new` using current source/live evidence;
4. forbid implementation edits before that finding ledger exists;
5. record audit SHA, execution baseline SHA, current production SHA, and submodule SHAs separately;
6. execute every proposed mandatory command from the **canonical execution worktree**, not the stale audited checkout. A helper that exists only on the stale branch is not a valid phase-1 gate: replace it with baseline-neutral SHA/hash/source checks, or plan a tested port after the finding ledger proves it is still needed.

This avoids both fixing dead code and silently dropping still-live risks after branch drift.

## 8. Deterministic compiler checks without bytecode noise

Package validation can import package-local Python modules and materialize `__pycache__/` even when the immutable compiler output was deterministic. For compile-twice comparisons:

1. set `PYTHONDONTWRITEBYTECODE=1` for compile and validation;
2. compare two fresh compiled roots;
3. if a prior validator already created caches, remove only those known transient package-local caches or exclude `__pycache__`/`*.pyc` from the comparison after confirming strict manifest validation still passes;
4. never carry this exception over to a deployable release artifact, where bytecode presence should remain a hard integrity failure.

Do not report a deterministic-build failure based solely on validator-generated bytecode, and do not hide real manifested-file drift behind a broad exclusion.
