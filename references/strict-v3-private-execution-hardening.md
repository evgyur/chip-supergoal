# Strict v3 private-data execution hardening

Use this reference when a compiled strict-v3 SuperGoal executes private-corpus, append-only-ledger, Telegram readback, or other privacy-sensitive phases.

## 1. Runtime state transitions are an ordered protocol

Do not jump directly from `COMPILED` to `RUNNING`. Advance the lifecycle through the legal pre-run states exposed by the package runtime, then update the active phase in a same-lifecycle transition.

Typical strict-v3 sequence:

1. `COMPILED → PLAN_REVIEWED`
2. `PLAN_REVIEWED → PREFLIGHT_GREEN`
3. `PREFLIGHT_GREEN → READY_TO_DISPATCH`
4. `READY_TO_DISPATCH → RUNNING`
5. same-lifecycle update: set phase status/attempt

`attempt` changes belong to a same-lifecycle update. Phase completion is normally represented by `EXECUTING → VERIFYING → COMPLETE`, then a same-lifecycle move to the next phase. Do not assume a package exposes `audit-phase`; some strict runtimes expose only the final `audit` command and require an auditing lifecycle/audit round at the end.

Before scripting transitions, run the package-local `sgctl ... --help` and inspect the package-local runtime state machine. Never infer commands from an older installed skill.

## 2. Evidence records must match the compiled verifier contract exactly

For every criterion:

- copy the exact command string from compiled `CONTRACT.json`;
- use the verifier type expected by that criterion;
- omit `assertion` when `expected_assertion` is null;
- use only RPD focus labels and policy labels declared by the compiled policy;
- bind `goal_id`, contract revision, and the current compiled contract SHA;
- append corrected/fresher evidence after hardening rather than rewriting old evidence.

Approval and review-delivery evidence are phase-scoped runtime evidence. Record them only when the current lifecycle/phase accepts mutable evidence; a `COMPILED` package may reject records because phase/lifecycle binding is not yet valid.

A command that once passed before its verifier was hardened is not fresh implementation proof. Rerun the exact command after the final mutation and append a newer evidence record.

## 3. Private baselines are explicit dependency artifacts

Never assume one baseline JSON embeds another. If P01 emits separate artifacts such as:

- source/file registry;
- Telegram authority/latest-message baseline;
- cron baseline;
- candidate seeding record;
- privacy contract;

then later phases must declare and validate each artifact they consume. Before writing a downstream tool, inspect the actual P01 artifact shape and add explicit CLI arguments for split artifacts. A downstream `registry_authority_mismatch` caused by looking for Telegram data inside the source registry is a contract-wiring defect, not evidence that the live authority changed.

Bind each baseline by fixed path, expected top-level keys, authority IDs, owner/mode, and hash. Reject caller-controlled roots or IDs that can redefine the trust boundary.

## 4. Seed only controlled rollout files

A candidate root is not a reason to copy an entire live skill/repository tree. Full-tree copies can:

- follow unrelated symlinks;
- import private or stale files into the candidate;
- blur the rollout manifest;
- make rollback ancestry unverifiable.

Seed only declared controlled paths from exact live bytes. Record for each path:

- live/candidate/seed-source path;
- existence and kind;
- SHA-256;
- mode, UID/GID, owner/group;
- Git tracked state and file-scoped patch hash when applicable;
- explicit ancestor source for renamed/new-from-old files.

Support files used only for candidate tests must be marked as test-harness inputs and excluded from the live rollout manifest.

## 5. Private filesystem verification must be descriptor-relative

Path-string checks plus `Path.resolve()`, `exists()`, `stat()`, `copy2()`, or `shutil.copytree()` are insufficient for hostile or race-sensitive private roots.

For canonical/staging/private-event paths:

1. walk every directory component with `openat(..., O_DIRECTORY | O_NOFOLLOW)`;
2. verify owner and exact mode through `fstat` on the open descriptor;
3. open files relative to the pinned parent descriptor with `O_NOFOLLOW`;
4. require regular files, UID ownership, and mode `0600`;
5. require directories to be UID-owned and mode `0700`;
6. fsync newly created files and their parent directory;
7. reject symlinked leaves and intermediate components;
8. keep reset/delete helpers descriptor-relative and restricted to a dedicated fixture namespace.

For atomic append-only writes, create a unique temp file with `O_EXCL`, fsync it, link/create the final name without overwrite, fsync the event directory, and then remove/fsync the temp residue. Conflicting duplicate IDs must never overwrite prior bytes. Identical canonical bytes may be idempotent if the contract says so.

Crash residues need an authenticated filename/content binding, a read-only classifier, and an explicit recovery command. Verification may report aggregate residue counts/hashes, but must never print event IDs or raw bodies.

## 6. Content-free means IDs can also be sensitive

Do not print raw captions, URLs, corrections, Telegram payloads, event IDs, chain IDs, or low-entropy identifiers. Emit:

- counts;
- fixed enum distributions;
- content-derived aggregate fingerprints;
- boolean gate results;
- redacted error codes.

Hashing a low-entropy ID is not automatically safe because it can be brute-forced. Prefer a fingerprint bound to the full canonical event or a keyed/nonce-salted commitment when public verification needs an identifier.

Keep raw private fetch-back snapshots in a `0700/0600` staging area, consume them with no-follow descriptor-relative reads, append the immutable ledger events, and delete/fsync the ephemeral file only after durable event writes succeed.

## 7. Intent must precede transport; verification must follow exact readback

For preview/delivery instrumentation:

1. append `preview_send_intent` and persist chain/parent state before network mutation;
2. on transport failure, leave only the immutable intent;
3. after ChipCR identity, canonical-chat, message-ID, entity/media, truncation, and fetch-back verification pass, append `preview_sent`;
4. append a child `preview_fetched` bound to exact message IDs and fetch-back hashes/body;
5. record explicit corrections as parent events and observed in-place edits as `actor=unknown` until attribution is proven;
6. repeated content/media hashes are delivery duplicates in the same chain, not editorial revisions.

Sanitize both success output and failure paths. Exceptions from APIs often contain raw payloads; CLI stderr should expose a stable error code, while raw diagnostics stay only in protected local state when required.

## 8. Mandatory test commands must prove that tests actually ran

`python -m unittest discover` does not execute pytest-style free functions. A zero-test run is a failure even if the process wrapper looks green.

Prefer one of these:

- compile the mandatory command with the repository's real runner (`pytest` for pytest-style tests);
- add real `unittest.TestCase` characterization tests;
- when an immutable contract forces `unittest discover`, add a candidate-only bridge that invokes the existing zero-argument guard functions and handles only explicitly known fixtures.

The final evidence must show a positive executed-test count. Test-harness bridge/support files are not live rollout files unless the manifest explicitly includes them.

## 9. Review loop

For high-risk private phases, run independent static review without reading raw fixture/event bodies. Focus the reviewer on trust anchors, symlink/race safety, crash durability, redaction, causal matching, and fail-closed integration.

Treat every blocking review finding as a mutation request, rerun mandatory commands, and review again until PASS. Store only the content-free review verdict/report in package evidence; do not paste raw private corpus into prompts or subagents.
