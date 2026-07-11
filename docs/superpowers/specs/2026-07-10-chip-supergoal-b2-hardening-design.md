# Chip SuperGoal B2 Hardening Design

## Status

Approved for implementation on 2026-07-10 after an RPD review. The selected approach is a pragmatic hardening of contract v3, not a v4 rewrite.

## Problem

The repository reports a green Ubuntu pipeline while several executable contracts remain fail-open or disconnected:

- compilation can bypass semantic, profile, and risk-policy validation;
- the generated package is not self-contained even though its protocol invokes package-local helpers;
- generated Markdown omits execution-significant contract data;
- runtime state, evidence, audit, and terminal-marker authority are not connected to the compiler or CLI;
- archive creation can write two entries named `MANIFEST.json`;
- the implementation assumes POSIX locking, Bash, LF checkouts, and POSIX path syntax;
- CI has no native Windows gate.

The hardening must eliminate these classes of failure without changing the public contract version or removing existing CLI commands.

## Goals

1. Make compilation and package validation fail closed for schema, semantic graph, profile, policy, and research errors.
2. Emit a relocatable, self-contained package whose executor-facing views preserve all execution-significant contract data.
3. Establish one machine authority for runtime state and evidence-backed completion.
4. Support the documented Python workflows natively on Windows and Linux.
5. Produce deterministic, path-safe archives without manifest collisions.
6. Prove the result with negative regressions, native Windows tests, Linux tests, fresh-clone smoke tests, privacy checks, and GitHub Actions.

## Non-goals

- Contract schema or protocol version 4.
- A new agent scheduler or replacement for Hermes GoalManager.
- Requiring Bash on Windows.
- Accepting previously malformed packages merely because an older compiler produced them. They must be recompiled from their v3 contract.
- Adding external runtime dependencies when the Python standard library is sufficient.

## Architecture

### 1. Canonical validation pipeline

All public entry points use one ordered service:

```text
load JSON
-> parse strict v3 model
-> graph and identifier semantics
-> resolve profile inheritance
-> validate risk-policy declarations
-> validate research gate
-> compile canonical artifacts
-> seal immutable inventory
-> validate the emitted package
```

`validate-contract`, `compile`, `compile_contract_file()`, and `validate-package` must not maintain separate interpretations of validity. Compilation raises a structured validation error containing the same diagnostic codes returned by `validate-contract`. The CLI prints those diagnostics and exits non-zero.

Profile resolution deep-merges `base` and the selected profile, rejects missing profiles and inheritance cycles, and supplies delivery/privacy defaults without mutating the caller's source object. The emitted `CONTRACT.json` is the canonical **resolved execution contract**. It contains applied profile defaults and, for `public-clean`, redacted source locators; the unredacted input is never copied into the package. `MANIFEST.json` records only `source_contract_sha256` for provenance. Runtime state, events, evidence, and audit bind to the SHA-256 of the canonical emitted `CONTRACT.json` bytes plus its retained `contract_revision`, never to the source hash. Package validation reapplies package-local profile rules idempotently and verifies those exact emitted bytes.

`public-clean` replaces private locators with the literal `[redacted]`, omits private-only delivery/operator fields, and rejects a contract when removing a private field would make an executable command, deliverable, or approval ambiguous. Risk policy enforcement has two stages:

- compile time: known tags, required RPD focus, required approval class, and rollback declaration;
- audit time: `mandatory_evidence` records for every active risk tag.

### 2. Sealed plan and mutable runtime

A compiled package contains two explicitly different planes.

**Sealed plane**

