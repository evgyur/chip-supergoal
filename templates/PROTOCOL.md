# chip-supergoal execution protocol

This file is read by the executing agent at the start of the single `/goal` session and followed throughout. It is the operating manual for the autonomous run.

Set `PACKAGE_ROOT` to the absolute directory containing this `PROTOCOL.md` and `CONTRACT.json`. Set `TARGET_WORKTREE` from `CONTRACT.json.goal.workspace_root` only for single-workspace non-repository tasks. Package state, scripts, phases, reports, and receipts are always addressed through `$PACKAGE_ROOT`. For Git-backed work, read `CONTRACT.json.architecture.repo_baselines`: every repository entry must provide its own absolute `root` and exact `baseline_sha`, and every repository check must run against that owning root/baseline pair. When `implementation_roots` declares multiple repositories, a missing/non-Git root or missing exact baseline fails with exit 2; never degrade to `$TARGET_WORKTREE`, a delimiter-joined pseudo-ref, or filesystem existence evidence. Do not assume the package is installed as a `.supergoal` subdirectory of the target repository.

## The loop

Repeat inside the same `/goal` run until `SUPERGOAL_RUN_COMPLETE` is printed or a real safety/approval blocker stops execution. **Chip mode: do not stop at numbered phase boundaries.** `SUPERGOAL_PHASE_DONE` is a checkpoint, not a reason to yield. Continue immediately into the next phase/audit while tool budget and safety allow.

Weak blockers are forbidden. A private proof action that is part of the requested verification — for example a private DM smoke/readback to Chip's own bot, local tests, read-only inspections, usage/log queries, report writes, or repo cleanup — is not an approval blocker by itself. Only the real gates listed below may stop the run.

**File-first runtime rule:** manifested `$PACKAGE_ROOT/STATE.md` and `$PACKAGE_ROOT/runtime-seed/*.md` are immutable compiler seeds. Before every run, execute `bash "$PACKAGE_ROOT/scripts/init-runtime.sh" "$PACKAGE_ROOT"`; it atomically initializes the mutable bundle under `$PACKAGE_ROOT/out/runtime/`, verifies an existing bundle, and never overwrites live state. Mutable coordination lives only under `$PACKAGE_ROOT/out/runtime/`, which is excluded from manifest drift checks. Never edit manifested seeds or `MANIFEST.json`.

1. Read mutable state in this order: `$PACKAGE_ROOT/out/runtime/STATUS.md`, `TODO.md`, `PLAN.md`, relevant sections of `MEMORY.md`, then the latest entries in `RUN_LOG.md`. Use `CHECKS.md` and `REVIEW.md` as the verification and review ledgers.
   - If `STATUS.md` says `phase: AUDIT`, skip numbered phases and run the **Final audit** below.
   - If it says `BLOCKED_BY_APPROVAL`, `READY_FOR_DELETE_APPROVAL`, or another explicit human/provider approval gate, first reassess whether the blocker is real under the weak-blocker rules above. If it is fake/over-broad, supersede it in `STATUS.md` and append the reason to `RUN_LOG.md`. If it is real, stop the loop. Do not re-run checks or restate the same approval card on repeated continuations.
   - Files are not automatically injected into subagents. Every delegation must include the package workdir, all seven absolute runtime paths, one claimed TODO ID, and the read/update contract.
