# chip-supergoal execution protocol

This file is read by the executing agent at the start of the single `/goal` session and followed throughout. It is the operating manual for the autonomous run.

## The loop

Repeat inside the same `/goal` run until `SUPERGOAL_RUN_COMPLETE` is printed or a real safety/approval blocker stops execution. **Chip mode: do not stop at numbered phase boundaries.** `SUPERGOAL_PHASE_DONE` is a checkpoint, not a reason to yield. Continue immediately into the next phase/audit while tool budget and safety allow.

Weak blockers are forbidden. A private proof action that is part of the requested verification — for example a private DM smoke/readback to Chip's own bot, local tests, read-only inspections, usage/log queries, report writes, or repo cleanup — is not an approval blocker by itself. Only the real gates listed below may stop the run.

**File-first runtime rule:** manifested `.supergoal/STATE.md` and `.supergoal/runtime-seed/*.md` are immutable compiler seeds. Before every run, execute `bash .supergoal/scripts/init-runtime.sh .supergoal`; it atomically initializes the mutable bundle under `.supergoal/out/runtime/`, verifies an existing bundle, and never overwrites live state. Mutable coordination lives only under `.supergoal/out/runtime/`, which is excluded from manifest drift checks. Never edit manifested seeds or `MANIFEST.json`.

1. Read mutable state in this order: `.supergoal/out/runtime/STATUS.md`, `TODO.md`, `PLAN.md`, relevant sections of `MEMORY.md`, then the latest entries in `RUN_LOG.md`. Use `CHECKS.md` and `REVIEW.md` as the verification and review ledgers.
   - If `STATUS.md` says `phase: AUDIT`, skip numbered phases and run the **Final audit** below.
   - If it says `BLOCKED_BY_APPROVAL`, `READY_FOR_DELETE_APPROVAL`, or another explicit human/provider approval gate, first reassess whether the blocker is real under the weak-blocker rules above. If it is fake/over-broad, supersede it in `STATUS.md` and append the reason to `RUN_LOG.md`. If it is real, stop the loop. Do not re-run checks or restate the same approval card on repeated continuations.
   - Files are not automatically injected into subagents. Every delegation must include the package workdir, all seven absolute runtime paths, one claimed TODO ID, and the read/update contract.
2. Read `.supergoal/LOOP_DESIGN.md` when present. Treat it as the execution harness: host/reviewer/judge roles, verification gates, state checkpoints, stop/budget limits, boundaries, egress/redaction, recovery, and ASCII preview. If the file is missing for an older package, continue compatibly but record the gap in `STATUS.md` and `RUN_LOG.md`; do not invent a parallel loop.
3. Read `.supergoal/phases/phase-<zero-padded N>.md` (for example, phase 1 is `phase-01.md`). This is your full work spec. Compiled packages use two-digit phase filenames; do not look for `phase-1.md`.
4. Claim exactly one stable phase ID in `TODO.md`: change it from `pending` to `in_progress`, set one owner, and update `STATUS.md` with the same active TODO before mutating project files. If another owner already holds it, stop as a single-writer conflict.
5. Print `SUPERGOAL_PHASE_START` with the spec's metadata (phase number, name, task, mandatory commands, acceptance count, evidence types, dependencies).
6. Print `SUPERGOAL_STATUS` for human readability: current phase, percent, status, current action, check summary, latest evidence, and next step. This is not completion proof and does not replace the runtime files or formal markers.
7. Do the work described in the spec. Run mandatory commands. Surface evidence into the transcript (command output last ~10 lines + exit code; file listings; key diff excerpts).
8. Print `SUPERGOAL_PHASE_VERIFY`: each acceptance criterion `pass|fail` with evidence; engineering checks (build/typecheck/lint/tests); **cleanliness checks** — run `bash .supergoal/scripts/repo-state.sh added-lines <Baseline ref>` (the complete set of added/new lines since baseline, **including uncommitted and untracked work**) and grep it for stack-specific debug patterns — `console.log`/`console.error` for JS/TS; `print(`/`pprint(` for Python; `print(`/`dump(` for Swift; `fmt.Println`/`log.Println` for Go; session TODO/FIXME added this phase; dead imports added; files changed count via `bash .supergoal/scripts/repo-state.sh changed-files <Baseline ref> | wc -l`; notable diff one-liners. Any non-zero cleanliness count triggers the same 3-strike treatment as a failed criterion unless the phase spec explicitly declares a `Cleanliness override:` line. Record every criterion/command result and evidence pointer in `CHECKS.md`; do not leave transcript-only proof.
9. **RPD phase review.** If the phase spec declares `RPD required: yes` or the phase touches a risky area, run `RPD_PHASE_REVIEW`. Append findings, evidence tier, mutation/checked-holds decision, and verdict to `REVIEW.md`. Fix any gap before `SUPERGOAL_PHASE_DONE`.
10. **Memory writeback check.** Write task-local verified facts, decisions, constraints, and mistakes to avoid into `.supergoal/out/runtime/MEMORY.md`; do not store raw transcripts, secrets, or temporary progress. If a non-obvious reusable lesson should survive this project, also write it under the detected MEM_DIR and link it from the runtime memory. Print `MEMORY_SAVED: <name>` or `MEMORY_SAVED: none`.
11. Print `SUPERGOAL_PHASE_DONE`. Transactionally update the runtime bundle: mark phase N `done` in `TODO.md`; set the next phase or `AUDIT` in `STATUS.md`; append one evidence-bound event to `RUN_LOG.md`; ensure `CHECKS.md` and `REVIEW.md` reflect the same outcome. If any write fails, keep the phase incomplete and repair state before continuing.
12. **Continue, don't courtesy-yield.** After runtime writeback, immediately read the next phase or enter `AUDIT`. Do not print `SUPERGOAL_TURN_YIELD` solely because a phase ended. If a real gate/blocker is hit, record it in `TODO.md`, `STATUS.md`, and `RUN_LOG.md`, then print the blocker once and stop.
13. When `STATUS.md` says `phase: AUDIT`, run the **Final audit** below. Planning review delivery is a planner dispatch gate; if the user already launched the goal, a missing `review-md-files-delivery-receipt.json` is an `AUDIT_GAP`/warning to report, not a product-completion blocker. Final artifact delivery receipts are blocking only when final-file delivery was requested. Then print `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE` with a 5-line summary. The `/goal` condition is satisfied only after product verification, coherent terminal runtime files, required final delivery receipts, and final markers exist.