- `CONTRACT.json`;
- `THINKING.md`, optional `RESEARCH.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `PROTOCOL.md`, `LAUNCH_GOAL.md`, phase specifications;
- package-local Python library, `scripts/sgctl.py`, policy, profiles, templates, and compatibility wrappers;
- `MANIFEST.json` with canonical byte hashes and modes for immutable artifacts.

**Mutable plane**

- `STATE.md` as a human projection;
- `runtime/STATE.json` as the state authority;
- `runtime/events.jsonl` as the revision/hash chain;
- `runtime/evidence.json` and final-audit outputs;
- delivery receipts created during execution.

`MANIFEST.json` uses manifest version `1.1` and contains an exact `mutable_paths` registry. No glob or arbitrary `out/` exception is permitted:

| Path | Required | Validation |
|---|---:|---|
| `STATE.md` | yes | exact projection of `runtime/STATE.json` |
| `runtime/STATE.json` | yes | state schema, goal/contract identity, revision |
| `runtime/events.jsonl` | yes | event schema, hash chain, last revision/state hash |
| `runtime/evidence.json` | yes | evidence schema; initially `[]` |
| `runtime/state.lock` | no | regular one-byte lock file; never archived |
| `reports/final-audit.json` | no | final-audit schema and current identities |
| `reports/final-audit.md` | no | canonical projection of final-audit JSON |
| `reports/terminal-record.txt` | no | terminal-record grammar below |
| `out/review-md-files-delivery-receipt.json` | no | matching receipt schema |
| `out/final-artifacts-delivery-receipt.json` | no | matching receipt schema |
| `out/final-artifacts-manifest.json` | no | archive-result schema |

The manifest does not include mutable bytes in the sealed fingerprint. Package validation verifies every present mutable path according to the registry; any file that is neither a sealed artifact nor an exact registered mutable path fails closed.

Compilation initializes `runtime/STATE.json` with schema `3.0`, lifecycle `COMPILED`, revision `1`, current phase equal to the dependency-ready phase with the lowest ordinal, phase status `PENDING`, zero attempt/audit counts, and the emitted contract identity. Semantic validation requires positive unique contiguous ordinals but does not require the first phase id to be `P01`. It writes one `state_initialized` event carrying the same identity, revision, serialized state hash, previous-event hash `null`, and its own event hash. `STATE.md` is rendered from that JSON, and `runtime/evidence.json` is `[]`.

All mutable updates use one package lock. A state transition first appends and fsyncs a journal event containing the complete target state and state hash, then atomically replaces `STATE.json` and `STATE.md` from sibling temporary files. Recovery replays the last valid journal state after an interrupted projection write. Evidence and audit writes use the same lock and temporary-file/`os.replace` discipline. Every runtime writer is rooted at the package and opens parent components without following symlinks or Windows reparse points, so a junction cannot redirect a mutable write outside the package. Validators report a recovery-required diagnostic when the journal and projection differ; they never silently choose the newer-looking file.

### 3. Relocatable self-contained execution

The compiler copies an explicit runtime inventory rather than recursively copying the repository. Direct library callers use the repository's canonical `templates/PROTOCOL.md`; the four-line protocol fallback is removed.

`LAUNCH_GOAL.md` uses a relocatable locator: the package root is defined as the parent directory of the `LAUNCH_GOAL.md` being executed. It never embeds the compile-time absolute path. Once entered, protocol commands are relative to that package root and use:

```text
python scripts/sgctl.py <command>
```

Unix `.sh` scripts remain compatibility wrappers around Python commands. They are not the authority and are not required on Windows. Nested roots such as `.supergoal/<slug>` and relocated packages must work without global string replacement.

Compilation and package validation resolve `templates/`, `profiles/`, `spec/risk-policy.json`, and Python helpers from the package being built or validated. An installed-skill fallback is forbidden: deleting the source checkout after compilation must not change package validation or execution results.

### 4. Lossless executor views

`CONTRACT.json` remains the canonical plan. Generated views must render every execution-significant field:

- sources and decisions;
- architecture and loop boundaries;
- dependencies, work items, deliverables, and change expectations;
- criteria, blocking flags, verifier type/command/expected exit/assertion;
- command text, purpose, safety, and timeout;
- phase risk tags and RPD focus;
- approvals, delivery, research, compatibility, baseline, and rollback data.

Renderers must not invent rollout, cron, Telegram, or non-git claims absent from the resolved contract/profile. `validate-package` recompiles immutable views in memory and compares canonical bytes, including `PROTOCOL.md`.

### 5. Cross-platform runtime and canonical bytes

Text artifacts are encoded to UTF-8 and written as explicit LF bytes. Serialized paths always use `/`; filesystem access always uses `pathlib.Path`. Source reads accept CRLF but canonical comparisons use normalized output bytes.

State locking uses a small standard-library adapter with a ten-second timeout and 50 ms retry interval:

- non-blocking `fcntl.flock` on POSIX;
- `msvcrt.locking` on Windows over byte zero of a lock file initialized to one zero byte;
- the same context-manager contract and stale-writer revision check on both platforms.

The lock file is persistent and is never deleted, preventing inode replacement races. Both implementations seek to byte zero before lock/unlock, release in `finally`, and raise `SGV-STATE-LOCK-TIMEOUT` after the shared timeout.

The native aggregate runner is Python. `scripts/test.sh` delegates to it on Unix and retains shell lint checks. Tests that need WSL convert Windows paths explicitly; symlink security tests skip only fixture creation when Windows privileges prohibit symlinks, while the archive implementation is still tested with mocked/path-policy cases.

### 6. Evidence and terminal completion

Audit accepts evidence only when it matches all applicable authority fields:

- goal id;
- contract revision and contract SHA-256;
- phase and criterion;
- declared verifier command and expected exit for command evidence;
- result, redaction, freshness, and required artifact hash fields;
- mandatory policy evidence tags.

Missing, stale, cross-goal, wrong-revision, wrong-verifier-type, wrong-assertion, wrong-command, or wrong-exit evidence is an audit gap. The exit code must equal the criterion's declared `expected_exit`; an exact declared non-zero exit is valid. Approval and delivery manifests are phase-scoped auxiliary evidence with the exact reserved `criterion_id` value `__phase__`; they remain valid for zero-criteria phases and cannot substitute for criterion proof. Runtime state must reach `DONE` through legal revision-checked transitions before terminal completion is possible; `AUDITING` and `DONE` require the active phase to remain `COMPLETE` and unblocked.

Freshness is deterministic. Evidence timestamps use second-precision RFC3339 UTC (`YYYY-MM-DDTHH:MM:SSZ`). The audit anchor is the timestamp of the current `transition:*->AUDITING` journal event, not the verifier's wall clock. `captured_at` must not be more than 300 seconds after that anchor; values within the allowed skew are clamped to the anchor for age calculation. Every evidence type uses `loop.evidence_max_age_seconds` (default `86400`) unless overridden by `loop.evidence_max_age_by_type`. Its effective age must be within that limit. `fresh_until` is either the literal `audit_end`, which still obeys the maximum age, or an absolute RFC3339 timestamp not earlier than the audit anchor. Malformed timestamps, missing audit anchors, excessive future skew, expired absolute times, and over-age records are audit gaps.

Terminal markers are exact standalone records, not substring searches. The only machine-authoritative terminal input is UTF-8/LF `reports/terminal-record.txt`, atomically produced by `sgctl finalize`; arbitrary Markdown is never scanned for completion. The file and identical CLI stdout contain exactly five lines and one final LF, with no leading/trailing whitespace or duplicate records:

```text
SUPERGOAL_TERMINAL v1 goal=<goal-id> contract_sha256=<64-lowercase-hex> contract_revision=<positive-int> state_revision=<positive-int> audit_sha256=<64-lowercase-hex>
AUDIT_COMPLETE
SUPERGOAL_RUN_COMPLETE
Goal complete: yes
END_SUPERGOAL_TERMINAL
```

The referenced audit hash must match `reports/final-audit.json`, whose state revision must equal current `runtime/STATE.json`. Audit recomputation also validates the sealed inventory, generated views, manifest fingerprint, and no-follow path policy; sealed drift invalidates an existing terminal record. CRLF, reordered/missing/duplicate lines, extra blank lines, bad identities, or additional text invalidate the record. `PROTOCOL.md` may document individual marker literals because it is never parsed as a terminal record. Contract-derived fields containing standalone terminal lines are rejected to prevent operator confusion. Marker-like prose and explicit negation do not complete a goal.

### 7. Deterministic archive

The package's `MANIFEST.json` is included once and unchanged. ZIP inventory is stored separately as `ARCHIVE-MANIFEST.json`. It records source files, canonical hashes, sizes, and logical modes but does not attempt to hash itself.

Determinism means byte-identical ZIP output on Windows and Linux for identical package bytes and mutable snapshot. The writer uses `ZIP_STORED`, sorted file entries, no directory entries, timestamp `1980-01-01T00:00:00`, UTF-8 filename flag, empty comments/extras, fixed Unix creator/extractor versions, and fixed logical external modes (`0755` only for the registered executable wrapper set, `0644` otherwise). The archive destination and its temporary file are always outside the package root; the optional in-package `out/final-artifacts-manifest.json` is only a result/receipt that points to that external archive. An inside-root destination fails with `SGV-PACKAGE-ARCHIVE-INSIDE-ROOT`. `runtime/state.lock` and prior delivery outputs are excluded from archive input. A post-write readback verifies unique names, flags, metadata, hashes, and manifest consistency before atomic destination replacement.

The shell delivery packager delegates to the Python archive implementation so there is one archive authority.

## Compatibility

- `schema_version` and `protocol_version` remain `3.0`.
- Existing `sgctl` commands and strict exit behavior remain available; runtime/evidence/archive commands are additive.
- Existing valid v3 contracts continue to compile after fixtures are made policy-complete.
- v2 migration remains supported and is verified on both platforms.
- Unix wrappers retain their current filenames and executable modes.
- Old non-self-contained compiler output receives an actionable validation diagnostic and must be recompiled.

## Error handling

Every rejected boundary returns a stable `SGV-*` diagnostic with invariant, stage, JSON/file location, message, and remediation. `spec/diagnostic-catalog.json` is the diagnostic-code authority; tests fail when code emits an unregistered diagnostic or the catalog contains an unused code. CLI commands must never print a success payload after an error. Partial compile output is built in a sibling temporary directory, validated, and atomically replaces the target only after success; failure leaves the previous valid target unchanged.

## Test strategy

Implementation follows red-green-refactor. Required regressions include:

- missing dependency, zero phases, duplicate ids, missing profile, inheritance cycle, unknown risk, missing approval, rollback, RPD focus, and policy evidence;
- direct library compile and CLI compile parity;
- exact self-contained runtime inventory and relocatability;
- nested package roots and spaces in Windows paths;
- lossless rendering mutation tests for every execution-significant field;
- CRLF source checkout and canonical LF output;
- Windows and POSIX state locking/stale writers;
- wrong-goal, wrong-revision, stale, wrong-command, wrong-exit, exact declared non-zero exit, and missing policy evidence;
- marker injection, marker negation, substring, duplicate marker, and authorized terminal output;
- deterministic archive, duplicate names, symlink escape, secret rejection, and readback;
- public-clean redaction and chip-private delivery defaults;
- compile -> validate -> transition -> evidence -> audit -> archive E2E.

GitHub Actions runs equivalent Python unit/semantic/rendering/security/migration/E2E/aggregate gates on Ubuntu and Windows. Shell syntax, shellcheck, and shfmt remain Ubuntu-specific and are installed rather than silently skipped.

## Rollout and rollback

Work is implemented on an isolated branch from `35a22fe`. Each subsystem is test-first and independently reviewable. Before publication:

1. native Windows aggregate passes;
2. native Linux/WSL fresh clone aggregate passes;
3. skill guard, user stories, privacy/secret scan, and `git diff --check` pass;
4. independent spec-correctness and quality reviews have no blocking findings;
5. the branch is committed, pushed, and GitHub Actions are read back green.

Rollback is the single publication commit or its bounded commits. No external deployment or data migration is involved.

## Acceptance criteria

- Invalid contracts cannot compile or validate as packages.
- A generated package executes its validation/runtime commands without the installed source skill.
- All contract fields affecting execution are preserved in canonical output.
- Completion cannot be authorized by forged or mismatched evidence or text markers.
- Archive creation is deterministic and collision-free.
- Native Windows and Ubuntu gates pass from clean clones.
- Public documentation accurately describes supported platforms, optional live canaries, and package boundaries.
