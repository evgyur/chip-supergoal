# Private corpus controller hardening

Use this when a SuperGoal phase freezes public development cases plus calibration/sealed cases held outside git.

## Authority and preflight

- Resolve the package root as `parent(LAUNCH_GOAL.md)` at execution time.
- Read every declared context file from that root and take phase authority only from `runtime/STATE.json`; `STATE.md` is a projection.
- Execute the Preflight commands **exactly as printed**. Do not infer or rename a subcommand. If a compound invocation stops on a mistaken command, run the exact omitted command and treat the mistaken invocation as failed evidence, not as satisfying preflight.

## Safe private-bundle migration

Never migrate sealed cases in place.

1. Create a permission-restricted backup outside the repository.
2. Build the complete replacement under a private staging directory.
3. Validate every staged case against the frozen JSON Schema.
4. Verify counts, strata, source composition, source-snapshot hashes, labels, outcomes, nonces, and permissions.
5. Swap staged directories/files into place only after all checks pass.
6. Keep the backup until the phase and final audit close.

An in-place per-case loop can leave a mixed v1/v2 corpus when a later case fails. Retrying such a loop may then lose controller-only labels already removed from earlier cases.

## Planner/controller separation

A case file may contain planner-visible input and controller grading truth, but controller-only labels, adjudicated outcomes, reviewer comments, private nonces, and sealed traces belong in separate private files.

Public commitment entries should expose only the frozen allowlist, normally:

```json
{"id":"opaque-id","content_sha256":"salted-commitment"}
```

Do not expose split or stratum when they can be derived from opaque IDs inside the controller.

## Commitments

Keep two hashes for private artifacts:

- `bytes_sha256`: raw file integrity, private only;
- `content_sha256`: domain-separated commitment using a private random nonce.

Example commitment preimage:

```text
<domain> NUL <nonce-bytes> NUL <canonical-artifact-bytes>
```

Store nonces only in the private controller. Aggregate commitments must bind the ordered case set, labels, outcomes, nonce projection, and fairness receipts. Use canonical JSON plus a trailing newline everywhere.

## Honest provenance

`source_class=public_repo` requires a real committed repository fixture. Bind each snapshot to a safe `git:` locator, embedded content, and SHA-256, then verify the embedded content equals the referenced file. Do not label synthetic prose as public-repository evidence.

Historical/adversarial source counts must be derived from private controller metadata and verified against the frozen policy; never infer them from public commitment IDs.

## Independent fairness receipts

Use two isolated reviewers that did not author cases and do not inspect candidate implementation.

Each reviewer writes:

- a detailed private receipt covering every case with per-case sufficiency, strategy-flexibility, distinguishing reason, verdict, case commitment, policy hash, and ordered-set hash;
- a public aggregate receipt with counts and hashes only.

The public aggregate must bind the private detailed receipt by SHA-256 without revealing private IDs, labels, comments, or paths. Verify distinct reviewer identities, complete case coverage, policy hash, ordered-set hash, both independence attestations, and all-pass aggregate verdict before closing the fairness gate.

## Shared-state delegation pitfall

Background reviewers may read shared files while the parent continues working. Once review is dispatched, do not regenerate or mutate the reviewed corpus or policy until those agents finish. If the corpus must change, invalidate the affected receipts and rerun only the affected review lane. Give parallel reviewers distinct output paths and verify every claimed file, hash, count, and permission after completion.

Do not delegate corpus repair and simultaneously edit the same schema/private root. A worker can otherwise overwrite or race the parent. Repair first, verify and back up, then dispatch read-only reviewers.

## Freeze semantics

- Create holdout manifests and policy freezes with exclusive creation (`O_EXCL`) or compare-identical reuse; never silently overwrite authority.
- Freeze transitive policy/schema references, not only top-level policy files.
- Run the private verifier from the public verifier while suppressing private stdout/stderr; surface only a generic failure and aggregate-safe evidence.
- Use `git ls-files --cached --others --exclude-standard` to reject private directories, private case bytes, or sealed IDs outside the one allowlisted commitment manifest.

## Minimum verification

Before phase close:

- public cases validate against the actual frozen JSON Schema;
- snapshot content hashes and repository locators verify;
- private verifier passes twice with identical aggregate commitments;
- two public and two private fairness receipts verify;
- source composition and all split/stratum counts match policy;
- post-freeze mutation tests cover both direct and transitive inputs;
- `git diff --check`, unit tests, package preflight, and CI pass;
- no sealed content, labels, nonces, reviewer detail, credentials, or private traces appear in git or user-visible output.
