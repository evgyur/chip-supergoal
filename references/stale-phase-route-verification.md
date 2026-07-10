# Stale phase-plan correction: rebaseline before implementation

Use this when executing a SuperGoal phase that references an older finding, line number, page, command, route, datastore, runtime mode, or deployment rail.

## Core lesson

A phase file, review report, compacted handoff, or chat summary can be stale even when `.supergoal/STATE.md` looks current. Treat all four as navigation aids, not proof. Current source, raw command logs, Git identity, authenticated live readback, and durable evidence files outrank summaries.

## Required rebaseline before coding

For every inherited finding or phase:

1. Locate the current canonical code path and its tests. Classify named routes/modules as canonical, alias/redirect, deprecated, test-only, or removed.
2. Compare candidate Git, remote branches, and deployed release identities. Large commit divergence may still hide a small content delta, or the reverse; inspect both ancestry and content.
3. Verify live applicability before designing a migration or runtime fix. Read the active service mode/config safely (key names and non-secret values only), then confirm the relevant schema/table/function actually exists.
4. Reproduce suite counts and failing test names from raw logs. Never copy counts or failure names from a compacted summary into the baseline ledger without parsing the retained log.
5. Classify each original item as `confirmed`, `already-fixed`, `stale`, or `new equivalent`. `already-fixed` is a valid phase outcome when current source plus live privilege/behavior evidence proves it.
6. Preserve the phase intent, but do not resurrect a removed architecture merely to satisfy stale wording. Record the correction and evidence in the finding ledger and phase receipt.

## Applicability rule

Do not apply or test a database migration against production merely because a dormant optional code path has a defect. First prove whether that path is active. If production uses a different store/runtime, fix and test the optional path in the candidate, disclose that it is inactive live, and keep activation/migration as a separate reviewed action.

For transactional SQL, prefer a disposable database fixture:

- apply the real migration to an ephemeral PostgreSQL instance;
- exercise idempotency, injected mid-transaction failure, and concurrent calls;
- assert final row counts and balances;
- keep production readback read-only;
- never use real payments, grants, or entitlements as tests.

A migration containing a new grant can be shipped as inactive candidate code without claiming the grant is live. Applying it remains a distinct high-risk action.

## Examples

### Canonical route drift

- Stale instruction: “mirror `/payment_new`”.
- Current reality: `/payment_new` is redirect-only; `/payment` is canonical.
- Correct action: implement against `/payment`, retain the alias only as a compatibility surface, and test both.

### Removed multi-table write path

- Stale report: project applications need a new atomic RPC.
- Current reality: the candidate stores the complete application and cases in one row/INSERT, while live RLS and grants are already safe.
- Correct action: classify `already-fixed`, retain characterization and privilege proof, and do not add a needless SECURITY DEFINER function.

### Inactive optional datastore

- Confirmed code defect: an optional Supabase rental path performs sequential financial writes.
- Live reality: the service runs a file-backed store and the production database has no rental schema.
- Correct action: replace the optional path with one transactional RPC, validate it in disposable PostgreSQL with rollback/concurrency tests, and do not apply the dormant migration during routine app rollout.

## Baseline integrity check

Before `SUPERGOAL_PHASE_DONE` for a rebaseline phase, mechanically verify:

- every original finding ID appears exactly once;
- every classification uses the allowed status set;
- suite totals and failure names match raw logs;
- live SHA/runtime statements have authenticated receipts;
- no stale line reference is the sole evidence;
- phase/RPD review corrections are written back to `STATE.md` and the ledger.

This prevents fluent but false baselines from driving unnecessary or dangerous work.