2. Read `$PACKAGE_ROOT/LOOP_DESIGN.md` when present. Treat it as the execution harness: host/reviewer/judge roles, verification gates, state checkpoints, stop/budget limits, boundaries, egress/redaction, recovery, and ASCII preview. If the file is missing for an older package, continue compatibly but record the gap in `STATUS.md` and `RUN_LOG.md`; do not invent a parallel loop.
3. Read `$PACKAGE_ROOT/phases/phase-<zero-padded N>.md` (for example, phase 1 is `phase-01.md`). This is your full work spec. Compiled packages use two-digit phase filenames; do not look for `phase-1.md`.
4. Initialize or resume the **run-wide atomic execution lease** before any project mutation. Use `python3 "$PACKAGE_ROOT/scripts/execution-lease.py" acquire "$PACKAGE_ROOT" --owner "${HERMES_SESSION_KEY:-hermes}:${HERMES_SESSION_MESSAGE_ID:-unknown}" --owner-pid "$PPID"` for a fresh run; the script persists the raw token only in owner-only `$PACKAGE_ROOT/out/runtime/.execution-lease-token`; record only that path and the returned owner hash in `STATUS.md`, never the raw token. On every resumed turn and before each phase mutation, run `python3 "$PACKAGE_ROOT/scripts/execution-lease.py" check "$PACKAGE_ROOT" --token-file "$PACKAGE_ROOT/out/runtime/.execution-lease-token" --owner "${HERMES_SESSION_KEY:-hermes}:${HERMES_SESSION_MESSAGE_ID:-unknown}"`, then run the matching `refresh` action with the same `--owner` value. If another token owns the lease, stop as a single-writer conflict. Never adopt another executor's token. Stale recovery is fail-closed: it requires the configured minimum heartbeat age **and** proof that the recorded owner PID/start-time/executable identity is no longer live, plus a recorded reason/checked-hold. A live matching owner can never be displaced by elapsed time. Any manual takeover without proven owner death requires a separate authenticated approval gate; it is not automatic.
5. Resolve and fail-close the phase execution route **before any project mutation**. Read `CONTRACT.json.loop.execution_profile.phase_routes` and require exactly one route for the current phase that matches `Execution route:` in the phase spec.
   - `direct`: do not dispatch Luna.
   - `shawl`: load the canonical `shaw` skill and its Shawl/Luna mode reference; run canonical `shaw-luna-pool.py check`; require model `gpt-5.6-luna`, read-only scout mode, and the contract's scout/review bounds. Never substitute another model or direct provider call while calling the route Shawl.
   - Append route, candidate identity before dispatch, report/artifact paths, finding dispositions, local reproduction commands/exits, candidate identity after mutation, and Sol/GoalManager verdict to `$PACKAGE_ROOT/out/runtime/REVIEW.md` and `RUN_LOG.md`. Luna findings are hypotheses: only Sol/GoalManager may reproduce, write/integrate, advance state, or decide `GO`/`DONE`. Every code-affecting fix creates a new candidate identity and requires a fresh exact-candidate review. Route mismatch, missing canonical Shawl, writer overlap, or exhausted review budget with unresolved P0/P1 fails closed with the exact blocker.
   - After the route is resolved, claim exactly one stable phase ID in `TODO.md`, set one owner, and mirror the active TODO in `STATUS.md`. If another owner already holds it, stop as a single-writer conflict.
