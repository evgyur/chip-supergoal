---
name: chip-supergoal
description: "Use for SuperGoal planning. Native-send exactly 3 files with verified Telegram message IDs before claiming ready. Builds strict executable /goal packages with Principal+ planning and Senior gates."
argument-hint: <describe what must be built, fixed, shipped, or planned>
---
# chip-supergoal
`chip-supergoal` is a planner/compiler. It turns a non-trivial request into a disk-backed `.supergoal/` package and one standard Hermes `/goal` handoff; GoalManager executes and verifies it.
## Chip override: bind the outcome, never the path
Bind only outcome, hard boundaries, and acceptance. SHA, releases, steps, models, and tools stay internal unless Chip asks for an exact candidate. Their changes never justify a sibling or repeated `/goal`; replace the goal only when its outcome or boundaries change.
## Principal+ contract
Use this root as the controller. Heavy detail lives in references and templates.
1. **Simple core, modular depth** — root owns triggers, invariants, stage order, artifact list, and reference dispatch. Incident lessons live in references.
2. **Plan-only + honest-state boundary** — this skill may inspect, research, validate planning artifacts, and run preflight characterization, but it must not execute numbered implementation phases. When Chip says “make SuperGoal,” emit a canonical package with `PROTOCOL.md`, pending `STATE.md`, validated phase specs, and one launch handoff. Never manually implement first and then backfill completed phases, `FINAL_AUDIT`, `AUDIT_COMPLETE`, `SUPERGOAL_RUN_COMPLETE`, or a no-op `Current phase: COMPLETE`; use `references/planner-executor-state-hygiene.md`.
3. **One launch surface** — create exactly one human-facing launch body in `LAUNCH_GOAL.md`. Do not hide alternate launch bodies in `ROADMAP.md` or `THINKING.md`.
4. **One standard `/goal`, not a chain** — the executor reads `STATE.md` and continues until all phases plus audit complete. When one goal must cross a hard foundation-selection boundary, it may supervise multiple physically separate Project Flow runs; defer materializing the downstream DecisionPackage/`STATE.yaml` until an atomic evidence-backed admission guard proves the upstream Flow terminal. See `references/staged-project-flow-runs-in-one-goal.md`.
5. **No false done** — every phase needs real evidence; final completion requires re-reading the original `ROADMAP.md`, re-running aggregate checks, checking deliverables, `RPD_FINAL_REVIEW`, `AUDIT_COMPLETE`, then `SUPERGOAL_RUN_COMPLETE`. For a goal whose finish line is a working production system, a verified rollback is safe failure evidence—not acceptance evidence: keep the activation phase blocked/failed or route it back for repair until the declared live behavior actually passes.
6. **Risky work gets Senior Gate** — auth, payments, secrets, production, migrations, gateways, cron/model routing, private data, destructive actions, public launches, and recurring bugs require evidence-tiered RPD/Senior review.
6a. **Mandatory post-draft Senior challenge** — immediately after the first complete plan draft, critically re-evaluate every decision with this pressure test: `Критически оцени все свои решения. Это план на 100 из 100 или его можно усилить? Мне не нужен план внедрения ради внедрения. Senior-план должен допускать: «мы проверили и не внедряем».` Record a justified score, concrete weaknesses, and one verdict: `implement`, `strengthen-and-rereview`, or `do-not-implement`. A `do-not-implement` verdict is a valid successful planning outcome: preserve the evidence and rationale, but do not emit `READY_TO_DISPATCH` or launch `/goal` unless Chip changes the desired outcome.
6b. **Ponytail scope gate** — before planning lock the smallest `direct-work`/SuperGoal budget; after drafting shrink once inside RPD, never in another review. See `references/ponytail-scope-gate.md`.
7. **Telegram delivery is blocking, automatic, and exactly three files** — every Chip-facing SuperGoal sends `startup_pack_v4` into the exact current Telegram chat/topic as three separate native documents, in this order: `THINKING.md`, `ROADMAP.md`, `LAUNCH_GOAL.md`. No `RESEARCH.md`, loop/state/protocol files, JSON, phase specs, archives, scripts, or supporting artifacts are sent to chat by default. Those remain inside the disk package.
8. **The three-file rule is receipt-enforced** — resolve the target, then run `templates/delivery/send-review-md-files.sh`. `startup_pack_v4` is exactly three files: `THINKING.md`, `ROADMAP.md`, `LAUNCH_GOAL.md`; each needs a real `message_id` and readback with `has_media=true` plus `media_type=MessageMediaDocument`. **Never manually call `hermes send --file` / `-f` for SuperGoal delivery**. Resends use the canonical sender with `SUPERGOAL_DELIVERY_RUN_ID=resend-<UTC timestamp>`. Any mismatch is `SUPERGOAL_REVIEW_FILES_BLOCKED`; full contract: `references/telegram-launch-and-delivery.md`.
9. **Normal speed by default** — generated SuperGoals must not enable Hermes `/fast` or persist `agent.service_tier: priority` unless Chip explicitly opts in for that run. Fast mode and reasoning effort are independent; keep the persistent default `agent.service_tier: normal`.
10. **No false resume** — never emit `Goal resumed`, `executing`, or equivalent from a continuation wrapper alone. A resume claim requires evidence that an executor is active now: a running foreground/background process, an enabled durable continuation job with a queued/running tick, or a real phase mutation plus verification in the current turn. If execution cannot continue in-session, install/verify the durable continuation mechanism before promising continuity, record its handle in mutable runtime state, and label `queued` separately from `running`. A chat message that merely says “send any message to continue” is paused/on-demand, not continuous execution.
    - `↻ Continuing toward goal (N/M)` proves only a continuation decision, not execution. Require a later `turns_used`/`last_turn_at` advance, a live executor, or verified runtime mutation; otherwise report `continuation marker emitted; execution not proven / goal stranded`. For async review, yield once and wait for callback/deadline. Full rules: `references/supergoal-goal-pipeline-turn-yield.md`.
