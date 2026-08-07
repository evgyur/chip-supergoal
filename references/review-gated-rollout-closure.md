# Review-gated rollout closure

Use this reference when a SuperGoal prepares an exact production-adjacent rollout behind a manifest-bound human approval. It applies to private-data, Telegram, cron, dirty-checkout, append-only, and recovery-sensitive work.

## Closure order

1. Build an immutable manifest from the live baseline and candidate. Bind every operation to exact source/destination paths, before/after hashes, mode, UID/GID, action, inverse, and patch digest.
2. Keep approval artifacts non-authoritative until the real request message ID is known. Authority must come from a fresh Telegram readback, not a local projection alone.
3. Run the rollback and process-death matrix against isolated adapters. The matrix and production recovery command must share the same recovery decision function; a synthetic matrix with different semantics is not evidence.
4. Run strict no-effect verification immediately after refreshing volatile baselines. Bind the receipt to the manifest SHA, baseline artifact SHAs, and content-free readback digests.
5. Run an independent reject-first review using absolute file paths and enough turns to inspect every artifact. Require an explicit terminal PASS/REJECT marker and preserve only the final reviewer answer, not CLI progress output.
6. Record phase evidence through the package-local runtime controller, then perform the legal state transition. A report PASS does not close the phase by itself.
7. Stop at the approval gate. Do not activate, edit cron, or send a canary until approval is bound to the exact manifest SHA.

## Telegram approval and send readback

Validate the approval with a fresh source readback before any mutation:

- exact actor identity;
- exact private chat;
- exact approval message ID and request reply target;
- exact phrase or phrase hash;
- request/approval timestamps inside the validity window;
- manifest SHA and candidate hash;
- replay/consumption state.

After sending an approval-consumption receipt or private canary, fetch that exact message and verify message ID, chat endpoint, reply target, runtime sender identity, exact text/hash, and timestamp before advancing the transaction. Storing a digest of an unvalidated response is not proof.

## Recovery semantics

- Set the mutation/recovery-required flag before entering a multi-file apply loop.
- Verify both files and cron after forward apply and after rollback.
- Treat absence and symlink as different states; strict poststate includes regular-file type, hash, mode, UID, and GID.
- Create canonical stage directories through an already `O_NOFOLLOW`-opened parent `dir_fd`; acquire the transaction lock with `O_EXCL`.
- If a private canary was sent and fetched successfully, recovery should verify and finish the existing transaction without resending. If strict verification fails, perform the declared rollback and leave an honest recovery-required or rolled-back terminal state.
- Never claim `rolled_back` when cron inverse/readback or file poststate failed.

## Volatile Telegram baseline

A Telegram control chat can change while the executor is running. Refresh the baseline immediately before the strict no-effect check and run the check in the same bounded command window. Do not weaken `expect-no-live-change` merely to accommodate a stale baseline. If operational chat traffic is intentionally allowed, encode that exception explicitly and detect forbidden rollout signatures separately.

## Package-local runtime and journal gate

Do not assume the controller lives at repository-root `scripts/sgctl.py` or in another SuperGoal checkout. Resolve and use the package-local executable runtime, normally:

```bash
python3 .supergoal/scripts/sgctl.py record-evidence . --input <record.json>
python3 .supergoal/scripts/sgctl.py state-transition . --expected-revision <N> --phase-status VERIFIED
```

Before creating or recording closure evidence:

1. inspect `runtime/STATE.json`, `runtime/events.jsonl`, and the canonical evidence ledger;
2. verify the state journal is non-empty and internally consistent;
3. verify the expected state revision immediately before transition;
4. if the journal is empty/corrupt, stop phase closure and use the package's documented recovery/migration path; do not hand-edit `STATE.json`, borrow a controller from another checkout, or claim the phase closed;
5. after recording, read back the evidence ledger and state transition.

Evidence files written to disk but rejected by `record-evidence` are unregistered candidates, not canonical evidence.

## Independent review hygiene

- Give the reviewer absolute paths, especially for hidden `.supergoal/` files.
- Use sufficient tool turns; a one-turn reviewer that spends its only turn loading context is not an independent review.
- Ask for a unique final heading and terminal verdict. Extract the last occurrence of that heading so an echoed prompt cannot be mistaken for the review.
- A reviewer failure caused by an inaccessible model/provider should be retried with another independent session. Preserve the successful final review only.
- A PASS is advisory until mandatory commands, evidence registration, and the state transition all succeed.

## Closure checklist

- [ ] Exact operations and inverses validated independently.
- [ ] No whole-tree replacement or unrelated dirty-file mutation.
- [ ] Cron changes use the existing job edit adapter only.
- [ ] Approval and outgoing Telegram messages use authoritative fetchback.
- [ ] Crash matrix covers every stage and every file boundary.
- [ ] Matrix recovery and production recovery share policy.
- [ ] No-effect receipt binds manifest, baselines, and readbacks.
- [ ] Independent review has no open P0/P1.
- [ ] Runtime journal is healthy.
- [ ] Evidence is canonically registered.
- [ ] State transition is read back as VERIFIED.
- [ ] Live activation remains blocked until manifest-bound approval.
