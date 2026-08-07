# Transactional outbox and trading-control hardening

Use this reference during a SuperGoal execution phase that repairs transactional outbox ownership, kill switches, or ambiguous exchange attempts.

## Outbox ownership closure

1. Build one typed registry covering every literal producer topic and every scheduler-generated topic. Record owner, concrete consumer, idempotency scope, retry limit, and terminal/DLQ policy.
2. Scan producer code and compare it with the registry. Dynamic topic construction needs a fail-closed allowlist at the producer boundary. Include every public API alias in the scan: normalize aliases to the canonical owned topic internally, but preserve the documented public response contract. A route that returns `202 queued` must map to a real consumer or an explicit operator-notification workflow; do not silently convert an orphan producer into a no-op green path.
3. Inspect live outbox metadata read-only (`topic`, `status`, counts, attempt maxima, age). Never read or export payloads unless needed and approved.
4. A topic is closed only when one of these is true:
   - a fenced consumer exists and is included in runner, service unit, release build, installer, and packaged smoke; or
   - the producer rejects it before insert and user-facing API behavior is repaired explicitly.
5. Add a dry-run replay classifier for failed rows. Reuse the original row/idempotency key; do not create a second logical job. Trading/execution topics require exchange readback before any replay proposal.
6. Evidence should include the registry, orphan count, live status summary, retry/DLQ rules, dry-run proposals, targeted tests, and explicit `live mutations: zero` when no rollout occurred.

## Kill switch closure

A kill switch is not an admin queue label. In one transaction it should:

1. create or reuse an active scoped kill record;
2. pause affected active users;
3. enqueue risk-reducing close-all work per affected user with deterministic idempotency;
4. write an audit event and idempotent API response.

Execution must query the active kill state immediately before lease renewal/reservation/signing. The emergency close-all/control path remains separate so the kill switch blocks risk-increasing execution without blocking risk reduction. Prove ordering with a test that asserts no reserve/sign/transport call occurs after the guard raises.

## Ambiguous exchange attempt recovery

For `request sent, response lost`:

1. reserve an attempt with deterministic CLOID before signing;
2. on replay, never resend blindly;
3. call the exchange order-status/readback endpoint using user address + exact CLOID;
4. verify returned CLOID and parse terminal/resting/error state conservatively;
5. record `attempt.recovered_by_cloid` as a read-only exchange observation;
6. only continue execution finalization from the recovered result. If no exact order is found, remain fail-closed and escalate to reconciliation.

Do not invent an average fill price from a limit price. If order-status lacks the actual average, store it as unknown and let reconciliation repair notional/fee accounting.

## Verification ladder

- Focused unit RED → GREEN for each guard/recovery branch.
- Isolated PostgreSQL integration with zero skips for transaction, fencing, idempotency, and outbox effects.
- Targeted execution/control/reconciliation suite.
- Release build + packaged smoke for every new consumer/runner/service.
- Static + live read-only audit rerun after code changes.

Never treat broad `N passed, M skipped` output as proof of database behavior when the skipped integration suite can be exercised safely in an ephemeral local database.
