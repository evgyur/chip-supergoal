# Standing-goal runtime evidence and expected-failure CI baselines

Use this when continuing an already-compiled SuperGoal whose package owns the execution protocol, especially when phases include neutral comparisons or negative baselines.

## Runtime authority

1. Resolve the package root as the parent of the `LAUNCH_GOAL.md` being executed. Do not trust a remembered checkout path.
2. Read `runtime/STATE.json` first. Treat `STATE.md` as a projection only.
3. Read the declared package context and run every declared preflight command from the resolved package root.
4. Continue through the standard Hermes `/goal` session. Do not create a custom runner, nested `/goal`, Project Flow, or second execution state unless the package contract explicitly declares one.
5. Advance phase state only through package-local `sgctl state-transition` with the current expected revision. A normal phase sequence is `PENDING -> EXECUTING -> COMPLETE`, then the next phase starts `PENDING -> EXECUTING`.

### Exact preflight replay

Preflight is executable contract text, not a command family to reconstruct from memory.

- Re-read the current `LAUNCH_GOAL.md` on every continuation and extract only the Python command lines inside its actual `Preflight` fenced block.
- Execute those lines byte-for-byte from the resolved package root, in order. Do not infer extra validators, positional roots, formats, or phase arguments from prior runs or nearby documentation.
- A mistakenly added exploratory command failing does not prove the declared preflight is red. Stop, re-read the block, run the exact declared commands, and report the exploratory failure separately if it matters.
- Do not substitute a previously successful preflight from the transcript; package bytes and runtime authority may have changed.

### Honest external blockers

When a phase requires unavailable external capabilities or immutable receipts:

1. Implement and test the fail-closed/import-only path first; never synthesize a passing capability receipt.
2. Write a compact blocker evidence artifact containing the missing authority, completed local work, hashes of safe public reports, and confirmation that private source content was not exported.
3. Commit and push the coherent non-authoritative slice when the delivery boundary permits it, but do not mark the phase complete.
4. Transition the phase to `BLOCKED` with `--blocker-json` and the exact current revision. Do not also mutate lifecycle with `--to WAITING_EXTERNAL` unless `spec/state-machine.json` explicitly permits that edge from the current lifecycle; phase blocking and lifecycle transitions are separate authority changes.
5. Read back `state-show` and ask for the smallest concrete external input: controller access or immutable receipt paths. Optional authority upgrades must be listed separately from hard blockers.

### Explicit operator waiver and no-candidate continuation

If the operator explicitly says to skip unavailable external attestations, treat that as a **scoped waiver**, not as evidence that the capability passed.

1. Record a machine-readable waiver artifact with the exact waived evidence classes, operator authority, timestamp, and non-claims. Do not quote raw private chat; paraphrase the instruction and bind it to the current session/goal.
2. Preserve unavailable lanes as `import_only`, `non_authoritative`, or equivalent. Never rewrite them to `pass`, infer zero P0/P1, or replace missing observations with numeric zeroes.
3. Continue only when the frozen contract already permits a waiver, import-only lane, or `no_candidate` outcome. An operator waiver cannot silently invent a transition that the contract forbids; if no declared lane exists, amend/recompile the contract through its approval boundary or remain blocked.
4. When comparison authority is absent, emit a complete fail-closed report: task/stratum rows remain present, unavailable metrics are `null`, `promotion_capable=false`, `zero_p0_p1_proven=false`, and selection is `no_candidate`. Aggregate appearance must not rescue missing authority.
5. Remove the rejected layer from the **runtime candidate**. Preserve useful evaluators and regression tests under the developer/evaluation boundary when they still prove controls, but do not leave an unselected critic/repair layer in the portable runtime inventory or enabled profile.
6. Downstream rollout phases follow the contract's no-candidate branch: signed no-go/no-op control receipts, zero live exposure, and no promotion language. A no-candidate path can close the goal honestly; it cannot claim the planned quality lift occurred.

### No-candidate does not erase upstream blocking criteria