11. **One mutable worktree, one writer** — continuations, GoalManager, cron, delegates, and CLIs must not edit one checkout concurrently. A sibling-modification warning is a hard stop: wait, re-read, reconcile, and rerun. See `references/concurrent-continuation-single-writer.md`. **Planner stop-loss:** load `references/planner-runaway-stop-loss.md`.
## Use when
Use for:
- `/chip-supergoal <task>` or “make SuperGoal / SG / ТЗ package”
- “plan and ship X”, autonomous feature/refactor/redesign planning
- brownfield work where codebase reality, tests, deployment, or recovery matter
- greenfield products/systems where stack, research, architecture, and phase boundaries matter
- standing SuperGoal continuation/repair where `STATE.md` exists
- explicit successor planning only when Chip changes the desired outcome/hard boundaries or directly asks for a **new SuperGoal**. Implementation divergence, changed HEAD/dirty patch, review findings, stale evidence, or a stalled executor are not reasons to replace the goal: retire competing writers if needed, repair the existing runtime/package sidecar, refresh internal evidence, and continue under the same semantic goal.
- repeated standing-goal continuations after `AUDIT_COMPLETE`: verify completion once from `STATE.md`/final audit artifacts if not already fresh in-session, then stop with `SUPERGOAL_RUN_COMPLETE`; do not re-run phase loops, keep re-testing, or repeat long identical completion reports on every auto-resume unless the user explicitly asks for a re-audit or new work. After one fresh completion proof in the same session, answer duplicate wrappers with one compact stop line and explicitly say the auto-continuation/standing goal should be closed. If the same wrapper repeats again in the same chat with no new instruction, do not call tools again, do not mention approval gates repeatedly, and emit only the compact complete/stop line.
- skill/library hardening work that needs phases, review, and final audit
Do **not** use for tiny edits, one factual answer, pure copywriting, or a task whose safest path is direct execution in the current session. For those, say it is too small for SuperGoal and use the direct workflow.
**Audit vs implementation correction:** resolve the request from the full Telegram/conversation sequence, not the latest sentence alone. If Chip first directs a concrete SuperGoal change and then asks “у нас так устроен?” or “переделал?”, treat the question as a completion check on that requested implementation, not permission to stop at a conceptual comparison. For safe skill/compiler work, patch the compiler/protocol/tests, compile and strict-validate a real package, initialize the runtime twice to prove no overwrite, run the full suite, and only then answer `ready`. A proposed architecture, audit verdict, emoji, or presence acknowledgement is not completion. If the sequence genuinely asks for read-only analysis, keep it read-only.
## Human gates
Only two gates are allowed by default:

1. **Stage 1 clarifying questions** — only for true material gaps that tools cannot answer. Short pointer follow-ups like “вот это”, “это”, “читай сообщение”, “make supergoal”, or a voice/reply after a visible context block are not a reason to loop on clarification or invent a subject: use the current conversation/Telegram context first, and only ask if the subject is still unrecoverable. If Chip corrects that the wrong source was used, immediately recover the pointed message/reply/entities/media via gateway context or `telegram-chip` and regenerate the package around that source; do not defend the prior assumption. A SuperGoal compiled around the wrong class (for example a generic concierge-hook plan when the pointed source is a trading/copy task) is a planner failure. Include a scope check when the user's example could be mistaken for the whole mission: if Chip asks for a class-level system (“all future lessons and meetings”, “the whole publisher”, “make this reliable”), do not compile a narrow SuperGoal around the latest example (`lesson 4`, one bug, one artifact). Treat the example as a regression fixture inside a broader roadmap.
2. **Stage 6 plan review** — after the first complete draft, run the mandatory post-draft Senior challenge before showing anything as launchable. Show the reviewed package summary and wait for explicit go/no-go only when the verdict is `implement` or `strengthen-and-rereview` has already been resolved. If the verdict is `do-not-implement`, present the evidence-backed recommendation and stop without `READY_TO_DISPATCH`; do not manufacture implementation phases merely to complete the SuperGoal shape. If Chip then says “убери все апрувалы”, “можно сразу в прод”, or equivalent about a launchable visible package, treat it as Stage-6 approval plus standing authorization for rollback-safe beta/prod app rollout; remove redundant environment gates across all package artifacts and keep at most one bounded manifest for concrete high-risk exceptions. See `references/bounded-manifest-no-internal-approvals.md`.
Everything else should be autonomous and evidence-backed.
## Generated artifacts
Write under `$SUPERGOAL_ROOT` (normally `<repo>/.supergoal/`):

- `THINKING.md` — goals, constraints, risks, dependencies, assumptions, memory hits, tools/skills used.
- `RESEARCH.md` — only when research gates run.
- `LOOP_DESIGN.md` — measurable outcome plus the bounded execution/review harness.
- `ROADMAP.md` — decision package, phase map, measurable acceptance criteria, mandatory commands, evidence requirements.
- `STATE.md` — immutable compatibility state seed; `runtime-seed/{PLAN,TODO,MEMORY,STATUS,RUN_LOG,CHECKS,REVIEW}.md` seeds the file-first mutable bundle under `out/runtime/` through `scripts/init-runtime.sh` without overwriting live state. Full contract: `references/file-first-runtime-state.md`.
- `PROTOCOL.md` — self-contained executor loop copied from `templates/PROTOCOL.md`.
- `LAUNCH_GOAL.md` — the only artifact containing a launch line beginning exactly `SUPERGOAL_GOAL_BODY:`.
- `phases/phase-NN.md` — one strict, two-digit zero-padded phase spec per phase (`phase-01.md`, `phase-02.md`, …), validated by `scripts/validate-phase.sh`.
- `scripts/repo-state.sh` — deliverable/diff/cleanliness helper copied from this skill.
- Compiled packages must also carry their executable runtime (`scripts/`, `lib/`, `spec/`, `templates/PROTOCOL.md`, and delivery templates) so package-local `sgctl` and validators work without the source skill checkout. Runtime `__pycache__`/`.pyc` files are excluded from manifest drift checks.
- delivery scripts/receipts for `startup_pack_v4`: exactly `THINKING.md`, `ROADMAP.md`, and `LAUNCH_GOAL.md`.
- `out/<goal-id>.complete-supergoal.tar.gz` — optional internal/portable bundle containing exactly the compiler manifest's immutable `artifacts`, every mutable path that currently exists in the compiled package, and `MANIFEST.json`, with preserved modes and no runtime `out/` recursion. It is not part of default Telegram delivery.
- `out/<goal-id>.complete-supergoal-package-receipt.json` — archive SHA-256, entry count, secret-scan result, and extracted strict-validation result when the optional archive is built.

See `references/artifact-schemas.md` for exact schemas and `templates/LAUNCH_GOAL.md` for the launch contract.

## Procedure