6. Print `SUPERGOAL_PHASE_START` with the spec's metadata (phase number, name, task, execution route, mandatory commands, acceptance count, evidence types, dependencies).
7. Print `SUPERGOAL_STATUS` for human readability: current phase, percent, status, current action, check summary, latest evidence, and next step. This is not completion proof and does not replace the runtime files or formal markers.
8. Do the work described in the spec. Run each mandatory command at most once unless its declared effect set is purely read-only/local-test and the previous attempt is proven pre-effect. Approval-consuming, metered/provider, signer/claim, destructive, public-send, production, and ambiguous-effect commands are one-shot: after any attempted invocation, recover from receipts/state instead of retrying. Surface evidence into the transcript (command output last ~10 lines + exit code; file listings; key diff excerpts).
9. Print `SUPERGOAL_PHASE_VERIFY`: each acceptance criterion `pass|fail` with evidence; engineering checks (build/typecheck/lint/tests); **cleanliness checks** — for every Git repository declared in `CONTRACT.json.architecture.repo_baselines`, `cd` to its exact `root` and run `bash "$PACKAGE_ROOT/scripts/repo-state.sh" added-lines <that repository's baseline_sha>` (the complete set of added/new lines since baseline, **including uncommitted and untracked work**) and grep it for stack-specific debug patterns — `console.log`/`console.error` for JS/TS; `print(`/`pprint(` for Python; `print(`/`dump(` for Swift; `fmt.Println`/`log.Println` for Go; session TODO/FIXME added this phase; dead imports added; files changed count via `bash "$PACKAGE_ROOT/scripts/repo-state.sh" changed-files <that repository's baseline_sha> | wc -l`; notable diff one-liners. Fail with exit 2 if any declared Git root/baseline is absent or invalid. The **files-changed count and ordinary declared implementation lines are informational**, because a real phase is expected to change its allowed surface. Fail/repair only on explicit prohibited debug/TODO/dead-import patterns, out-of-scope or undeclared paths, invalid baseline/ownership, secret/private-path leakage, or a phase-specific cleanliness rule. A phase may add `Cleanliness override:` only to explain an intentional otherwise-prohibited pattern; it must never waive scope, secret, baseline, or ownership failures. Record every criterion/command result and evidence pointer in `CHECKS.md`; do not leave transcript-only proof.
10. **RPD phase review.** If the phase spec declares `RPD required: yes` or the phase touches a risky area, run `RPD_PHASE_REVIEW`. Append findings, evidence tier, mutation/checked-holds decision, and verdict to `REVIEW.md`. Fix any gap before `SUPERGOAL_PHASE_DONE`.
11. **Memory writeback check.** Write task-local verified facts, decisions, constraints, and mistakes to avoid into `$PACKAGE_ROOT/out/runtime/MEMORY.md`; do not store raw transcripts, secrets, or temporary progress. If a non-obvious reusable lesson should survive this project, also write it under the detected MEM_DIR and link it from the runtime memory. Print `MEMORY_SAVED: <name>` or `MEMORY_SAVED: none`.
12. Print `SUPERGOAL_PHASE_DONE`. Transactionally update the runtime bundle: mark phase N `done` in `TODO.md`; set the next phase or `AUDIT` in `STATUS.md`; append one evidence-bound event to `RUN_LOG.md`; ensure `CHECKS.md` and `REVIEW.md` reflect the same outcome. If any write fails, keep the phase incomplete and repair state before continuing.
13. **Continue, don't courtesy-yield.** After runtime writeback, immediately read the next phase or enter `AUDIT`. Do not print `SUPERGOAL_TURN_YIELD` solely because a phase ended. If a real gate/blocker is hit, record it in `TODO.md`, `STATUS.md`, and `RUN_LOG.md`, then print the blocker once and stop.
14. When `STATUS.md` says `phase: AUDIT`, run the **Final audit** below. Planning review delivery is a planner dispatch gate; if the user already launched the goal, a missing `review-md-files-delivery-receipt.json` is an `AUDIT_GAP`/warning to report, not a product-completion blocker. Final artifact delivery receipts are blocking only when final-file delivery was requested. Release the run-wide lease only after all terminal runtime files and required receipts are durable by running `python3 "$PACKAGE_ROOT/scripts/execution-lease.py" release "$PACKAGE_ROOT" --token-file "$PACKAGE_ROOT/out/runtime/.execution-lease-token" --owner "${HERMES_SESSION_KEY:-hermes}:${HERMES_SESSION_MESSAGE_ID:-unknown}"`, then print `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE` with a 5-line summary. The `/goal` condition is satisfied only after product verification, coherent terminal runtime files, required final delivery receipts, and final markers exist.

## Dev-history hardening gates

These gates come from repeated Dev-chat incidents and override vague convenience:

- **Continuation over status-only:** if `$PACKAGE_ROOT/out/runtime/STATUS.md` is not `DONE` or truly `BLOCKED`, continue the current phase/audit from disk. Do not answer only with a status report when work can safely continue. Do not invent approval blockers for private verification, local checks, read-only probes, usage/log inspection, or requested repo cleanup.
- **Gateway restart/autoresume:** after restart, withheld autoresume, or repeated `/goal resume`, inspect `$PACKAGE_ROOT/out/runtime/STATUS.md`, active goal identity, and the last phase marker. Resume safely; do not create a new root unless the state identity is ambiguous or the user explicitly asks for a clean SuperGoal.
- **Retrieval-before-ask:** before asking for keys, wallet refs, prior artifacts, package paths, docs, or approvals the user says already exist, search `$PACKAGE_ROOT/`, repo docs, local ignored overlays, session history, relevant skills, and Telegram history when available. If missing, name what was checked.
- **Safe-lane approval:** broad “делай всё до конца” covers safe repo/docs/tests/private-skill work through requested commit/push/verification. It does not approve money/DNS/secrets/grants/destructive production/public posting.
- **Bounded live manifest:** money, wallets, trading, DNS, secrets, grants, destructive production, and public/mass sends require one exact bounded manifest. If absent, print `BLOCKED_BY_APPROVAL` and stop.
- **Repo/private delivery:** if the task names `git push`, `private repo`, or a skill publication target, phase/final DONE requires remote HEAD verification and clean status, or an explicit local-only boundary.



## Standard Hermes `/goal` compatibility

This protocol is designed for the upstream Hermes GoalManager. Do not start a custom runner and do not spawn nested `/goal` commands. The standard `/goal` loop only sees the standing goal and the latest response snippet; it does not understand SuperGoal phases, receipts, approvals, or audit state unless the response states them clearly.

If the platform forcibly cuts off before final completion, use the footer below so the host resumes. Do not voluntarily stop after a normal phase.

```text
SUPERGOAL_TURN_YIELD
Goal complete: no
Next: <phase N+1|AUDIT|blocked marker>
Completion requires: AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE in the same final response.
```

Final completion must end with:

```text
AUDIT_COMPLETE
SUPERGOAL_RUN_COMPLETE
Goal complete: yes
```

Do not use `Goal complete: yes` anywhere else. A phase being done is not the whole goal being done. If `AUDIT_COMPLETE` is present without `SUPERGOAL_RUN_COMPLETE`, the standard judge should continue. If `SUPERGOAL_RUN_COMPLETE` is present without `AUDIT_COMPLETE`, that is a protocol violation and must be treated as incomplete.

## Embedded RPD v2 gates

chip-supergoal embeds RPD directly. Do not load or invoke an external `/rpd` skill. Use this protocol and the embedded RPD contract below.

RPD is a mutation gate, not a commentary layer. Every finding must either mutate work/specs/commands/criteria/audit-fix specs, or be marked `checked-holds` with an evidence tier. Material claims must use one of: `direct artifact`, `provided context`, `external/current source`, or `assumption` with falsifier. Memory, stale phase text, and previous self-reports are not proof of current state.

Run Senior Gate for risky phases/final completion involving production, money, privacy, credentials, auth/payments, gateway/routing/cron/model-provider routing, architecture/migration, public launch, recurring bugs, or claimed completion after a risky run. Any new layer/fallback/agent/shim must pass the overengineering budget: necessity, simpler alternative rejected, removal condition.

### RPD_PHASE_REVIEW

Run after `SUPERGOAL_PHASE_VERIFY` and before `MEMORY_SAVED` when the phase spec declares `RPD required: yes` or touches a risky area: auth, payments, secrets, private data, database migrations, destructive data changes, production infra, gateway/routing/cron/model-provider routing, architecture/migration, recurring bugs, baseline-red recovery, or public launch.

Print:

```text
RPD_PHASE_REVIEW
Phase: <N>
Focus: <focus>
Evidence map: <direct artifact / provided context / external source / assumption claims>
Pattern: <finding + evidence tier + mutation|checked-holds>
Assumption: <claim + true|false|unverified + evidence tier + mutation|checked-holds>
Stress test: <failure mode + mitigation mutation|checked-holds>
Integration: <touchpoints + canonical truth + split-brain risk + mutation|checked-holds>
Senior Gate: <required|skipped with reason; findings + evidence ledger|checked-holds>
Overengineering budget: <checked + mutations|checked-holds>
Mutations applied before DONE: <list or none — checked-holds>
```

