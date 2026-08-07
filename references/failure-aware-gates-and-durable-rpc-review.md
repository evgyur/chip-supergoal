# Failure-Aware Gates and Durable RPC Review

Use this during SuperGoal implementation phases that must prove no new regressions or introduce leased inbox/outbox RPCs.

## Failure-aware baseline comparison

1. Freeze baseline SHA and test command before candidate edits.
2. Remove generated/ignored test artifacts from both worktrees before each run; clean Git status is not enough.
3. Run identical commands in separate baseline and candidate worktrees.
4. Compare normalized failed node IDs and collection-blocked files, not only exit codes/counts.
5. Rerun each candidate-only node at least twice in both worktrees.
6. Block deterministic regressions: candidate repeatedly fails while baseline repeatedly passes.
7. Record baseline-blocked files explicitly; do not claim their tests passed.
8. Persist privacy-safe evidence: commands, SHAs, timestamps, counts, normalized nodes, and output hashes—not raw private output.
9. Checkpoint long comparators before paired rechecks so a late error does not force a full rerun.

## Supabase/PostgREST RPC checks

- Match SQL return shape to the client contract. A dict-only RPC client needs an object such as `{ "updates": [...] }`; `RETURNS TABLE` arrives as an array.
- Pin every `SECURITY DEFINER` search path, preferably `pg_catalog, public`, and schema-qualify application tables.
- Revoke execute from `PUBLIC`; grant only the intended service role. RLS alone does not protect a security-definer RPC.
- Smoke-test the migration in ephemeral PostgreSQL using minimum predecessor schema, legacy rows, and replayed calls.
- Confirm: accept precedes acknowledge; expired leases recover; completed rows never reopen; private inbox payload is scrubbed after completion when no longer needed.

## Irreversible external effects

1. Lease an outbox record before provider calls.
2. Use a stable opaque idempotency key derived from the accepted event.
3. Treat 4xx as terminal according to policy.
4. Preserve the lease on timeout, transport failure, or 5xx because provider outcome is ambiguous.
5. Propagate retryable errors to the durable inbox processor. Never catch them and then mark the accepted update complete.
6. Retry after lease expiry with the same key; complete only on a definitive result.
