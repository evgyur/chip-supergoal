# Production canary: artifact integrity, runtime identity, observers

Use this reference for hash-bound SuperGoal releases that switch live systemd services and then observe a canary.

## Immutable artifact smoke

- Treat a built candidate directory as immutable immediately after digest generation.
- Python smoke commands can silently add `__pycache__/` and `.pyc`; run them with `PYTHONDONTWRITEBYTECODE=1` or smoke a disposable copy.
- Do not “fix” candidate readability by recursively changing modes after hashing. Exercise the install path that applies final ownership/modes, or use a non-mutating runtime identity.
- Re-run the artifact digest verifier after every packaged smoke. A successful functional smoke is insufficient if the artifact fileset drifted.

## Packaged runtime smoke: import roots and DSN schemes

A script that passes from the repository root may fail after release packaging because application modules moved under `backend/`. Entry points shipped both ways should resolve `ROOT / "backend"` when that directory exists and otherwise fall back to `ROOT`. Test the packaged entry point itself; a source-tree unit test does not prove release layout.

Live environment DSNs may use the generic `postgresql://` form while SQLAlchemy's installed driver is Psycopg 3. Before `create_engine`, normalize that exact prefix to `postgresql+psycopg://`; do not alter already explicit driver URLs. Exercise the packaged script with the live read-only service identity and redacted output.

Run packaged Python smoke with `PYTHONDONTWRITEBYTECODE=1`, then re-run the artifact digest/fileset verifier. Otherwise a successful smoke may invalidate the candidate by adding `__pycache__` after hashing.

## Exact runtime identity and secret contract

Before canary activation, test each private file with the exact service identity and sandbox assumptions:

1. inspect every parent-directory owner/mode;
2. inspect `User=`, `Group=`, `SupplementaryGroups=`, `ProtectSystem=`, `ProtectHome=`, and `ReadWritePaths=` from the live unit;
3. execute the application's real secret reader in a transient systemd context with the same user/groups;
4. verify semantic constraints, not only OS readability. A reader may correctly reject a group-readable `0640` token even when the service can read it; use owner-only `0600` with the service user when that is the contract;
5. run a loopback authenticated smoke without printing the token.

A service observed as `active` during `Restart=on-failure` may still be crash-looping. Require a restart-stability dwell, `NRestarts` readback, endpoint smoke, and journal check before accepting it.

## Pre-switch versus post-switch verification

A rollout verifier needs two explicit modes:

- **baseline mode** before mutation: current symlink and release hash must match the recorded live baseline;
- **candidate mode** after the approved switch: current symlink and release hash must match the approved candidate.

Do not reuse a baseline-only verifier inside the canary observer; it will report the intended switch as drift and create a false failure. Both modes must still verify manifest hash, immutable seeds, candidate artifact digest, Git identity/cleanliness, and stable projections of volatile registries.

## Release metadata schema discipline

Treat `release.json` as a versioned contract, not a bag of guessed field names:

- inspect its declared schema and actual keys before writing an integrity probe; repositories may use `repo_sha`, `git_sha`, `git_commit`, or a deliberately shortened commit identity;
- prefer the approved release-file hash plus `artifact_sha256` as the strongest identity proof, then validate the schema-defined commit field against the manifest using explicit full/short-prefix semantics;
- do not turn a missing guessed key or a short SHA into a candidate mismatch; classify that as a verifier defect and repair the probe;
- in post-switch reports, expose `baselineReleaseId` and `currentReleaseId` separately. Do not keep labeling the recorded baseline as `liveReleaseId` after the candidate is live, because the JSON may say `verdict=PASS` while presenting misleading identity evidence.

Bind these semantics in tests for both baseline and candidate modes before deployment.

## Observer ordering

1. Validate baseline mode.
2. Apply the exact approved mutation.
3. Perform immediate service/health/secret/endpoint checks.
4. Start the bounded observer in candidate mode.
5. Poll health, required units, restart counts, and monotonic risk counters.
6. On a real stop-rule, rollback first; then prove baseline symlink, health, required units, and rollback receipt.
7. If the observer itself fails before polling because of verifier logic, classify it separately from a canary failure. Repair the observer, prove candidate state fresh, and restart observation without inventing a rollback.

## Observer replacement and late completion notices

Bind every background observer to a unique process/session ID in mutable runtime state. When an observer is replaced after an observer-only defect:

- mark the old ID superseded before starting the replacement;
- record the replacement ID and the authoritative canary start time;
- treat a late completion notification from the superseded observer as stale control-plane evidence, not as the current canary verdict;
- verify current symlink, health, units, restart counters, and monotonic risk counters before dismissing the stale notice;
- anchor the observation deadline to the successful canary start only when interval evidence remained continuous. If continuity cannot be proved, reset the full observation window conservatively and record why.

