# Quality-canary compiler hardening

Use when a SuperGoal phase adds an opt-in quality gate, typed command metadata, deterministic reports, or profile-dependent attestation hashes while legacy profiles must remain byte-compatible.

## Core sequence

1. Add the gate behind a new profile that extends the legacy base; do not mutate default profile behavior.
2. Define one closed gate schema and catalog every blocking finding under the existing diagnostic/invariant authority.
3. Keep command metadata additive. Optional fields must preserve **presence**, not merely values: an omitted legacy field and an explicit `null` can have different canonical-output meaning.
4. Recompute review lane and judge requirements from normalized risk/action/profile inputs. Reject stale policy/rubric versions, forged lane/reason/status, placeholder commands, unbound sources, weak rollback, and undeclared risky mutations.
5. Emit canonical UTF-8 JSON with sorted keys and a trailing newline. Static and dynamic tests must prove the quality runtime does not open network sockets.
6. Bind both the normalized plan subject and deterministic report with SHA-256.
7. Compile a positive canary package and validate the package manifest, not only isolated lint fixtures.
8. Re-run focused, determinism/security, full-unit, shell/native, and aggregate test commands before review.

## Normalize before sealing

An attestation hash over raw source is wrong when profile resolution injects delivery/default policy fields or canonical model conversion changes the projection.

Correct order:

1. parse the source contract;
2. resolve the selected profile;
3. canonicalize the resolved contract;
4. remove only the attestation from the plan-subject projection;
5. hash that normalized projection;
6. render the deterministic quality report without self-referential report-hash validation;
7. hash the report and write both hashes into the attestation;
8. validate and compile the now-sealed canonical contract.

A positive test must assert that the compiled contract's declared `report_sha256` equals the actual bytes of `reports/plan-quality.json`.

### Resolved-delivery drift gate

`load_contract()` / model round-trip may still be earlier than final compiler resolution. The compiler can inject profile-derived delivery fields such as `files`, `receipt_policy`, `review_pack_required`, `target`, or `transport`. If those fields appear only during compile, an attestation can be green against the source contract but stale against the compiled `CONTRACT.json`.

Therefore:

1. seal only after profile/default resolution, not merely raw-model normalization;
2. compile a disposable package;
3. run `quality-lint` against the **compiled** `CONTRACT.json`, not only the source contract;
4. if subject/report hashes drift, compare source vs compiled contracts after removing only the attestation;
5. add the resolved defaults to the canonical input or use the compiler's official resolve-before-seal API;
6. reseal, compile fresh, and require both source and compiled quality lint to be green.

Never patch the generated attestation by hand: it would detach `MANIFEST.json` and the rendered review files from the contract authority.

### Reviewer completion gate

A semantic attestation may say `semantic_judge_status: passed` only after every delegated reviewer has returned and all accepted findings have been applied. Dispatching reviewers is not review completion. If a package is otherwise ready while reviewers remain in flight, keep the attestation pending/required and do not deliver an RPD-complete verdict.

## Portable-resource inventory pitfall

If compiler validation reads a new policy, rubric, schema, or profile through the package-local no-follow reader, that resource must also be present in the sealed portable inventory and manifest. Otherwise package staging may fail with a misleading archive/special-file diagnostic against an ordinary JSON file.

When adding a quality resource, update together:

- portable runtime spec/profile inventory;
- compiler report generation;
- package validator expectations;
- release/inventory tests;
- positive canary compile test.

Do not "fix" this by bypassing the no-follow reader or weakening package validation.

## Backward-compatible typed commands

Adding fields directly to a dataclass can silently alter legacy canonical JSON because recursive serialization emits default `None`, empty arrays, or private presence metadata.

Use an explicit presence set captured during parsing. Serialization should:

- emit only fields present in the source;
- preserve explicit `null` when the canary schema requires it;
- omit the internal presence tracker;
- special-case commands in every renderer/canonicalizer that recursively walks dataclasses.

Prove both directions:

- a legacy contract round-trips byte-for-byte;
- a quality-canary command round-trips `cwd`, mutation class, availability dependencies, expected output, risk tags, and nullable waiver.

## Review lifecycle

Independent RPD/code review is a completion gate, not background decoration. Do not commit, push, transition phase authority, or claim review completion while delegated reviewers are still in flight.

If the host forces a yield before receipts arrive:

- keep the phase `EXECUTING`;
- record tests as passed but review as pending;
- leave changes staged but uncommitted;
- do not emit completion markers;
- resume by consuming the reviewer result, fixing findings, rerunning affected gates, and obtaining a post-fix review before commit.

Prefer durable review receipts in phase evidence over narrative claims that a reviewer was dispatched.