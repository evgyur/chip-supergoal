# Request-wide deadline and ambiguous billing hardening

Use this reference when a SuperGoal phase hardens a multi-stage model/provider chain: proposer panel, judge, finalizer, verifier, or tool planner.

## Contract

- Start one request-level monotonic deadline before the first subcall. Every stage receives `min(per_call_timeout, remaining_request_time)`; never reset the wall-clock budget at stage boundaries.
- Keep one request-level planned-spend envelope. Reserve each dispatch before sending it and block stages that cannot fit inside the remaining envelope.
- Track subcalls separately as `requested`, `completed`, `cancelled`, `ambiguous`, and `billable`. A post-dispatch timeout is cancelled/ambiguous, not completed.
- Do not automatically retry timeout or HTTP 429 on billable/high-429 routes unless provider-backed idempotency plus cancellation/reconciliation proves duplicate-spend safety.
- Conservatively retain estimated billable units for an ambiguous post-dispatch timeout so an outer fallback cannot look like zero-cost success.
- Reconcile late provider receipts by stable subcall request ID. Duplicate receipts must stay visible but must not double bill.
- Open a request-local circuit after repeated 429, timeout, empty-output, or accounting anomalies. This is not a global provider-health substitute.

## Deterministic test pattern

`httpx` timeout arguments are not sufficient evidence under every transport. In particular, a custom or mock transport can ignore them. Wrap the dispatch coroutine in `asyncio.wait_for(..., timeout=remaining)` so the test exercises real cancellation semantics.

Required fault cases:

1. Two proposers run concurrently, then a slow judge gets only the remaining deadline and times out; total elapsed time remains bounded by the original request deadline.
2. An already exhausted deadline blocks dispatch entirely.
3. A stage whose planned units exceed the remaining spend envelope does not dispatch.
4. Timeout and 429 with retry count greater than one still produce one provider dispatch when idempotency/cancellation proof is absent.
5. Timeout records one requested, zero completed, one cancelled, one ambiguous, and non-zero conservative billable units.
6. Two anomalies open the request-local circuit before a third provider dispatch.
7. Late reconciliation is idempotent by request ID and exposes duplicate status.

## Review pitfalls

- A timeout result must not increment both `completed` and `cancelled`.
- Planned units and actual/estimated billable units are different ledgers; retain both.
- If legacy constructor-based tests intentionally preserve old retry behavior, keep that compatibility explicit. Parsed/default runtime configuration must remain fail-closed.
- Run mandatory focused tests, the complete suite, candidate-scoped lint, compile checks, diff checks, and secret scans before phase closure.
- If repository-wide lint is baseline-red on an unchanged line, record exact baseline evidence and run candidate-scoped lint. Do not silently fix unrelated baseline code or claim the broad command passed.
