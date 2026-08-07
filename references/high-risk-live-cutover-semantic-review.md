# High-risk live cutover: semantic review checklist

Use this reference when a SuperGoal will activate production services, trading, payments, migrations, credentials, or another live authority boundary. It complements structural validation; it is not a task-specific runbook.

## 1. Review the exact sealed package

- Compile from the canonical contract; do not hand-edit generated views.
- Record the compiled `CONTRACT.json` SHA-256 before independent review.
- The reviewer must verify that exact hash before reading semantics.
- A PASS is usable only with `P0=0` and `P1=0`.
- If the contract changes, increment the contract revision when intent changed, recompile, and re-review. Never carry a PASS across a changed hash.
- Keep the review receipt outside the sealed package, hash-bound to the package. Do not mutate the package merely to embed the PASS.
- Run validators with `PYTHONDONTWRITEBYTECODE=1`; transient `__pycache__`/`.pyc` files can make a manifest-sealed package fail fileset validation.

## 2. Current implementation gaps may be planned, but every future control needs a producer

A command may depend on a script or field that P01 will implement. This is valid only when the plan declares:

1. the exact work item that creates it;
2. its direct deliverable path;
3. focused tests for the behavior;
4. the later command that consumes it;
5. the final verifier that binds its evidence.

Reject plans where a command consumes a manifest, review, rollback package, approval receipt, or verifier output that has no deterministic producer/materialization step.

## 3. Dirty follow-on baseline

For a dirty inherited worktree, capture before edits:

- exact HEAD;
- full binary patch bytes and SHA-256;
- porcelain-status SHA-256;
- complete changed-path set;
- privacy-safe writer inventories: classification and hashes, not raw argv, prompts, routes, chat IDs, or credentials.

The final reconciled commit must have hunk-accounting evidence for every original hunk. Ignore only explicitly controlled evidence directories when checking source cleanliness.

## 4. Tests must bind the sealed candidate

- Test receipts must come from JUnit testcase records, not quiet `pytest -q` stdout.
- Empty the invocation-owned JUnit directory before each run; stale XML must not satisfy renamed or missing tests.
- Bind every receipt to `candidateHead`, invocation ID, exact required testcase names, pass status, and zero required skips.
- Recreate receipts at the engineering, sealed-candidate, and final-audit gates; verify all bind the same HEAD.
- Include receipt hashes in the candidate seal and, for live work, in the production approval.

## 5. Single writer and attempt boundary

A read-only preflight check is not enough; another writer can start after it.

For a live attempt:

1. append one hash-chained `BEGIN` event;
2. durably arm a restart-surviving `PREPARED_ATTEMPT` reconciler;
3. invoke apply;
4. acquire the shared writer-authority lock as the first live-authority action;
5. consume approval with CAS;
6. append exactly one terminal `SUCCESS` or `FAILED` event.

All managed writer entrypoints must honor the same authority lock. Low-level apply must reject missing, reused, or unmatched operation IDs. Read-only writer/gap/approval preflights occur before `BEGIN` and are non-attempts; every failure after `BEGIN`, including lock/CAS failure, requires terminal failure plus recovery/no-effects evidence.

## 6. Approval and replay ordering

Before minting live approval:

- perform approval-free all-source retention-gap proof;
- freeze a receipt with observation time and max age.

Approval must bind that receipt hash/freshness plus candidate, release, test receipts, manifest, rollback package, reviewer, cohort/follower, risk cap, targets, expiry, nonce, and intended identity.

Before activation/order authority:

- close the execution fence if required;
- catch up all sources while execution remains disarmed;
- emit per-source forward-progress/no-cap/no-gap evidence;
- block activation if any source lacks retained history.

## 7. Durable failure closure

Do not rely on shell `if` branches alone for production recovery. Use one tested live orchestrator that owns apply → observe → complete/rollback/recover.

Required failure evidence:

- append-only attempt ledger;
- `FAILED ↔ recovery receipt` bijection;
- `SUCCESS ↔ sealed canary receipt` bijection;
- failure stage and source exit code;
- hashes of redacted stdout/stderr;
- fresh postcondition hash;
- no completion on rollback, no-signal, timeout, or dry-run.

The mandatory failure matrix should include lock failure, approval-CAS failure, BEGIN→lock crash, lock→CAS crash, install/fence/activation failure, observer timeout/defect, complete failure, rollback/recover failure, process death, and host restart. Early crash windows need real subprocess kill plus startup reconciliation, not only caught exceptions.

## 8. External outcome proof

For trading or another external side effect, internal DB rows alone are insufficient. Require independent provider readback that causally binds:

- source event;
- target order identity;
- positive fill;
- resulting position;
- actual protective stop semantics;
- same-window equity;
- explicit risk formula and cap.

For a linear perpetual stop-loss, verify trigger direction (long stop below fill, short stop above fill), causal protected size, finite Decimal arithmetic, positive equity, and `riskFraction <= approved cap`.

## 9. Final semantic gate

Before handoff, independently trace each blocking criterion:

`criterion → command → produced artifact → exact hash/input binding → independent verification → final audit`

Reject vacuous gates. Examples: an empty failure directory without an exhaustive attempt ledger, a same-HEAD claim that omits one receipt, or an approval that references an unbound/future artifact.
