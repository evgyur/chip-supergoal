# Sealed eval corpus and policy-freeze design

Use this reference when a SuperGoal phase must create a public development corpus, private calibration/holdout cases, fairness receipts, frozen rubrics/promotion policies, or exact corpus-verifier commands.

## Authority boundaries

1. Keep full case envelopes split into `planner_input` and `controller_truth`. A planner receives only one released `planner_input`; hidden truth, tests, labels, condition identity, and commitment nonce remain controller-side.
2. Never embed fairness reviewer hashes inside the case they are intended to hash. That creates a self-hash cycle. Fairness receipts are separate artifacts bound to the case commitment.
3. Public non-public-case records contain only `id` and a content commitment. Put split/stratum/source metadata in a stable ID only when public verification must derive counts from IDs; otherwise admit that the public verifier cannot prove that distribution.
4. Use a domain-separated canonical JSON commitment over the private envelope containing a random private nonce. A plain unsalted hash of a guessable historical task permits confirmation attacks.
5. Public verification proves commitment integrity, counts, receipt shape, and absence of exposed content. It cannot prove that reviewers substantively reviewed private cases. Preserve this distinction in evidence wording.

## Minimal corpus invariants

- All case, requirement, assumption, risk, check, and strategy IDs are stable and unique.
- Every JSON authority uses `additionalProperties: false` and conditional validation for split/privacy, clarification-oracle, and strategy-flexibility states.
- Repository sources bind canonical remote, immutable commit/tree, and content hashes; moving branches are not snapshots.
- A flexible task accepts at least two valid strategy classes, and deterministic checks grade outcomes rather than an author-preferred implementation path.
- Calibration/sealed full cases, labels, reviewer comments, raw traces, and source paths are absent from tracked public files, logs, fixtures, and error rendering.
- Negative fixtures use synthetic IDs, never real sealed IDs or commitments.

## Fairness receipts

Use two separate reviewer receipts. Each public receipt binds:

- distinct reviewer ID/class;
- implementation/case-author independence attestations;
- fairness policy version/hash;
- exact ordered case commitment set hash;
- private detailed-review receipt hash;
- aggregate verdict.

For private cases, per-case public records remain `id` plus content hash. Detailed checklist answers and comments stay private. A controller-side verification receipt may close the semantic fairness gate; the public repository verifies only its commitment.

### Failed reviews are not attestations

Treat reviewer output and finalization output as different artifact classes:

- A detailed reviewer receipt may honestly contain per-case `fail` verdicts and an aggregate `fail`; keep it private and bind it to the frozen ordered commitment set.
- If the public aggregate schema deliberately permits only `pass`, do **not** emit a fake `pass` or a schema-invalid `fail`. Withhold the public aggregate receipt, report it as not issued, and leave the fairness gate open.
- A controller verifier that accepts only all-pass reviews is a finalization gate, not a validator for failed detailed receipts. Validate a failed detail receipt structurally with a reviewer-detail validator; do not rewrite failures merely to satisfy the finalizer.
- Before writing receipts, inspect existing target paths. Write canonical JSON atomically, hash the raw detailed-receipt bytes for aggregate binding, and set private directories/files to `0700`/`0600`.

### Dual-lane detail and aggregate receipts

When one reviewer covers both a private holdout set and a public development set, treat them as independently finalizable lanes:

- Build the private ordered-set commitment from the manifest-order canonical projection `[{"id", "content_sha256"}, ...]`; build the public ordered-set commitment from ID-sorted current public case files using each raw file SHA-256. Canonicalize with sorted keys, compact separators, UTF-8, and one terminal LF before hashing.
- A detailed receipt uses the same content-bound record shape in either lane: `id`, `content_sha256`, `sufficiently_specified`, `strategy_flexible`, `distinguishing_reason`, and `verdict`, plus reviewer identity, independence attestations, policy hash, ordered-set hash, and aggregate verdict.
- Hash the exact canonical detailed-receipt bytes after serialization; the aggregate receipt must bind that raw-byte hash, not a reconstructed object hash.
- Finalize lanes independently. A failed private detail receipt is preserved honestly and does not by itself prevent issuance of a passing public aggregate for an independently all-pass public detail set. Never promote a failed lane merely to satisfy a pass-only aggregate schema.
- Before writing, snapshot every reviewer authority input (policy, schemas, manifest, and case bytes), recompute immediately before atomic replacement, and abort on drift. After writing, independently verify canonical bytes, counts/order, commitments, aggregate derivation, schema, detail binding, permissions, and the public privacy boundary.
- Preserve reviewer independence by deriving receipt shape from frozen schemas/contracts rather than inspecting peer reviewers' substantive records, verdicts, or reasons.