| Stage | Action | Evidence |
|---|---|---|
| 0 | Resolve live skill dir, preload memory, detect tools/skills, detect resume state. | skill path + context notes |
| 1 | Intake. Brownfield asks 0–2 questions; greenfield batches up to 4 until material gaps close. | assumptions/gaps list |
| 2 | Recon. Run stack/env/repo scripts and read outputs. | 5-line stack/commands/risk summary |
| 2.5 | **Ponytail:** choose direct work vs SuperGoal; lock the smallest budget. | scope verdict |
| 3 | Define a measurable outcome, then run research + architecture gates. Use skill-first research when current facts matter. | `CONTRACT.json.loop.outcome_definition`; `THINKING.md`; optional `RESEARCH.md` |
| 3.5 | **Loop Design Gate.** Design the execution harness before roadmap compilation: Sol ownership, per-phase `direct|shawl` routing, bounded Luna review, verification gates, state, stop, budget, boundaries, egress/redaction, failure recovery, and ASCII preview. Mutate weak loop specs before launch. | `LOOP_DESIGN.md`; loop health rubric |
| 4 | Decompose into as many phases as the task requires. | phase map with dependencies |
| 5 | Write roadmap, state, protocol, launch goal, and phase specs. | files on disk + phase validation |
| 6 | Run Senior/RPD review and the one-pass `PONYTAIL_FINAL_CHECK` in the same seat. Delete unjustified machinery; never launch a separate Ponytail reviewer. | score + scope check + verdict |
| 6.5 | Preflight smoke: baseline commands, repo state, required files, blockers. | `PREFLIGHT_GREEN` or `PREFLIGHT_RED` |
| 6.6 | **Blocking semantic-review closure.** If any independent/asynchronous package review was dispatched, receive and apply its final verdict before delivery. A pending reviewer is not approval: do not send files, ask for `/goal`, or call the package ready while it runs. Require P0=0/P1=0 on the exact compiled bytes; any later mutation invalidates the verdict. A post-delivery REJECT is a planner MISS and the delivered revision must be treated as never launchable. | final review artifact bound to package hash |
| 7 | Send `startup_pack_v4` as exactly three native Telegram documents: `THINKING.md`, `ROADMAP.md`, then `LAUNCH_GOAL.md` last. Verify the exact three-entry file→message-ID receipt/readback. User replies `/goal` to the last file; planner stops. | `READY_TO_DISPATCH` or blocked state |

Planning rules: `references/core-planning-contract.md` and `references/outcome-definition-and-shawl-luna.md`.
## Executor invariants for generated `/goal`

The generated `PROTOCOL.md` must preserve these exact marker families:

- phase loop: `SUPERGOAL_PHASE_START`, `SUPERGOAL_STATUS`, `SUPERGOAL_PHASE_VERIFY`, `MEMORY_SAVED`, `SUPERGOAL_PHASE_DONE`, `SUPERGOAL_TURN_YIELD`
- preflight: `PREFLIGHT_GREEN`, `PREFLIGHT_RED`, `READY_TO_DISPATCH`
- RPD: `RPD_PLAN_REVIEW`, `RPD_PHASE_REVIEW`, `RPD_FINAL_REVIEW`
- failure recovery: `FAILURE_PROBE`, `FAILURE_ESCALATE`, `FAILURE_HANDOFF`
- audit: `AUDIT_START`, `AUDIT_VERIFY`, `AUDIT_GAPS`, `AUDIT_COMPLETE`, `AUDIT_HANDOFF`
- delivery/approval: `SUPERGOAL_REVIEW_FILES_BLOCKED`, `SUPERGOAL_FILES_SENT`, `BLOCKED_BY_APPROVAL`, `READY_FOR_DELETE_APPROVAL`
- completion: `SUPERGOAL_RUN_COMPLETE`

Official GoalManager execution continues across numbered phases in the same run until final audit, a real safety/approval gate, or a real blocker. It must not stop merely because `SUPERGOAL_PHASE_DONE` was printed. `SUPERGOAL_TURN_YIELD` is a forced-yield/blocker marker, not a courtesy phase boundary. See `references/execution-state-machine.md`.

## Phase spec contract

When generating phase files programmatically, build acceptance criteria and evidence lists as explicit arrays/lists, not strings. A common failure mode is iterating over a string and producing one bullet per character; validation may pass structurally while the phase is unusable. After generation, re-read at least one phase file and verify the bullets are semantic before declaring the package ready.

Acceptance criteria must also be satisfiable **in their own phase** under that phase's mutation/approval authority. Before sealing, execute every mandatory command against the clean baseline and candidate; if a broad gate is baseline-red, compile a Git-derived candidate-delta command plus explicit baseline evidence instead of knowingly shipping a failing command. Candidate-source/package equality belongs before approval; production active-file hash equality, current-symlink/process cwd, service restart, database apply, external delivery, and exchange-fill proof belong in the phase that performs and verifies that side effect. Never put post-deploy evidence in a pre-approval code phase and then silently defer it while marking the phase complete. Use `references/phase-gate-executability.md` and `references/cross-phase-production-evidence-ordering.md`.

For script-backed contracts, add an **executable ABI, Git source-lock, and live-path gate** before launch and again before each risky phase: compare every exact command with the candidate script parser/schema, execute its safe form, trace producer/consumer receipts, prove every bound baseline is a real commit reachable from the declared durable remote ref, and read back the actual install root, immutable release, mutable package root, and contract path. A structurally valid contract with an orphan/unavailable Git SHA, deliverables rendered only in `CONTRACT.json`, a launch file that does not tell the executor to read the contract, stale package roots, a plausible-but-wrong production root, or incompatible CLI flags is not launchable. If discovered after state advancement, stop before mutation and repair the runtime inside the same SuperGoal. Do not compile/redeliver a sibling or require another launch merely because implementation files, HEAD, tests, reviews, manifests, or receipts changed. Exact-candidate invalidation applies only when Chip explicitly requested release of one exact candidate; otherwise refresh those executor-owned artifacts internally and continue toward the unchanged outcome. Full procedure: `references/executable-contract-interface-and-live-path-revision.md`.