Do not let an old background notification overwrite the current observer ID or trigger an unnecessary rollback.

## One-shot systemd evidence

`Type=oneshot` services normally return to `inactive (dead)` after success. Judge them by `Result`, `ExecMainStatus`, timestamps/journal output, and expected evidence—not by persistent `active` state. If the workload has an empty eligible cohort and intentionally writes no file, store a compact receipt from the successful journal result (`eligible=0`, `emitted=0`) rather than misclassifying absence as failure.

Preserve probe exit codes. A diagnostic shell such as `probe; inspect; cleanup` can return success from cleanup even when the probe failed. Use `set -euo pipefail`, capture the probe return code explicitly, or perform cleanup in a trap and then re-emit the original code. For oneshot probes, read the root journal and `Result` after the command; silence plus a final shell exit code is not enough evidence.

## In-flight outbox work during observation

Do not treat every `processing` row as a canary failure. Distinguish active bounded work from a stale lease without reading private payloads:

1. compare `failed` count to the pre-canary monotonic baseline;
2. inspect only operational metadata: topic, attempts, `locked_at`, `locked_by`, service identity, and process state;
3. verify that the owner is alive and executing the expected read-only/external call path;
4. derive the stale threshold from the documented worst-case work bound (request timeout × retries × bounded item count + pacing), not from an arbitrary short delay;
5. trigger a stop/reclaim review only after that bound or when failed count/restart count rises.

A fresh lease owned by a healthy read-only worker is evidence of active processing, not drift. Do not restart the worker merely to make aggregate counters look idle. Keep diagnostics privacy-safe: omit payloads, wallet addresses, API keys, and user identity. Temporary syscall traces must be narrowly scoped and deleted after the diagnosis.

For `Type=oneshot`, transient execution timestamps may no longer be populated after the unit returns to `inactive`; the root journal plus `Result=success` and the application’s compact output are the durable proof.

## Evidence output isolation across phases

Treat completed phase evidence as append-only. Before reusing an audit/replay helper during a later canary or final audit:

1. inspect its default output path;
2. require an explicit `--out <current-phase-path>` when supported;
3. if the helper hardcodes an earlier phase directory, patch it to accept `--out` before execution rather than overwriting historical evidence and copying afterward;
4. hash or snapshot completed-phase evidence before any reused writer runs, then verify it did not drift;
5. keep the later observation in its own phase directory and bind it into that phase's source registry.

A read-only database audit can still mutate the evidence filesystem. `mutations=0` for production state does not excuse rewriting P02/P03 receipts during P06. Final audit should distinguish production mutations from evidence mutations and fail unexplained cross-phase drift.

## Delayed soak gates and stage-specific retirement approval

A short observer PASS closes only the short observer gate. It does **not** satisfy a manifest that separately requires a longer soak interval before legacy retirement, cron rewrites, replay, or expanded authority.

For multi-stage production manifests:

1. keep separate approval receipts and executable stages for canary and retirement;
2. derive `eligibleAfter` conservatively from the successful observer's `completedAt + required soak duration` unless the manifest explicitly anchors the interval to switch time and continuous evidence proves that earlier start;
3. record `CANARY_PASS / BLOCKED_BY_TIME_AND_APPROVAL` (or the package's equivalent honest status) while the delayed gate is open; do not advance the phase, start the final audit, or emit completion markers;
4. an approval phrase sent before `eligibleAfter` does not waive the time gate;
5. at eligibility, freshly verify the unchanged manifest hash, candidate release/current symlink, immutable seeds, health, required units, restart counters, monotonic outbox failures, absence of new funded actions, and candidate-attributable warning/error logs;
6. only then request or accept the exact stage-specific retirement phrase and write a new receipt bound to the unchanged manifest;
7. execute retirement in declared order, prove archive/rollback and no auto-resume, and only then close the phase.

For a durable wait, schedule a one-shot **read-only** gate check at `eligibleAfter`. Its prompt must be self-contained, forbid retirement and all live mutations, report eligibility, and provide the exact phrase Chip may send. The job must never auto-approve, auto-retire, or recursively schedule another job. Repeated standing-goal wrappers before eligibility should not trigger cosmetic busywork or repeated long approval cards: do one fresh bounded readback when useful, report the stable blocker compactly, and wait for the scheduled gate check or new instruction.

## Approved retry boundary

After an approved stop-rule rollback, retry under the same exact manifest only when all are true:

- candidate hash, target, blast radius, and excluded actions are unchanged;
- the correction only makes the already-approved runtime contract true;
- baseline recovery was freshly verified;
- the corrected prerequisite was tested under the exact runtime identity;
- the retry and prior rollback are both recorded in mutable runtime evidence.

If scope, candidate SHA, target, credentials class, external effects, or risk caps change, invalidate the old approval and request a new exact manifest approval.