If the review finds a gap, fix it before `SUPERGOAL_PHASE_DONE` and re-run affected mandatory commands or criteria. If the gap cannot be fixed safely, keep the phase blocked.

### RPD_FINAL_REVIEW

Run after `AUDIT_VERIFY` and before `AUDIT_COMPLETE` in every final audit round.

Print:

```text
RPD_FINAL_REVIEW
Evidence map: <direct artifacts / trust-prior / assumptions>
Pattern: <known/repeat failure class or checked-holds>
Assumption: <completion claim still unverified, or checked-holds>
Stress test: <path that can still break, or checked-holds>
Integration: <unchecked downstream touchpoint + canonical truth, or checked-holds>
Senior Gate: <required|skipped with reason; P0/P1/P2/P3 findings + evidence ledger|checked-holds>
Overengineering budget: <checked + mutations|checked-holds>
Decision: complete | audit-fix-needed | handoff
```

If decision is `audit-fix-needed`, write `$PACKAGE_ROOT/phases/audit-rpd-fix-<round>.md`, execute it inline, and then rerun the audit round. If decision is `handoff`, print `AUDIT_HANDOFF`, update `$PACKAGE_ROOT/out/runtime/STATUS.md` to `BLOCKED`, and do not print `SUPERGOAL_RUN_COMPLETE`.

## Final audit (Stage 10 — runs after the last phase, before completion)

Per-phase VERIFY blocks are self-reports. The audit closes that loophole by re-validating against the **original** `ROADMAP.md`, not against this run's own self-reports. The audit runs up to 3 rounds; on the 3rd round's failure, `AUDIT_HANDOFF`.

### Audit steps (one round)

1. Print `AUDIT_START` (round number, total phase count, criteria count, deduplicated mandatory commands to re-run).
2. Re-read `$PACKAGE_ROOT/ROADMAP.md` and pull every phase's acceptance criteria fresh from the original plan.
3. **Phase completeness:** scan the transcript for one `SUPERGOAL_PHASE_DONE` per phase 1..N. Any missing = an `AUDIT_GAP`.
4. **Effect-aware command audit.** Re-run only deduplicated commands whose contract-declared effects are purely read-only, static-analysis, or local-test and whose invocation cannot consume approval, spend, signer/claim state, no-clobber outputs, public delivery, or production state. Never re-run approval-consuming, metered, ambiguous-effect, or production commands; verify their immutable receipts, exact source bindings, and terminal classifiers instead. Missing or incoherent receipt evidence is an `AUDIT_GAP`, not permission to dispatch again. Surface last ~10 lines + exit code for safe reruns and exact receipt paths/hashes for one-shot commands.
5. **Spot-check verifiable acceptance criteria** across all phases:
   - "File X exists" / "Function Y exported" / "Config key Z set" / "No `console.log` in app code" → re-check via `ls`/`grep`/`cat`.
   - "Screenshot showed X" / "Manual smoke test passed" / non-deterministic checks → mark `trust-prior-verify`, don't re-run.