Every phase file must contain:

```text
SUPERGOAL_PHASE_START
Phase: N of TOTAL — <name>
Task: <one-line task>
Execution route: direct|shawl
Mandatory commands: <csv>
Acceptance criteria: <count>
Evidence required: <csv>
Depends on phases: <ids|none>
RPD required: yes|no
RPD focus: security|integration|ux|migration|data-loss|gateway|payments|none
```

Exact headings: `## Work`, `## Acceptance criteria`, `## Mandatory commands`, `## Evidence required`.

Run `bash "$SUPERGOAL_DIR/scripts/validate-phase.sh" <phase-number|phase-file>` for every phase. The copied wrapper must resolve numeric IDs (for example `06`) to package-local phase files, also accept explicit paths, and work when invoked from outside the package cwd. Test the exact form embedded in each phase's mandatory commands.

## RPD / Senior Gate

`chip-supergoal` embeds RPD. Do not invoke external `/rpd` to run this workflow.

- `RPD_PLAN_REVIEW` includes one bounded `PONYTAIL_FINAL_CHECK`; no second reviewer/model/round.
- `RPD_PHASE_REVIEW` runs in generated `/goal` for risky phases or `RPD required: yes`.
- `RPD_FINAL_REVIEW` always runs after `AUDIT_VERIFY` and before `AUDIT_COMPLETE`.
- Findings must mutate `ROADMAP.md`, `THINKING.md`, phase specs, protocol, code/work, or audit-fix specs. Otherwise mark `checked-holds` with evidence tier.

Load `references/rpd-review-gates.md` for the full evidence-tier, severity, overengineering-budget, and principal-review contract.

## Reference dispatch

Load only the matching canonical reference. Start with `references/dispatch-map.md` when the correct reference is not obvious.

Core active references:
- Planning and phase design: `references/core-planning-contract.md`, `references/phase-design.md`, `references/phase-gate-executability.md`, `references/planner-preflight-vs-postphase-commands.md`, `references/external-command-dependency-probes.md`.
- Scope expansion after review/delivery: `references/scope-expansion-after-review-package.md` — preserve the original request, add a source-bound revision, update every semantic plane, invalidate old fingerprints/approvals, recompile fresh, and rebuild the private-safe review bundle.
- Artifact schemas, review pack, deterministic bundles: `references/artifact-boundaries.md`, `references/artifact-schemas.md`, `references/final-audit-packaging.md`, `references/manifest-complete-portable-archive.md`. The manifest-complete reference governs the immutable `artifacts` plus present `mutable_paths` archive inventory and extracted strict validation.
- Execution state, phase closeout, audit, stale/partial continuation: `references/execution-state-machine.md`, `references/phase-completion-ledger-discipline.md`, `references/partial-execution-state-divergence.md`, `references/completed-standing-goal-and-workdir-hygiene.md`. The phase-ledger reference also governs exact shell exit capture, provenance freshness after manifest changes, and honest forced-turn closeout.
- Multi-stage provider deadline/billing phases: `references/request-wide-deadline-and-ambiguous-billing.md` — one monotonic request deadline and spend envelope, real cancellation under custom transports, no unsafe timeout/429 retries, distinct ambiguous/billable accounting, circuit breaking, and idempotent late reconciliation.
- Offline agent/tool evaluation phases: `references/offline-agent-eval-integrity.md` — preserve tool-call identity/order through text-only subcalls, simulate raw long-context occupancy independently of production compaction, and enforce helper-free answer provenance without overstating offline traces as live provider proof.
- Loop, measurable outcome, Shawl/Luna routing, simplicity, and senior review: `references/outcome-definition-and-shawl-luna.md`, `references/ponytail-scope-gate.md`, `references/loop-design-gate.md`, `references/rpd-review-gates.md`, `references/executable-contract-review.md`.
- Telegram three-file launch delivery: `references/telegram-launch-and-delivery.md`, `references/telegram-supergoal-artifact-delivery-correction.md`.
- Production, rollout, approval, canary: `references/production-safety.md`, `references/production-deploy-gates.md`, `references/review-gated-rollout-closure.md`, `references/production-canary-observer-and-artifact-integrity.md`. For production trading/payments/migrations or another live-authority cutover, also load `references/high-risk-live-cutover-semantic-review.md` before sealing.
- Exact release, zero-skip, executable command ABI, and live-path revision gates: `references/release-candidate-zero-skip-and-integrity.md`, `references/executable-contract-interface-and-live-path-revision.md`.
- Private-data and corpus missions: `references/strict-v3-private-execution-hardening.md`, `references/sealed-eval-corpus-and-policy-freeze.md`, `references/private-corpus-controller-hardening.md`.
- Standard `/goal` and staged flows: `references/upstream-goal-compatibility.md`, `references/staged-project-flow-runs-in-one-goal.md`.
- Skill maintenance and self-upgrades: `references/skill-maintenance.md`, `references/architect-plus-v3-upgrade-execution-lessons.md`.
- All specialist and incident routing lives in `references/dispatch-map.md` and `references/INDEX.md`; incidents are forensic unless explicitly dispatched. Add new examples to the governing reference, not root.