### Atomic public receipt-pair construction

For a reviewer assigned one public detail receipt plus one public aggregate receipt:

1. Check lane occupancy by filename/count only; never inspect peer receipt contents. Refuse if either assigned target already exists.
2. Snapshot the exact policy, schemas, current receipt validators/finalizer, reference contract, and all ID-sorted public case bytes. If verifier code drifts, re-read its current exact envelope and binding rules before continuing; retain semantic conclusions only when case/policy bytes and fairness semantics are unchanged.
3. Read every case semantically. For templated corpora, use a compact packet containing task, authority-marked context, oracle, must/should/non-goal truth, seams, risks, checks, accepted strategies, metamorphic relation, raw file hash, and source locator. Independently prove each `public_repo` locator uses the canonical remote, an advertised immutable commit, a safe path, and `git show <commit>:<path>` content equal to the embedded snapshot.
4. Serialize the detailed receipt as sorted-key compact UTF-8 JSON with exactly one terminal LF and exact verifier keys. Preserve ID order, bind raw case-file hashes, derive aggregate verdict mechanically, and stop without a public aggregate if any case fails.
5. Install without overwrite. Write and `fsync` a same-directory temporary file, set final permissions, then publish with a no-replace primitive such as `renameat2(RENAME_NOREPLACE)` or a same-filesystem hard-link followed by temporary-file unlink. Plain `os.replace` is insufficient because it can overwrite a concurrently created reviewer target.
6. Hash the exact installed detailed bytes, construct the schema-valid aggregate from that hash, and publish it with the same no-replace discipline. Keep the public aggregate content-free: reviewer identity/class, independence attestations, policy/set/detail hashes, count, and verdict only.
7. Run a standalone target-only verifier: canonical bytes, exact keys/order/coverage, case hashes, source bindings, aggregate derivation, detail raw-byte binding, aggregate schema, `0700` private parent, `0600` detail, intended public mode, and absence of per-case text/reasons in the aggregate. Re-hash all authority inputs after writing. Do not run a controller finalizer or inspect/repair peer receipts unless assigned that role.

### Semantic source and strategy checks

Schema validity is necessary but not sufficient for fairness:

- For a case claiming `source_class: public_repo`, require repository semantics as well as a content hash: the privacy class must identify public repository content, the locator must resolve to an immutable committed fixture or immutable commit/tree, and the embedded content must equal that source. A synthetic URN with self-consistent bytes is not a public-repository snapshot.
- Do not accept `strategy_flexible: false` at face value. If materially equivalent sibling envelopes allow several safe strategies but one case admits only one named sequencing class without a unique constraint, mark it as single-strategy grading.
- Check class separation through the combined truth projection—musts, acceptable assumptions, forbidden actions, deterministic checks, rubric anchors, and private labels—not merely through schema cardinality.

### Review-time drift guard

Fairness receipts must bind one frozen authority snapshot. Record hashes of the policy, schemas, manifest, cases, and reviewer-relevant validators/tests at review start; recheck them immediately before receipt writing. If an authority file changes mid-review, abort the write and re-review the affected authority scope. Never race a controller that is still generating source fixtures or changing validation semantics.

Scope drift recovery precisely instead of either ignoring it or needlessly restarting everything:

- If policy, schema, manifest, or case bytes changed, regenerate all derived extracts and re-review every affected case.
- If only the reviewer validator/verifier changed, re-read its current receipt envelope, ordered-set formula, and acceptance rules; prove policy/schema/manifest/case hashes are unchanged, refresh the authority snapshot, and redo receipt construction/validation. Semantic case conclusions may be retained only when their source bytes are bit-identical and the verifier change did not alter fairness semantics.
- Never inspect peer reviewers' substantive receipts to resolve drift or infer the expected verdict. Check active-lane occupancy by filename/count only, and refuse to add a receipt when the lane is already full.