A downstream `no_candidate` branch changes rollout behavior; it does not retroactively satisfy an earlier blocking verifier.

1. Before completing any waived/import-only phase, build a criterion ledger directly from every phase contract: criterion ID, exact command, expected assertion/exit, observed result, and evidence-record ID.
2. If a required command exits `0` but its report says `import_only`, `non_authoritative`, or `authoritative=false`, compare the report to the **expected assertion**. Exit zero alone is not passing evidence.
3. Record such evidence as `unverified`, not `pass`. An operator waiver may authorize safe continuation only when the frozen contract declares that lane; it never converts the missing authority into promotion or final-audit proof.
4. Generate the final aggregate hard-gate map from all blocking criteria in `CONTRACT.json`, including upstream phases. Do not hand-pick only the latest reports. Add a regression test proving each known import-only report keeps the aggregate `blocked`.
5. Run the final aggregate before creating a closeout receipt. If the aggregate is blocked, do not emit closeout, do not enter `AUDITING`, and transition the current phase to `BLOCKED` with the original upstream criterion named in `blocker-json`.
6. If a false pass was already recorded, correct forward: regenerate the aggregate as blocked, remove any uncommitted stale closeout, append a newer `unverified` evidence record that names the superseded record, and commit the correction. Never rewrite the runtime evidence ledger or preserve a knowingly false green for convenience.

### Evidence timing: record before phase completion

Do not postpone package-local evidence recording until final audit. For each phase, the safe order is: run declared command → inspect semantic result → write exact `command_result` → strict package validation → RPD review → `VERIFYING` → `COMPLETE`. A late evidence backfill can hide that a completed phase never earned its transition and makes false-green correction much harder.

Before final audit, mechanically compare the runtime evidence ledger against every blocking criterion. Missing, duplicate-conflicting, stale, or `unverified` records are blockers, not clerical cleanup.

### Recovering a BLOCKED phase legally

Do not jump directly from `BLOCKED` to `VERIFYING`; event validation commonly permits `BLOCKED -> EXECUTING -> VERIFYING` only. When the blocker field must be cleared and package-local `sgctl` has no direct clear-blocker flag:

1. Inspect `spec/state-machine.json` and the phase-status edge table first.
2. If declared, transition lifecycle `RUNNING -> RECOVERING` without changing phase status; this clears the stale blocker through a legal runtime event.
3. Transition `RECOVERING -> RUNNING` while setting the same phase to `EXECUTING`.
4. Re-run acceptance, then transition `EXECUTING -> VERIFYING -> COMPLETE` with exact revisions and read back every result.

Do not hand-edit `runtime/STATE.json`, and do not combine lifecycle recovery with an illegal phase-status jump. A CLI that prints an error object with shell exit `0` still failed semantically; inspect returned state/revision instead of trusting `set -e` alone.

## Evidence records must match the executable contract exactly

Before recording phase evidence, read the phase object from `CONTRACT.json` and derive records from it instead of retyping prose.

If a verifier has `command_id`, the evidence type must be `command_result`, even when the criterion's evidence tier says `direct_artifact`.

For a passing `command_result`:

- `command` must byte-match the command declared for that `command_id`;
- `assertion` must byte-match `expected_assertion`;
- `exit_code` must equal `expected_exit`;
- `replayable` must be `true`;
- attach the deliverable SHA-256 in `artifact_sha256` when useful;
- record RPD focus and artifact paths in allowed metadata fields, not ad-hoc keys.

`SGV-EVIDENCE-TYPE-MISMATCH`, `SGV-EVIDENCE-COMMAND-MISMATCH`, or `SGV-EVIDENCE-ASSERTION-MISMATCH` means the record was hand-authored against the human-readable criterion rather than generated from the executable verifier. Rewrite it from `CONTRACT.json`; do not weaken validation.

After all criteria have fresh passing evidence, transition the current phase to `COMPLETE` before advancing to the next phase. Never use marker text as runtime authority.

