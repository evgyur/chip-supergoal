# Full-suite red vs scoped SuperGoal completion

Use this when a scoped SuperGoal (for example video/HLS, auth UX, one feature rail) has its own focused gates and beta/live proof, but the repository-wide test suite is still red in unrelated areas.

## Rule

Do not loop forever and do not silently widen the scope.

When the original roadmap includes a full-suite gate and the full suite is red after the scoped work is beta-proven:

1. Re-run the exact full-suite command once from the canonical workdir and save or name the log path.
2. Extract the exact failing files/tests and classify each failure as:
   - scoped/owned by the current SuperGoal;
   - non-owned branch/content/test drift;
   - approval-sensitive product/payment/security policy;
   - environment/setup.
3. Write a small classification artifact under the active `.supergoal/<name>/` root, e.g. `FAILURE_CLASSIFICATION.md`.
4. Record current counts, command evidence, and the classification path through package-local evidence/state commands; do not patch `STATE.md` or invent an `AUDIT.md` authority.
5. If remaining failures are outside scope and include a product/payment/security policy decision, stop with `Goal complete: no` / `SUPERGOAL_RUN_COMPLETE: no` and name the required user decision.
6. Do not patch tests to match changed product behavior, or restore old behavior, when the failure is payment/product policy. Ask for the decision first.

## Correct status language

Use precise split status:

```text
AUDIT_COMPLETE: yes, for <scoped area>
SUPERGOAL_RUN_COMPLETE: no, because full suite remains red outside scope
prod: not touched
blocker: <policy/scope decision>
```

This is not a generic failure. It is an audit handoff: the scoped deliverable may be beta-proven, while the broader branch is not merge/prod-ready.
Do not run `finalize` or claim successful `python scripts/sgctl.py validate-terminal`;
no `reports/terminal-record.txt` is authorized while the declared full-suite
criterion remains red.

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