Treat reviewer-created semantic extracts, compact review packets, and normalized summaries as snapshot-bound artifacts too. If any source case or schema has a later hash/mtime than an extract, regenerate the extract and re-read the affected corpus before verdicts or receipts. For large templated corpora, a useful review packet keeps every case's task, planner-visible constraints, clarification oracle, must/should truth, decision seams, risks, deterministic checks, accepted strategy classes, and metamorphic relation while separately proving omitted boilerplate fields are byte-identical across cases. Do not hardcode locator syntax such as one `git:` prefix in an ad hoc reviewer; validate syntax from the frozen schema, then enforce repository provenance and immutable-content semantics as a separate check. Remove temporary extracts containing private case semantics before completion, leaving only the requested bound receipts.

For a canonical private detail receipt, derive the exact envelope from the current verifier rather than compatibility folklore. Write sorted-key compact UTF-8 JSON with exactly one terminal LF, preserve manifest case order, bind each exact manifest commitment, derive aggregate verdict mechanically from all per-case verdicts, refuse to overwrite an existing reviewer target, and use atomic replace under `0700`/`0600`. After writing, run a standalone content-free validation of canonical bytes, exact keys/order/coverage, commitments, aggregate derivation, authority hashes, and permissions. Do not run the controller finalizer or rewrite manifest/report state unless explicitly assigned the finalizer role; a stale-manifest diagnostic after a new receipt can be expected pending controller finalization, not evidence that the receipt should be altered.

## Outcome partition calibration

Freeze the taxonomy before candidate scoring. Do not add convenience classes later. Calibrate both class labels and causal episode partitions. A useful public synthetic pack includes enough non-miss examples for macro-F1 plus the preregistered minimum positive planner-miss manifestations, expert episodes, and multi-manifest episodes. Group only within task/seed using a frozen signature such as omission kind, normalized target IDs, and first-triggering-evidence hash.

## Immutable policy freeze

A `freeze-policy` command should:

1. validate direct policies and all transitively referenced schemas, controls, receipts, and calibration assets;
2. reject absolute paths, `..` escapes, final symlinks, and symlinked/junction ancestors for every read and write; resolve every authority under an explicit trusted root;
3. snapshot/hash every input, derive the lock, then recheck the same bytes immediately before publication so one lock cannot mix pre-drift hashes with post-drift thresholds;
4. write a deterministic canonical lock without wall-clock data;
5. publish through a same-directory temporary file, file `fsync`, atomic rename/replace, and parent-directory `fsync`; `O_EXCL` directly on the final path is exclusive but not crash-atomic because interruption can strand a truncated authority;
6. return success without rewriting when the same bundle is already frozen;
7. fail with a stable drift diagnostic if any direct or transitive byte changes;
8. never silently update the lock.

Add adversarial tests that pass an absolute transitive reference and a symlinked output parent. Both must fail without hashing the outside file, exposing its path in the public lock, or writing outside the authority root.

If the primary endpoint depends on later calibration evidence, freeze the selection algorithm and precedence now, and point to a future write-once endpoint-selection receipt. Do not mutate the already frozen promotion policy after calibration.

## Verifier privacy discipline

A public `verify-corpus` should use tracked-file inventory to reject private corpus directories, search occurrences of real non-public IDs outside allowlisted commitment artifacts, reject symlinks/path traversal, and ensure no tracked file equals private raw bytes. Errors and test failures report only stable code, case ID, and JSON pointer—not case text.

Do not compare a tracked file's raw SHA-256 to a nonce/domain-separated `content_sha256` commitment: those hash classes intentionally differ. After loading the controller manifest, compare public inventory against controller-only `bytes_sha256` values without rendering them, and have the private verifier scan for known labels, outcomes, nonces, reviewer details, and sensitive fragments that may not contain a complete case ID. Re-run the public inventory scan after private authority is loaded; otherwise the verifier may learn the needed raw hashes too late to use them.

Manifest-referenced public case, receipt, and transitive-policy paths need the same containment guard as inventory paths. Validate every resolved path before reading, not only paths returned by `git ls-files`.

For `public_repo` provenance, `git show <commit>:<path>` proves only that the object exists locally. Also prove the configured canonical remote URL and that the commit is reachable from an advertised/fetched canonical remote ref; otherwise a local-only commit can be mislabeled as canonical provenance.

## Private bundle operational pattern

When the deliverable itself is private and outside Git, use a self-verifying bundle:

```text
<private-root>/
  calibration/
  sealed/
  manifest.json
  verify_bundle.py
  validation_report.json
```