### Recording sequence and package hygiene

Use this order for every criterion batch:

1. Generate each input record from the live `CONTRACT.json` phase object into an external temporary path such as `/tmp/EV-<criterion>.json`; do not leave helper inputs in the compiled package.
2. Call package-local `sgctl record-evidence` with that absolute input path and require exit `0` for every record.
3. Delete temporary inputs after the runtime ledger has durably copied them.
4. Run strict package validation before changing phase state.
5. Transition with the exact current revision, then immediately read back `state-show`.

Evidence metadata is a closed schema. Prefer a single allowed `notes` value for artifact paths and review-receipt pointers, or another field already declared by the package schema. Do not invent convenient keys such as `rpd_review`: `unknown evidence metadata fields` is a record-construction defect, not a reason to bypass the ledger. Preserve failed command output while debugging; a loop that reports only exit codes destroys the diagnostic needed to repair the batch.

## Neutral CI matrices with an expected-failing baseline

A negative baseline can be evidence without making the whole CI run red. Preserve both facts:

1. Run the same neutral probe against baseline and candidate/hardening targets.
2. Always emit and persist a receipt containing target SHA, probe hash, environment, measurements, findings, and status.
3. Validate that the baseline failed for the preregistered reason. Do not accept an arbitrary crash as the expected negative result.
4. In the CI wrapper, exit `0` for the validated baseline target after the receipt is captured.
5. For candidate/hardening targets, propagate the probe exit code. Their failure remains blocking.
6. Keep the aggregate job dependent on the matrix jobs so a real candidate/platform regression cannot be hidden.

On PowerShell, capture `$LASTEXITCODE` immediately after the probe, publish the receipt, then branch explicitly on the target role. Avoid a compound condition that accidentally propagates the expected baseline failure.

## Immutable cross-platform receipts

When Windows jobs are long-running:

- use full-history checkout when the probe executes frozen SHAs (`fetch-depth: 0`);
- extract machine-readable receipt payloads from completed job logs and store decoded JSON under the evaluation results tree;
- bind each receipt to target SHA and neutral-probe SHA-256;
- require both native Windows versions plus Linux parity before closing the foundation phase;
- report expected baseline failures separately from candidate failures.

## CI platform labels are not capability authority

A green job on `windows-latest` or Ubuntu proves only the commands that job actually ran. It does not implicitly prove Hyper-V isolation, rootless Podman containment, or any other backend named by a blocking criterion.

When a delayed/background CI notification arrives during a standing goal:

1. Bind it to its exact run ID and head SHA; an old successful run is historical evidence, not proof for the current head.
2. Inspect job names, executed steps, and downloadable receipts—not just the aggregate conclusion or platform label.
3. Compare the emitted artifact schema and semantic fields to the criterion's expected assertion. A neutral Windows probe, ordinary Python test matrix, or `status=import_only` report cannot satisfy a native Hyper-V containment requirement.
4. Check authoritative `runtime/STATE.json` after classifying the notification. Do not clear a blocker or advance revision merely because the CI aggregate is green.
5. Report the useful delta compactly: what the run proves, what it does not prove, and whether runtime authority changed.

Add a regression test when possible: a green generic Windows/Linux matrix with no required backend receipt must leave the final aggregate blocked.

## Push and watch discipline

Long matrix runs are easy to cancel accidentally through branch concurrency.

- Finish and locally verify a coherent phase slice before pushing.
- Do not start a blocking `gh run watch` if another immediate phase commit will supersede that run.
- If a newer push intentionally cancels the watched run, stop the old watcher and watch only the newest head SHA.
- Treat local full-suite success as phase evidence only when the phase contract allows it; use the final uncancelled CI run as repository-level integration proof.

## Completion markers

Only emit `AUDIT_COMPLETE`, `SUPERGOAL_RUN_COMPLETE`, and `Goal complete: yes` together after runtime authority permits completion and the final audit is actually green. Never print them for an intermediate phase or merely because the host requests compatibility strings.
