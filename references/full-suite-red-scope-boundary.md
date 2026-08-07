# Full-suite red vs scoped SuperGoal completion

Use this when a scoped SuperGoal (for example video/HLS, auth UX, one feature rail) has its own focused gates and beta/live proof, but the repository-wide test suite is still red in unrelated areas.

## Rule

Do not loop forever and do not silently widen the scope.

### Baseline before candidate work

Before replaying a handoff commit, reconciling live drift, or editing a candidate, run every immutable phase command that is practical on the untouched canonical baseline. At minimum run:

- the exact focused command from the phase spec;
- the canonical full-suite wrapper, with a bounded timeout and retained summary;
- import/collection checks for files the handoff replaces.

Record baseline failures separately from candidate-introduced failures. If untouched canonical `main` already has broad code/test lineage mismatch, stop candidate integration early: classify it as a source-lineage blocker instead of spending the phase repair budget porting unrelated compatibility commits. A handoff branch passing its own narrow tests is not evidence that it is compatible with current canonical main or current live-private drift.

Use the repair budget only for failures owned by the scoped patch. Hundreds of unrelated failures, missing exports across untouched modules, or a full-suite failure count that grows outside the candidate diff are evidence to quarantine the candidate and write `FAILURE_HANDOFF`, not an invitation to repair the repository.

### Sealed package state

A compiler-generated package with `MANIFEST.json` treats generated `STATE.md` as sealed bytes. Hand-editing it makes `validate-package` fail generated-drift/hash checks. Before execution, the package must declare one supported state mechanism:

1. a compiler/state command that updates the contract, re-renders `STATE.md`, and refreshes the manifest; or
2. an explicitly unsealed runtime sidecar outside the manifested package (for example `<project>/SUPERGOAL_RUNTIME_STATE.md`) that the launch body names as the execution state source.

Do not add `FAILURE_HANDOFF.md` inside a sealed package unless the compiler/manifest is refreshed. Keep failure evidence beside the package and point to it from the supported runtime state surface. Do not call post-execution manifest drift a package-validation success.

When the original roadmap includes a full-suite gate and the full suite is red after the scoped work is beta-proven:

1. Re-run the exact full-suite command once from the canonical workdir and save or name the log path.
2. Extract the exact failing files/tests and classify each failure as:
   - scoped/owned by the current SuperGoal;
   - non-owned branch/content/test drift;
   - approval-sensitive product/payment/security policy;
   - environment/setup.
3. Write a small classification artifact under the active `.supergoal/<name>/` root, e.g. `FAILURE_CLASSIFICATION.md`.
4. Update `STATE.md` and `AUDIT.md` with current counts, command evidence, and the classification artifact path.
5. If remaining failures are outside scope and include a product/payment/security policy decision, stop with `Goal complete: no` / `SUPERGOAL_RUN_COMPLETE: no` and name the required user decision.
6. Do not patch tests to match changed product behavior, or restore old behavior, when the failure is payment/product policy. Ask for the decision first.

## Differential-test evidence must understand collection failures

A simple `candidate_failed_nodes - baseline_failed_nodes` subtraction is wrong when canonical baseline could not collect a test file. Once the candidate repairs a missing import/export, tests in that file finally run; their failures are not automatically candidate regressions.

Use this evidence model:

1. Freeze baseline SHA, clean-tree proof, exact test inventory, focused result, and canonical wrapper result before integration.
2. Run `pytest --collect-only` on baseline and store **file paths only** for collection-blocked modules. Do not retain raw traceback/provider output in evidence.
3. Run the same probe on candidate. A baseline-blocked file that now collects is a resolved collection blocker.
4. Classify a candidate failed node as new only when its file was collectible on baseline and the exact node was outside the baseline failure envelope.
5. Candidate-added tests still count: if they fail, they are new failures.
6. Detect removed tests separately from the frozen baseline path inventory.
7. Preserve raw exit codes and normalized sets in the JSON receipt; aggregate counts alone are insufficient.

Collection repair is an improvement, not permission to hide failures. Report newly runnable but still-red files separately, then use focused ownership gates to decide whether they block the phase.

## Failed-node set subtraction can hide a new defect

An unchanged pytest node ID does not prove an unchanged failure. A baseline-red test may fail for one missing item while the candidate makes the same node fail for two missing items, a later stage, or a different exception. Comparing only `candidate_failed_nodes - baseline_failed_nodes` launders that regression.

For every baseline-red node that touches candidate-owned files:

1. rerun the exact node on baseline and candidate under the same environment;
2. compare normalized failure stage, exception class, and structured assertion details;
3. when assertions report a collection of missing contracts/items, compare those item sets directly;
4. treat new missing items or a later/deeper failure as candidate-owned until disproved;
5. record the qualification in the differential receipt instead of reporting only equal failed-node counts.

## Evidence-schema and source-extraction preflight

Before starting a long wrapper, run the exact receipt verifier against a tiny fixture or inspect every required key. Producer and verifier must agree on names such as `lineage_ok`, `candidate_root`, and `candidate_sha`; never lose a long test run to a one-line schema mismatch.

For large Git objects, extract only required AST functions or diff hunks inside the subprocess. Do not pass a megabyte-scale source through a capped tool result and patch from truncated output: truncation markers can become source text. Syntax-check immediately, and verify indentation plus decorators when transplanting class methods.

## Correct status language

Use precise split status:

```text
AUDIT_COMPLETE: yes, for <scoped area>
SUPERGOAL_RUN_COMPLETE: no, because full suite remains red outside scope
prod: not touched
blocker: <policy/scope decision>
```

This is not a generic failure. It is an audit handoff: the scoped deliverable may be beta-proven, while the broader branch is not merge/prod-ready.

## Pitfall

Bad:

```text
Video is done, but full suite is red. Continuing to fix all tests.
```

This silently expands a video SuperGoal into content, homepage, cursor, and payment policy work.

Better:

```text
Video/HLS focused tests and beta smoke are green. Full suite is red in 12 non-video files. I wrote FAILURE_CLASSIFICATION.md. The Tochka route failure is payment policy: route returns 410 by design while tests expect old QR creation. Need Chip's decision before changing behavior or tests.
```