## Dev-history hardening gates

These gates come from repeated Dev-chat incidents and override vague convenience:

- **Continuation over status-only:** if `.supergoal/out/runtime/STATUS.md` is not `DONE` or truly `BLOCKED`, continue the current phase/audit from disk. Do not answer only with a status report when work can safely continue. Do not invent approval blockers for private verification, local checks, read-only probes, usage/log inspection, or requested repo cleanup.
- **Gateway restart/autoresume:** after restart, withheld autoresume, or repeated `/goal resume`, inspect `.supergoal/out/runtime/STATUS.md`, active goal identity, and the last phase marker. Resume safely; do not create a new root unless the state identity is ambiguous or the user explicitly asks for a clean SuperGoal.
- **Retrieval-before-ask:** before asking for keys, wallet refs, prior artifacts, package paths, docs, or approvals the user says already exist, search `.supergoal/`, repo docs, local ignored overlays, session history, relevant skills, and Telegram history when available. If missing, name what was checked.
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

If decision is `audit-fix-needed`, write `.supergoal/phases/audit-rpd-fix-<round>.md`, execute it inline, and then rerun the audit round. If decision is `handoff`, print `AUDIT_HANDOFF`, update `.supergoal/out/runtime/STATUS.md` to `BLOCKED`, and do not print `SUPERGOAL_RUN_COMPLETE`.

## Final audit (Stage 10 — runs after the last phase, before completion)

Per-phase VERIFY blocks are self-reports. The audit closes that loophole by re-validating against the **original** `ROADMAP.md`, not against this run's own self-reports. The audit runs up to 3 rounds; on the 3rd round's failure, `AUDIT_HANDOFF`.

### Audit steps (one round)

