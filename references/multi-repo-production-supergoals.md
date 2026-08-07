# Multi-repository production SuperGoals

Use this pattern when one goal spans several independent repositories plus live services or databases.

## Planning contract

- Keep one package/project root, but declare one canonical repository, candidate root, baseline SHA, live runtime, deployment target and rollback surface per component.
- Phase 1 writes a machine-readable source registry (for example `evidence/source-registry.json`) and revalidates current remote/live state before any code edit.
- Treat old handoff branches as evidence. Classify each finding as `confirmed`, `already-fixed`, `stale` or `rejected`; never merge a large handoff wholesale merely because it contains useful fixes.
- Preserve independent repositories and deployment units unless a shared control plane is itself the requested product.

## Verification and audit

- Never force a non-Git umbrella workspace through one `Baseline ref`. Run cleanliness and diff checks with explicit roots and baselines: `git -C <candidate-root> ...`.
- Verify package-level evidence separately by path, schema/markers, non-empty content and SHA-256.
- Classify every mandatory command as `setup-local`, `verify-read-only`, `mutate-repo`, `mutate-production`, `destructive` or `external-side-effect` during executable review.
- Final audit reruns only read-only or genuinely idempotent checks. One-shot production deploy, restart, database cutover, public send and money commands are never rerun; prove them with approval-bound immutable receipts plus live readback.
- For a database split-brain or stale-inode repair, separate: preservation and isolated restore; deterministic reconciliation dry-run; exact approval; cutover; read-only final audit.

## Approval design

- Build candidates and evidence before requesting production approval.
- Ask once with an exact manifest: target SHAs/image digests, backup hashes, service/path list, rollout order, health/stop thresholds and rollback commands.
- Keep code/fixture-only payment work outside money approval. A `bounded-money` boundary may be a checked-hold when the package explicitly forbids live transactions; request a new approval only if money movement becomes necessary.

## Compiler/state hygiene

- Patch the source contract and recompile generated views. If a package-specific protocol correction is unavoidable, patch both `PROTOCOL.md` and its packaged template, then rebuild `MANIFEST.json` and validate.
- Do not hand-edit compiler-canonical `STATE.md` merely to record planning delivery; strict validation can flag generated drift. Planning delivery truth belongs in the receipt under `out/`, which the manifest excludes.
- After adding review reports or protocol changes, rebuild the manifest before `validate-package`.

## Runtime scheduler reconciliation

When the goal spans a new runtime plus legacy cron/timers/watchdogs, static code review is not enough. Before assigning P0 labels or writing rollout phases:

1. Inventory **every configured scheduler**, not only active recurring jobs: Hermes jobs, user/system crontabs, systemd timers, long-running poll loops, paused one-shots, report/self-improvement jobs, alert adapters and legacy daemons.
2. Record schedule, enabled/paused state, workdir/release, state store, topics read/written, side effects and authority domain. Include paused historical jobs so an old resume path cannot silently restore a second writer.
3. Compare reviewed Git HEAD, canonical candidate and immutable live release by hashes/content. Classify each inherited finding `confirmed`, `already-fixed`, `stale` or `rejected`; a live service may contain a fix absent from the reviewed worktree.
4. Build a one-writer matrix for trading/execution, control, leader selection, reporting and alerting. A paused legacy order loop can remove direct double-trading while leader/report/alert planes remain split-brain.
5. Query durable queues read-only for orphan topics, exhausted retries and backlog age. Every producer topic needs exactly one owner or an explicitly removed producer; never repair status rows manually in the planning phase.
6. Make consolidation reversible: `pause → parity/read-only projection → archive/remove`, with TTL/sunset criteria, no-auto-resume proof and an approval-bound production manifest.

Keep systemd timer → durable queue → role-owned worker as the runtime scheduling authority where that pattern already exists. Use Hermes cron for read-only analysis/reporting, not as a competing operational state writer.

## Minimal pre-dispatch checks

1. `validate-contract` and `validate-package`.
2. `validate-loop-design` and every generated phase markdown.
3. Parse every mandatory command with `bash -n -c` without executing it.
4. Compile packaged Python and run shell syntax checks.
5. Simulate GoalManager outcomes: phase done continues, approval blocks, final triple markers complete.
6. Verify repository access, SSH identity/effective user, service names and live target reachability read-only.
7. Deliver `startup_pack_v4` and validate the exact three-file ordered receipt: `THINKING.md`, `ROADMAP.md`, `LAUNCH_GOAL.md` last.
