# Live-drift-preserving rollout overlays

Use this when a verified canonical candidate must be deployed onto a production checkout that contains tracked or untracked live-private drift.

## Core rule

Never deploy the canonical candidate by checkout/reset/copying its whole tree when live state differs. A candidate can be correct against canonical `main` and still erase current product behavior, private gateway patches, untracked runtime modules, or local supervision choices.

## Safe sequence

1. **Freeze live preconditions read-only**
   - service/container identity and health;
   - live Git HEAD plus tracked-status hash and path list;
   - image/container digest;
   - state/DB generation hashes;
   - exact file hashes for every controlled rollout path.
2. **Capture only required live source**
   - stream `git diff --binary HEAD` locally for tracked drift;
   - copy only explicitly selected untracked source/tests needed to reproduce current behavior;
   - exclude `.env`, credentials, databases, logs, backups, user exports, and generated state.
3. **Build a live-derived baseline**
   - start from the live HEAD, apply the tracked patch, and add the selected untracked source only in an isolated worktree;
   - if the live repository is a partial/promisor clone and bundles omit blobs, do not hydrate or mutate production Git state without approval; use filesystem copies for the controlled paths instead.
4. **Overlay the accepted candidate selectively**
   - apply only accepted candidate file diffs;
   - resolve conflicts in favor of live product behavior plus the candidate's security/correctness invariant;
   - do not reintroduce canonical entrypoints or watchdogs that live intentionally removed;
   - reject unrelated compatibility/product changes from the candidate lineage.
5. **Test baseline and overlay under the same harness**
   - run focused security gates;
   - run the same full-suite command on the reconstructed live baseline and overlay;
   - compare failure details, not only failed node IDs or aggregate counts.
6. **Package a controlled-file rollout**
   - artifact contains exact target bytes only for controlled paths;
   - manifest records `before_sha256`, `after_sha256`, absent/present state, mode, owner, service, image, DB generation, and rollback source for every path;
   - execution first verifies every precondition hash, then backs up, atomically replaces, builds/loads the image, restarts one service, and runs identity/health/privacy checks;
   - any mismatch aborts before mutation.
7. **Roll one bot/service at a time**
   - verify and retain a receipt before starting the next;
   - rollback from the manifest-bound backup, never from an assumed Git branch.

## Stateful rollout-control pitfalls

### Bind approval without changing the approved manifest

If approval names a manifest hash, do not flip an `approved` field inside that manifest: the file hash changes and the approval no longer binds the applied bytes. Persist a separate mode-0600 approval receipt containing the exact manifest SHA, scope, order and approval text. The verifier must fail closed unless either the immutable manifest was already approved before hashing or a valid external receipt matches the full SHA.

### Verify before-state for pending units and after-state for completed units

A one-bot-at-a-time verifier cannot keep expecting every runtime's `before_sha256` after bot 1 succeeds. Before each later bot, load prior manifest-bound success receipts:

- completed bot with valid receipt → require `after_sha256` / deployed release marker;
- current and pending bots → require `before_sha256` / previous release pointer;
- stale, malformed or wrong-manifest receipt → fail closed.

This avoids both false aborts and accidental acceptance of an unreceipted partial rollout.

### Keep post-deploy probes stdin- and readiness-safe

- Commands that pipe Python through `docker exec ... python -` need `docker exec -i`; without stdin attachment Python exits with empty output and JSON parsing fails.
- `systemctl restart` plus a single immediate identity probe is race-sensitive. Poll bounded service readiness and identity, verify the service remains active after a short window, then run privacy/hash checks.
- Track a non-secret failure stage (`restart`, `identity`, `hashes`, `privacy`) and persist it in the failed receipt. Redacting the entire exception to only `RuntimeError` destroys root-cause evidence.
- On any red stage, stop the sequence, rollback, and verify restored before-state before retrying the same unit. Never advance to the next bot while the current unit is red.

## Conflict-resolution invariant

A three-way merge that chooses `theirs` wholesale is unsafe when `theirs` was built from canonical main and `ours` is live-private drift. Resolve by intent:

- retain live routing, audience, entrypoint, local integration, and private-patch behavior;
- add redaction, atomic-write, bounded-shutdown, credential-fingerprint, and container-boundary invariants;
- remove raw exception/body/token logging even when the live line is newer;
- add or update focused tests when an old source-string assertion intentionally referred to an unsafe log message.

## Evidence pitfall: same node, new regression

Set subtraction on failed pytest node IDs can miss a regression inside an already-failing test. Example: baseline and candidate both fail `test_contract`, but candidate adds a second missing invariant inside that same assertion list.

For baseline-red nodes owned or touched by the candidate, retain normalized assertion fingerprints or structured failure details and compare them. At minimum:

- rerun the exact node on baseline and candidate;
- extract structured missing-item/error-class data when available;
- flag any new missing item, exception class, or failure stage even if the node ID was already red.

## Large-file transfer pitfall

Do not reconstruct source from tool output subject to stdout caps. For large Git objects, stream directly to a file (`git show <rev>:<path> > target`) and immediately run syntax/size/hash checks. A successful tool call can still return truncated content and create a syntactically broken artifact if its captured stdout was used as the file body.