1. Print `AUDIT_START` (round number, total phase count, criteria count, deduplicated mandatory commands to re-run).
2. Re-read `.supergoal/ROADMAP.md` and pull every phase's acceptance criteria fresh from the original plan.
3. **Phase completeness:** scan the transcript for one `SUPERGOAL_PHASE_DONE` per phase 1..N. Any missing = an `AUDIT_GAP`.
4. **Re-run aggregated mandatory commands** once each (build / typecheck / lint / full test suite — whatever the union of all phases' mandatory commands is, deduplicated). Surface last ~10 lines + exit code. Non-zero exit = an `AUDIT_GAP`.
5. **Spot-check verifiable acceptance criteria** across all phases:
   - "File X exists" / "Function Y exported" / "Config key Z set" / "No `console.log` in app code" → re-check via `ls`/`grep`/`cat`.
   - "Screenshot showed X" / "Manual smoke test passed" / non-deterministic checks → mark `trust-prior-verify`, don't re-run.
5b. **Deliverable check** — for each phase block in `.supergoal/ROADMAP.md`, parse the `**Deliverables:**` bullets. For every bullet that names a file path or glob:
   - Read `baseline_ref:` from `.supergoal/out/runtime/STATUS.md`.
   - Run `bash .supergoal/scripts/repo-state.sh deliverable <baseline-ref> "<path>"`. It compares the **complete working tree** (committed + staged + unstaged + deleted) against the baseline and detects untracked new files separately, printing `present — <evidence>` (exit 0), `missing` / `deleted` (exit 1), `invalid baseline` (exit 2), or `unchanged — existed before baseline` (exit 3). In a git repo, invalid baselines fail closed; only non-git workspaces use filesystem existence fallback. Strategy: complete-working-tree comparison helper.
   - `missing`/`deleted` (exit 1), `invalid baseline` (exit 2), or `unchanged pre-existing` (exit 3) → `AUDIT_GAP: phase <N> deliverable "<bullet>" not proven as delivered by this run`, unless the roadmap explicitly marks that deliverable as pre-existing / verification-only.
   - This is repository ground truth, not transcript self-report — it catches the "agent said done but didn't ship" case the per-phase VERIFY cannot, even when the run never committed.
6. Print `AUDIT_VERIFY` with each phase's status, each command's exit, each criterion's pass/fail/trust-prior + evidence, and a `Deliverables:` block summarizing the step-5b check (`<deliverable>: present|missing` lines).

7. Run `RPD_FINAL_REVIEW`. If it decides `audit-fix-needed`, treat it like an audit gap and write `.supergoal/phases/audit-rpd-fix-<round>.md`. If it decides `handoff`, print `AUDIT_HANDOFF`, update `.supergoal/out/runtime/STATUS.md` to `BLOCKED`, and stop.

### If gaps found

1. Print `AUDIT_GAPS` with the list.
2. Write `.supergoal/phases/audit-fix-<round>.md` — a focused fix spec that targets only the failing criteria. Forbid scope creep. Use the affected phases' original VERIFY as the success gate.
3. Execute the fix spec inline (same agent, same `/goal`, same per-criterion 3-strike protocol from regular phases).
4. On fix success: loop back to step 1 of the audit (round + 1).
5. On 3rd round's audit failure: print `AUDIT_HANDOFF` (full gap history, suggested next move), update `.supergoal/out/runtime/STATUS.md` to `BLOCKED`, stop. Do **not** print `SUPERGOAL_RUN_COMPLETE`.

### If zero gaps

1. Before printing terminal markers, update `.supergoal/out/runtime/STATUS.md`: set `phase: DONE`, `active_todo: none`, `goal_complete: yes`, and the final evidence pointer; mark all TODO items terminal, finish `CHECKS.md` and `REVIEW.md`, and append a terminal event to `RUN_LOG.md`. This disk state is the control-plane proof that prevents later stale `/goal` continuations from re-opening a completed run.
2. Compute `audit coverage`: `re_verified / (re_verified + trust_prior)` as a percentage. `re_verified` = criteria with `pass` from step 5 + deliverables marked `present` from step 5b. `trust_prior` = criteria marked `trust-prior-verify`.
3. Verify delivery receipts by owner/stage: if the SuperGoal declares `send-review-md-files.sh`, `.supergoal/out/review-md-files-delivery-receipt.json` should exist with `ok=true`, `sent=true`, and `pack_version=review_pack_v2`; if it is missing after launch, record an `AUDIT_GAP` but do not block product completion on a planner dispatch artifact. If final artifact delivery is declared, `.supergoal/out/final-artifacts-delivery-receipt.json` must exist with `ok=true` and `sent=true`; missing or false final receipt blocks completion.
4. Print `AUDIT_COMPLETE` (rounds, phases re-verified, commands re-run clean, criteria pass / trust-prior counts, **audit coverage %**).
5. Print `SUPERGOAL_RUN_COMPLETE` with the 5-line summary, then `Goal complete: yes`. If `trust_prior / (re_verified + trust_prior)` > **30%**, prepend a one-line honesty banner: `⚠ Audit coverage: <re_verified> re-verified, <trust_prior> (<pct>%). Eyeball UI/UX before merging.` Below 30%, print the same coverage line without the warning prefix.

## Failure recovery (3-strike)

### First failure of any acceptance criterion

1. Print `FAILURE_PROBE` (phase, failed criterion, what was tried, root-cause hypothesis).
2. Append the probe to `.supergoal/out/runtime/RUN_LOG.md`, set the exact blocker/attempt in `STATUS.md`, and keep the claimed TODO item `in_progress`.
3. **Auto-retry the same phase once.** Inject the probe as a "Previous attempt failed because: …" preamble. Do not advance.

### Second failure (auto-retry also failed)

1. Print `FAILURE_ESCALATE`.
2. Write a focused **fix spec** at `.supergoal/phases/phase-N.fix.md`. The fix spec:
   - Targets only the failing criterion.
   - Forbids scope creep ("do not touch unrelated files").
   - Ends with the original phase's VERIFY block as the success gate.
3. Execute the fix spec inline (same agent, same `/goal` — no new dispatch).
4. On fix success: re-run the original phase's VERIFY; on pass, advance to N+1.
5. On fix failure: proceed to third-failure handling.

### Third failure (fix spec also failed)

1. Print `FAILURE_HANDOFF`: failing criterion, full probe history (three attempts), suggested next move.
2. Update `.supergoal/out/runtime/STATUS.md` with `phase: BLOCKED`, mark the claimed TODO item `blocked` with the exact reason, and append the terminal failure to `RUN_LOG.md`.
3. Stop attempting. The user takes the wheel. The `/goal` condition will not be satisfied; surface the handoff clearly so the host evaluator and user both see it.

## Mid-run interruption

If the user sends any message during the run:
- If it is a correction/frustration signal about weak stops or fake blockers, apply it immediately, reassess the blocker, and continue from `.supergoal/out/runtime/STATUS.md` unless a real safety gate remains.
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