When the same main agent will later implement the candidate, preserve practical blindness by assigning private-case generation and review to an isolated controller/worker. Its user-visible handoff may contain only the private root, aggregate counts, aggregate commitments, and validation status—never tasks, truth sets, labels, reviewer reasoning, or per-case hashes paired with semantic descriptions. The main agent verifies paths, permissions, aggregate hashes, and the controller verifier without rendering private JSON into chat/tool output. Label reviewer identity honestly: isolated agent reviews are not human reviews, and two aliases emitted by one generator are not independent evidence unless the receipt records the real reviewer classes and independence boundary.

- Generate the exact ordered ID sequence mechanically from declared strata and split counts; validate order as well as uniqueness/totals.
- Enforce preregistered aggregate source composition in the private manifest/verification report. Do not expose per-case source metadata merely to make the public manifest easier to audit.
- Canonicalize JSON as UTF-8, sorted keys, compact separators, `ensure_ascii=false`, and exactly one terminal LF. Record whether each commitment hashes canonical value bytes (no LF) or canonical file bytes (one LF).
- Write atomically under `umask 077`; enforce directories `0700` and files `0600`.
- Keep synthetic source material inside each private case and bind every immutable synthetic URN to the canonical hash of that matching artifact, so snapshot hashes are recomputable rather than decorative.
- For private aggregate commitments, use explicit ordered projections: calibration labels, fairness receipts, calibration-only outcome partitions, and concatenated canonical case bytes in manifest order. Do not embed a manifest's own hash inside itself; report its file hash separately after writing.
- If commitments are exposed outside the private boundary or case material is guessable, retain the domain-separated private-nonce design above. Do not weaken confirmation-attack resistance merely for convenient public recomputation.
- Retain an independent package-local verifier. It must recompute per-case/source/reviewer/aggregate hashes, split visibility, schema/cardinality, metamorphic parents, calibration thresholds, privacy scans, and permissions.
- Run the verifier twice: first to create/refresh the deterministic validation report, then again so that report is itself covered by fileset/permission checks.
- Prove the private root is outside Git. If the working directory is not a repository, say so instead of fabricating a before/after diff claim.
- Human-facing completion stays blind-safe: paths, aggregate counts, status, and aggregate commitments only—never task text, truth sets, labels, reviewer reasoning, or per-case hashes paired with semantic descriptions.

## Blind multi-worker sequencing

When the main executor will later implement or score the candidate, enforce this order rather than letting workers race:

1. **Controller author** creates or migrates private envelopes, nonces, exact source composition, labels, partition assets, manifest, and verifier. Its report remains `awaiting_independent_review`; it must not create reviewer aliases or close its own fairness gate.
2. **Freeze case bytes first.** Run the controller verifier twice and bind the exact ordered case-commitment set. Do not launch reviewers while the controller is still mutating cases: every receipt would immediately become stale.
3. **Two separate reviewer workers** independently inspect the same frozen commitment set. Each writes its own detailed private receipt and a content-free aggregate receipt. Record the real reviewer class (`isolated-agent` or `human-expert`), case-author independence, candidate-implementation independence, policy hash, ordered commitment-set hash, detailed-receipt hash, case count, and verdict.
4. **Controller finalizer** verifies distinct receipt authors, complete case coverage, matching policy/set commitments, and receipt hashes. Only this finalizer may populate `fairness_receipts_sha256` and change private validation status to `pass`.
5. **Main executor stays blind.** It checks paths, permissions, counts, status, and aggregate hashes by running the private verifier; it does not render private envelopes or detailed reviewer comments into tool output or chat.

If source composition or schema authority changes after generation, return to step 1 and invalidate every old receipt. Never patch public commitments around stale private bytes.

## Recovery patterns learned from live corpus migrations

### Atomic private migration

- Never rewrite the canonical sealed corpus case-by-case. Copy the current private root to a permission-preserving backup outside Git, build the replacement under a `0700` staging directory, validate every staged case and aggregate commitment, then swap complete directories/files into place.
- A failed migration must leave the old case set and manifest authoritative. Do not let an early successful file write create a mixed v1/v2 root.
- Keep expert labels and outcome partitions in separate controller-only files when the general case schema does not need them. Do not weaken a public schema with untyped private fields merely to fit controller assets.
- After the swap, run the finalizing verifier once and the read-only verifier again so the refreshed report and permissions are themselves checked.

### Commit public fixtures before generating reviewable cases

For `source_class=public_repo`, use an immutable two-commit sequence: first commit the minimal public source fixtures; then generate cases whose locators bind canonical remote + that 40-character commit + repository path, and verify `git show <commit>:<path>` equals the embedded content and SHA-256. Freeze those case bytes before launching reviewers. Any later source, schema, generator, locator, or case change invalidates all receipts over the old ordered commitment set.