## Launch and delivery rules

- `LAUNCH_GOAL.md` is the sole replyable launch file and sole actual `SUPERGOAL_GOAL_BODY:` surface; `ROADMAP.md`, `THINKING.md`, and `PROTOCOL.md` must not duplicate it.
- For a SuperGoal about this skill, keep the generated mission outside the skill root so self-tests see only the launch template.
- Every Chip-facing delivery sends `startup_pack_v4` and nothing else by default: native `THINKING.md`, native `ROADMAP.md`, then native `LAUNCH_GOAL.md` last with a caption telling Chip to reply `/goal`. All other package artifacts stay on disk unless Chip explicitly asks for one.
- A visible `MEDIA:/...` line, filesystem path, link, blank document, extra attachment, or claim that files were attached is not delivery evidence. Run `send-review-md-files.sh`; require hashes and the exact three-entry `{relative_filename: message_id}` proof. Any inventory other than the three canonical files is `SUPERGOAL_REVIEW_FILES_BLOCKED`.
- Before sending, verify the exact chat/topic against `hermes send --list telegram --json`; ambient variables may be stale. Parse each real `message_id`, preserve the three-file order, fetch the messages back, and never duplicate files through final-response `MEDIA:` lines.
- Final artifacts require `SUPERGOAL_FILES_SENT` before `SUPERGOAL_RUN_COMPLETE` when final-file delivery was requested.

## Verification checklist

After editing this skill or generating a package:

```bash
cd <installed-skill-dir>
bash scripts/test.sh
python3 <skills-dir>/create-skill/scripts/skill_workflow_guard.py <installed-skill-dir> || true
```

When validating a generated `.supergoal/` package outside the installed skill directory, the copied `validate-phase.sh` / `validate-loop-design.sh` may call `scripts/sgctl.py`, which imports `chip_supergoal` from the skill's `lib/` tree. Set `PYTHONPATH=<installed-chip-supergoal>/lib` for those validation commands instead of treating `ModuleNotFoundError: chip_supergoal` as a package failure.