5b. **Deliverable check** — for each phase block in `$PACKAGE_ROOT/ROADMAP.md`, parse the `**Deliverables:**` bullets. For every bullet that names a file path or glob:
   - Resolve the deliverable to exactly one owning repository from `CONTRACT.json.architecture.repo_baselines`; use that entry's absolute `root` and exact `baseline_sha`. Ambiguous, missing, non-Git, or invalid ownership fails with exit 2 for Git-backed goals.
   - From the owning repository root, run `bash "$PACKAGE_ROOT/scripts/repo-state.sh" deliverable <that repository's baseline_sha> "<repository-relative path>"`. It compares the **complete working tree** (committed + staged + unstaged + deleted) against the baseline and detects untracked new files separately, printing `present — <evidence>` (exit 0), `missing` / `deleted` (exit 1), `invalid baseline` (exit 2), or `unchanged — existed before baseline` (exit 3). Only contracts with no declared Git implementation root may use filesystem existence fallback. Strategy: complete-working-tree comparison helper.
   - `missing`/`deleted` (exit 1), `invalid baseline` (exit 2), or `unchanged pre-existing` (exit 3) → `AUDIT_GAP: phase <N> deliverable "<bullet>" not proven as delivered by this run`, unless the roadmap explicitly marks that deliverable as pre-existing / verification-only.
   - This is repository ground truth, not transcript self-report — it catches the "agent said done but didn't ship" case the per-phase VERIFY cannot, even when the run never committed.
6. Print `AUDIT_VERIFY` with each phase's status, each command's exit, each criterion's pass/fail/trust-prior + evidence, and a `Deliverables:` block summarizing the step-5b check (`<deliverable>: present|missing` lines).

7. Run `RPD_FINAL_REVIEW`. If it decides `audit-fix-needed`, treat it like an audit gap and write `$PACKAGE_ROOT/phases/audit-rpd-fix-<round>.md`. If it decides `handoff`, print `AUDIT_HANDOFF`, update `$PACKAGE_ROOT/out/runtime/STATUS.md` to `BLOCKED`, and stop.

### If gaps found

1. Print `AUDIT_GAPS` with the list.
2. Write `$PACKAGE_ROOT/phases/audit-fix-<round>.md` — a focused fix spec that targets only the failing criteria. Forbid scope creep. Use the affected phases' original VERIFY as the success gate.
3. Execute the fix spec inline (same agent, same `/goal`, same per-criterion 3-strike protocol from regular phases).
4. On fix success: loop back to step 1 of the audit (round + 1).
5. On 3rd round's audit failure: print `AUDIT_HANDOFF` (full gap history, suggested next move), update `$PACKAGE_ROOT/out/runtime/STATUS.md` to `BLOCKED`, stop. Do **not** print `SUPERGOAL_RUN_COMPLETE`.

### If zero gaps

1. Before printing terminal markers, update `$PACKAGE_ROOT/out/runtime/STATUS.md`: set `phase: DONE`, `active_todo: none`, `goal_complete: yes`, and the final evidence pointer; mark all TODO items terminal, finish `CHECKS.md` and `REVIEW.md`, and append a terminal event to `RUN_LOG.md`. This disk state is the control-plane proof that prevents later stale `/goal` continuations from re-opening a completed run.
2. Compute `audit coverage`: `re_verified / (re_verified + trust_prior)` as a percentage. `re_verified` = criteria with `pass` from step 5 + deliverables marked `present` from step 5b. `trust_prior` = criteria marked `trust-prior-verify`.
3. Verify delivery receipts by owner/stage: if the SuperGoal declares `send-review-md-files.sh`, `$PACKAGE_ROOT/out/review-md-files-delivery-receipt.json` should exist with `ok=true`, `sent=true`, `kind=startup-files`, `pack_version=startup_pack_v4`, exactly `THINKING.md`, `ROADMAP.md`, and `LAUNCH_GOAL.md`, and an exact three-entry file→message-ID map ending in `LAUNCH_GOAL.md`; if it is missing after launch, record an `AUDIT_GAP` but do not block product completion on a planner dispatch artifact. If final artifact delivery is declared, `$PACKAGE_ROOT/out/final-artifacts-delivery-receipt.json` must exist with `ok=true` and `sent=true`; missing or false final delivery blocks terminal completion.
4. Print `AUDIT_COMPLETE` (rounds, phases re-verified, commands re-run clean, criteria pass / trust-prior counts, **audit coverage %**).
5. Print `SUPERGOAL_RUN_COMPLETE` with the 5-line summary, then `Goal complete: yes`. If `trust_prior / (re_verified + trust_prior)` > **30%**, prepend a one-line honesty banner: `⚠ Audit coverage: <re_verified> re-verified, <trust_prior> (<pct>%). Eyeball UI/UX before merging.` Below 30%, print the same coverage line without the warning prefix.

