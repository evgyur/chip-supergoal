# Scoped candidate recovery when canonical tests are broadly red

Use when a narrow privacy/reliability candidate passes focused gates but the immutable repository wrapper fails across many unrelated subsystems.

## Required sequence

1. **Baseline before integration.** On untouched canonical `main`, run the exact focused phase command and the canonical wrapper with a bounded timeout. Persist counts and failing-file names separately from candidate results.
2. **Keep the first candidate quarantinable.** If conflict resolution accumulates broad compatibility code or test rewrites, move it aside and rebuild from clean canonical `main`; do not keep repairing an opaque merge.
3. **Restore only missing dependency surfaces.** Use `git log -S'<symbol>'` to identify the commit that introduced a test-required method. Prefer replaying the narrow source hunk; do not import an entire unrelated feature chain merely to make one filtered command green.
4. **Privacy behavior outranks stale log assertions.** When a scoped privacy change intentionally replaces raw exception/profile/message logging with metadata-only events, update only the directly corresponding tests to assert non-disclosure and event shape. Never rewrite unrelated product-policy tests to manufacture a pass.
5. **Run the exact focused gate, then the wrapper once.** Record the process handle, exit code, passed/failed/skipped counts, failed-file count, and collection/no-run count in a durable evidence artifact. Terminal scrollback alone is not final evidence.
6. **Prove pre-existing drift with a clean baseline probe.** Re-run representative failing modules in a detached clean worktree. Matching failures demonstrate non-owned branch/test drift, but do not convert a mandatory red wrapper into a pass.
7. **Classify and stop instead of widening scope.** Separate scoped/owned, non-owned canonical drift, policy-sensitive, and environment failures. If the phase contract requires a green canonical wrapper, the phase remains failed even when focused tests pass.
8. **Preserve production safety.** Do not deploy, push, restart, or advance dependent rollout phases while the mandatory gate is red. Re-run available no-live-mutation and backup-integrity checks before handoff.

## Sealed state guard

At executor startup, run package validation **before editing `STATE.md`**. If `STATE.md` is compiler-generated and manifested, never hand-edit it. Require either:

- a compiler-supported state update command that re-renders and refreshes the manifest; or
- a launch-declared runtime sidecar outside the sealed package.

If neither exists, write failure/classification artifacts beside the package and stop. Manually refreshing hashes would hide a package-contract defect.

## Failure handoff contents

Include:

- candidate/base SHA and branch;
- exact focused and wrapper commands/results;
- baseline-probe result;
- changed-file and commit counts;
- classification artifact path;
- package-validation status;
- explicit list of actions not performed;
- exact prerequisite for a new run: reconciled canonical source/test baseline and regenerated package with supported runtime state.