Compiler/validator pitfalls:
- `startup_pack_v4` is exactly `THINKING.md`, `ROADMAP.md`, `LAUNCH_GOAL.md`. If package-local receipt validation or delivery code still hardcodes `review_pack_v2` or requires `LOOP_DESIGN.md`, treat it as compiler drift: make validation contract-driven, run the full compiler suite, recompile, then prove strict package validation with the real three-message receipt. Never send a fourth startup attachment to satisfy stale code.
- Phase-boundary ledger edits need a transport-integrity readback, not trust in a multi-file patch preview. Re-read all mutable state files, scan for literal truncation/template markers, prove the previous-phase-done/next-phase-claimed tuple, and repair partial transitions before touching next-phase code. Discover `sgctl validate-package` syntax from package-local `--help`; current packages take the root positionally. Full procedure: `references/phase-completion-ledger-discipline.md`.
- Contract `phases[*].work_items` must be an array of objects with a `text` field. Bare strings crash the current renderer at `w.get(...)`; objects using only `summary` render as Python dict literals in `phase-NN.md`. Normalize each item to `{"text": "semantic work item"}` before `sgctl compile`, then re-read a generated phase to confirm clean bullets.
- For interrupted production activation, post-activation verifier failures, or a follow-on remediation manifest, load `references/rollout-final-audit-lessons.md` before retrying or requesting another approval. Reconcile intent against live fetchback, preserve the lock-bound activator source by SHA, rebuild seeding from current verified live state, derive cron inverse from current prestate, finish canonical-candidate/exact-scope handoff locally, and surface only the final manifest-bound external gate.
- For urgent follow-ons after partial manual execution, use the existing SuperGoal: retire competing writers, reconcile actual HEAD+dirty state internally, eliminate stale predecessor semantics, trace every command input/deliverable, and continue through the same goal path. Do not compile a sibling because implementation diverged.
- Mandatory preflight commands must run successfully against the **current live input shape before sealing**, not merely pass shell syntax. Parse mutable operator registries defensively when a collection may be either a list or an ID-keyed mapping. For commands whose final deliverable is intentionally future-created, separately execute a dependency probe before sealing: under the declared `cwd` and runtime user, verify traversal/read permissions for every external path and evaluate every referenced JSON/key path against the real bytes. A command that expects `service.unit` while the source exposes `runtime.service`, or that points across home-directory permissions unreadable to its declared user, is package-red even if a temporary ACL, compatibility alias, root wrapper, or content shim could make one run pass. Never mutate a bound external source merely to manufacture replayability; repair the contract/source boundary in the running goal, refresh internal candidate evidence, and continue without a sibling or revised launch. Process inventories must also separate source-checkout writers from already-running production services: inventory and hash both, but do not treat an `/opt/.../current` runtime process as a competing checkout editor solely because its name contains `worker`, and never stop a live service under a safe-lane/no-production approval just to make a planner assertion green. Ancestor/self processes must be excluded explicitly. If the exact command fails, repair it inside the current goal and re-run acceptance; do not substitute a similar command as evidence and do not force Chip through another launch. Detailed recipe: `references/executable-preflight-live-shape-and-process-classification.md`.
- For private-data, production, scheduler, messaging, migration, or rollback-sensitive missions, apply the complete pre-dispatch gate in `references/compiler-conformance-and-semantic-closure.md`: probe the actual compiler, bind package/workspace roots, run independent semantic closure until no P0/P1 remains, and prove crash recovery plus mutation-safe final audit. Structural validator green alone is not semantic proof.
- Before compiling a strict v3 contract, prove the selected compiler is v3-capable: output must contain `runtime/STATE.json`, a relocatable `LAUNCH_GOAL.md`, and projection-only `STATE.md`. Quarantine legacy `out/RUNTIME_STATE.md` or compile-time-root output and use the newer verified package-local runtime. Then verify generated review files contain the actual contract semantics; structural validation alone is insufficient. Before dispatch, verify that `THINKING.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `STATE.md`, and optional `RESEARCH.md` render the actual source set, decisions, assumptions, loop limits, approvals, RPD mutations, and honest pending state. Patch the renderer and recompile rather than hand-editing sealed output. Use `references/architect-plus-v3-upgrade-execution-lessons.md` for renderer-contract checks, current `sgctl` validation, validator-driven mutations, research fallback, and reference-catalog maintenance.
- Full `sgctl validate-package` expects a compiler-shaped package with `CONTRACT.json` and `MANIFEST.json`; a hand-written markdown-only package may pass phase/loop validators but fail package validation. For strict packages, write a valid v3 `CONTRACT.json` and run `sgctl compile ... --out <root>`.
- Planner preflight must distinguish package launchability, current repository baseline, and post-phase acceptance commands. Never mark an exact known-red baseline check `ok=true` merely to obtain `PREFLIGHT_GREEN`, and never claim that commands invoking future deliverables were executed before those files exist. Trace future commands to producer deliverables/tests and report them as planned; run all existing safe probes now. Also omit `compatibility.research_gate` entirely when research did not run, because a non-empty `required=false` mapping still causes the current compiler to generate `RESEARCH.md`. Full contract: `references/planner-preflight-vs-postphase-commands.md`.
- At executor closeout, discover the package-local validation surface before invoking a remembered helper name: inspect `<root>/scripts/` and run `python3 <root>/scripts/sgctl.py --help`. For current compiled packages, the portable closeout is `sgctl.py validate-package <root> --strict --format json` plus `sgctl.py validate-loop-design <root>/LOOP_DESIGN.md --instantiated --format json`, followed by the aggregate tests and diff checks. Do not invent a `validate-loop-manifest.sh` dependency when the package does not declare or ship one; use the package-native `sgctl` capabilities and record the exact correction in `RUN_LOG.md`.
- A compiled package carries some **skill-library maintenance probes** (`scripts/test.sh`, `test-user-stories.py`, `probe-upstream-goal-compat.py`, `probe-reference-taxonomy.py`) as runtime assets, but these are not package acceptance tests: they expect the source skill's `SKILL.md` and `docs/` fixtures and can fail correctly in an ordinary mission package. Validate a compiled mission with package-local `sgctl validate-contract`, `validate-package`, `validate-loop-design`, every `validate-phase-markdown`, plus `bash -n -c` for mandatory commands. Run `scripts/test.sh` only from the installed `chip-supergoal` skill root when testing the skill itself; do not misclassify missing `SKILL.md`/user-story fixtures inside a generated package as mission failure.
- `sgctl compile` refuses to overwrite a package that already contains runtime/delivery artifacts such as `out/`. For planner regeneration, remove or move the package root first, then compile fresh; do not keep retrying the same compile command.
- Contract `risk_tags` must come from `spec/risk-policy.json` (`private_data`, `gateway`, `migration`, etc.), not generic labels like `security`, `privacy`, or library-specific tags. Phase `RPD focus` must use the allowed enum (`security`, `integration`, `ux`, `migration`, `data-loss`, `gateway`, `payments`, `none`).
- If you copy `scripts/validate-phase.sh` or `scripts/validate-loop-design.sh` into a portable manual package, also copy package-local `scripts/sgctl.py` **and** `lib/chip_supergoal/`. The wrappers resolve `$ROOT/scripts/sgctl.py`, and `sgctl.py` imports from `$ROOT/lib`; copying only the wrapper or only `sgctl.py` is incomplete. Alternatively run validators through the installed skill path with `PYTHONPATH=<installed-chip-supergoal>/lib` and label the package non-portable until dependencies are embedded.
- For nested package roots such as `<repo>/.supergoal/<slug>`, never insert an absolute path containing `.supergoal/` and then globally replace `.supergoal/` in `PROTOCOL.md`; that self-rewrites the inserted path. Render placeholders or perform exact targeted replacements, then assert protocol/root/phase paths and exactly one launch body.
- A clean-checkout preflight that needs stale ignored `.supergoal/out` files exposes a verifier defect. A seeded ignored artifact may be labeled compatibility evidence for planner preflight, but phase 1 must make the verifier self-contained and final acceptance must rerun it without preseeded residue.
- If you add helper scripts/lib/spec files after compilation, rebuild or update `MANIFEST.json` before running `validate-package`, otherwise the package fingerprint/fileset check will fail.
- For one SuperGoal spanning several repositories and production runtimes, use `references/multi-repo-production-supergoals.md`: per-repo baselines, handoff-as-evidence classification, mutation-safe final audit, exact rollout approval, canonical-state hygiene, and a compact pre-dispatch validation matrix.
- Before deploying a canonical candidate onto a dirty/live-private checkout, use `references/live-drift-rollout-overlays.md`: reconstruct a read-only live baseline, overlay accepted invariants without erasing live behavior, compare baseline-red failure details, and package exact before/after file hashes plus rollback.
- When selectively porting accepted fixes from a handoff whose parent includes live drift or rejected product changes, use `references/selective-handoff-port-safety.md`. Prefer file-scoped three-way patches, inspect the complete staged index before every continue/commit, and abort immediately if unrelated deletions appear.
Then verify live loadability with `skill_view("chip-supergoal")` and, for critical refs, `skill_view("chip-supergoal", file_path="references/rpd-review-gates.md")`.
## Output Contract
For Chip, final planning output is compact and evidence-first: package path, risks/assumptions, sent files or disk paths, exact launch instruction/card, and any blocker.
Do not claim execution success from this planner. Only the `/goal` executor can earn `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE`.
## Quick Test Checklist
- [ ] `skill_view` loads; `scripts/test.sh` passes; launch-body, phase/PROTOCOL, incident-reference, and ignored `.supergoal` regressions hold.
## Done Criteria
- [ ] Frontmatter has `name: chip-supergoal`, trigger-rich description, and `argument-hint`.
- [ ] Root `SKILL.md` stays under the local architecture budget enforced by `scripts/test.sh`.
- [ ] Planner writes `THINKING.md`, optional `RESEARCH.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `STATE.md`, `PROTOCOL.md`, `LAUNCH_GOAL.md`, and strict phase specs.
- [ ] Embedded RPD/Senior Gate remains self-contained; no external `/rpd` dependency.
- [ ] Risky phases require RPD metadata and measurable evidence.
- [ ] Final executor completion requires `AUDIT_COMPLETE` before `SUPERGOAL_RUN_COMPLETE`.
- [ ] File/Telegram delivery, when requested, is backed by receipts before completion.
- [ ] For every Chip-facing package, exactly three native documents were sent to the current Telegram thread in this order: `THINKING.md`, `ROADMAP.md`, `LAUNCH_GOAL.md`. The `startup_pack_v4` receipt contains exactly those three hashes and three real message IDs; `LAUNCH_GOAL.md` was last. Any missing or extra attachment, wrong order, or unverified mapping is `SUPERGOAL_REVIEW_FILES_BLOCKED`.