## Failure recovery (3-strike)

The 3-strike loop applies only to failures proven to occur before any protected or ambiguous effect. A post-effect failure is terminal for that command authority: do not retry it, do not create a fix-spec replay, and recover read-only from receipts/state. If effect occurrence cannot be disproved, classify it as post-effect and stop that authority fail-closed.

### First failure of any acceptance criterion

1. Print `FAILURE_PROBE` (phase, failed criterion, what was tried, root-cause hypothesis).
2. Append the probe to `$PACKAGE_ROOT/out/runtime/RUN_LOG.md`, set the exact blocker/attempt in `STATUS.md`, and keep the claimed TODO item `in_progress`.
3. **Auto-retry the same phase once only when the failure is proven pre-effect and every command to repeat is local/read-only/idempotent.** Inject the probe as a "Previous attempt failed because: …" preamble. Otherwise record terminal authority consumption or ambiguity and do not advance.

### Second failure (auto-retry also failed)

1. Print `FAILURE_ESCALATE`.
2. Write a focused **fix spec** at `$PACKAGE_ROOT/phases/phase-N.fix.md`. The fix spec:
   - Targets only the failing criterion.
   - Forbids scope creep ("do not touch unrelated files").
   - Ends with the original phase's VERIFY block as the success gate.
3. Execute the fix spec inline (same agent, same `/goal` — no new dispatch) only for proven pre-effect/local failures. A fix spec may repair code or evidence, but it never authorizes replay of a consumed or ambiguously attempted protected command.
4. On fix success: re-run the original phase's VERIFY; on pass, advance to N+1.
5. On fix failure: proceed to third-failure handling.

### Third failure (fix spec also failed)

1. Print `FAILURE_HANDOFF`: failing criterion, full probe history (three attempts), suggested next move.
2. Update `$PACKAGE_ROOT/out/runtime/STATUS.md` with `phase: BLOCKED`, mark the claimed TODO item `blocked` with the exact reason, and append the terminal failure to `RUN_LOG.md`.
3. Stop attempting. The user takes the wheel. The `/goal` condition will not be satisfied; surface the handoff clearly so the host evaluator and user both see it.

## Mid-run interruption

If the user sends any message during the run:
- If it is a correction/frustration signal about weak stops or fake blockers, apply it immediately, reassess the blocker, and continue from `$PACKAGE_ROOT/out/runtime/STATUS.md` unless a real safety gate remains.
- If it changes scope or introduces a real new risk, pause at the next safe boundary, update the phase spec/state, and continue or ask only for the smallest missing approval.
- Do not pause merely to ask whether to resume.

## Memory writeback rules

Short version:

- Save anything non-obvious a future Supergoal run on a similar task would benefit from.
- Frontmatter: `name`, `description`, `metadata.type` (feedback / project / reference / user).
- Link from `MEMORY.md`.
- Final phase always writes a `project_<slug>.md` memory.
- Never save secrets, transient task details, or ephemeral state.

## Required transcript blocks

Exact required block names:
- `SUPERGOAL_PHASE_START`
- `SUPERGOAL_PHASE_VERIFY`
- `RPD_PHASE_REVIEW` when required
- `MEMORY_SAVED`
- `SUPERGOAL_PHASE_DONE`
- `SUPERGOAL_TURN_YIELD`
- `AUDIT_START` / `AUDIT_VERIFY` / `RPD_FINAL_REVIEW` / `AUDIT_GAPS` / `AUDIT_COMPLETE` / `AUDIT_HANDOFF`
- `SUPERGOAL_RUN_COMPLETE`
- `FAILURE_PROBE` / `FAILURE_ESCALATE` / `FAILURE_HANDOFF`