### Reviewer disagreement and honest pending state

- Aggregate a failed review without rendering sealed IDs, case text, labels, or comments into the main-agent context.
- Check the finding against the exact frozen rule. `minimum_valid_strategies_when_flexible=2` does not make every `strategy_flexible=false` case fail automatically; it still requires proof that the constrained case is outcome-graded and does not encode an unjustified author preference.
- Treat repeated independent findings against the same cohort as a corpus-quality signal, not reviewer noise. If two reviewers independently identify the same unjustified single-strategy pattern, repair that cohort even when a permissive cardinality rule could be read as allowing it.
- If a reviewer misapplied policy, preserve the failed detail receipt under a private/rejected audit path outside the active receipt glob and dispatch a fresh independent reviewer with the exact rule clarified. Never relabel the failed receipt as passing.
- If the finding is valid, return to controller authoring, change the cases, recompute commitments, invalidate every stale receipt, and restart both reviews. A passing receipt over pre-repair bytes is stale even when its reviewer never inspected the changed field explicitly.
- The finalizer must accept zero or one valid receipt as honest `awaiting_independent_review`, accept exactly two distinct complete passing receipts as `pass`, and reject failed or excess receipts in the active set.

### Reviewer lifecycle across tool turns

Background reviewer workers are not durable evidence until their receipt or returned result exists. Do not dispatch reviewers and immediately emit `SUPERGOAL_TURN_YIELD`: ending the turn/session can discard unfinished workers and create the illusion of reviews still running.

1. Freeze every reviewer authority input before dispatch: cases, policy, schemas, source locators, generator output, manifest projection, and receipt envelope.
2. Dispatch independent reviewers, then continue only work that cannot alter those inputs—full-suite tests, remote reachability proof, evidence-shape review, or unrelated read-only audit.
3. Do not regenerate cases, schemas, locators, or policy while a reviewer is active. If an authority mutation becomes necessary, let the active result become rejected/stale evidence and restart the affected reviews from the new commitment set.
4. Before yielding, require a verifiable durable artifact: expected receipt path, exact raw hash, or completed reviewer result. If the host forces a yield first, report the lane as `awaiting_independent_review`; on continuation, inspect active receipts and launch fresh workers for missing lanes rather than assuming prior delegations survived.
5. A public aggregate must bind a detailed receipt whose internal reviewer ID matches the aggregate reviewer ID, whose case order/commitments match the current set, and whose mechanically derived verdict is pass. Merely proving that some private detail hash exists is insufficient and permits cross-reviewer or stale-detail substitution.
6. Keep only the current two active receipt pairs in finalizer globs. Move superseded but audit-worthy details/aggregates to a rejected archive before freezing the holdout manifest.

## Review pitfalls

- Duplicate booleans such as `strategy_flexible` in case and fairness blocks create split authority.
- Untyped `expert_labels` or `outcome_partition_labels` fields in a general public-case schema invite leakage.
- Hashing fairness metadata as part of the content it attests creates a cycle. Define an explicit reviewed-content projection that excludes fairness and private labels/outcomes, or keep receipts separate.
- A validator that writes `validation_report.json` only after checking permissions has not yet checked its own output; rerun it.
- A policy named for plan quality that omits deterministic semantic-review lane/judge routing is incomplete even if it contains corpus statistics.
- Exact phase commands must be executed verbatim against the current checkout during review; missing commands/tests are evidence of incomplete implementation, not a design verdict. Do not count `PYTHONPATH=... <command>`, a wrapper, or a broader aggregate runner as proof for a contract that declares plain `<command>`. If the literal unittest command imports only because another runner injects `PYTHONPATH`, make the test/package bootstrap self-contained or correct the declared command, then rerun the literal command.
- When a new schema/test validator adds a dependency, update the pinned test requirements and any release-engineering test that intentionally asserts the exact dependency file in the same change. Then run both the focused gate and the repository-native full suite.
- After public source fixtures are committed and pushed, prove the immutable commit exists on the canonical remote before generating reviewable locators. After receipt finalization and policy freeze, regenerate deterministic public cases once, compare aggregate hashes, and rerun corpus verification plus idempotent freeze to prove no hidden generator drift.
- Concurrently appearing untracked artifacts are live drift. Inspect and report them, but do not treat them as baseline authority or overwrite them during a read-only review.
