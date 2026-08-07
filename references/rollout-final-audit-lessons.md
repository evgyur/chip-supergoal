# SuperGoal rollout and final-audit lessons

Use this reference when a SuperGoal reaches rollout/final-audit preparation with local dirty changes, production deploy gates, or security/cleanliness scans.

## Exact-SHA production deploy gate

If a rollout report mentions `scripts/deploy_prod_rf.sh origin/prod`, verify what that command would actually deploy.

Danger pattern:

```text
local worktree: detached and dirty
HEAD == origin/prod == old SHA
report says: run deploy_prod_rf.sh origin/prod
```

That would deploy the old `origin/prod`, not the local SuperGoal changes.

Required gate before any code deploy phase:

1. Commit reviewed SuperGoal deliverables in the canonical repo/worktree.
2. Push/promote the exact reviewed SHA to `origin/prod`.
3. Verify:

```bash
git fetch origin --prune
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/prod)"
```

4. Only then run canonical deploy:

```bash
bash scripts/deploy_prod_rf.sh origin/prod
```

Or, from the canonical clean worktree, use:

```bash
bash scripts/promote_human20_prod.sh
```

Approval language must name the exact SHA/source ref and must not imply that a dirty detached worktree will be deployed by `origin/prod`.

## Split code deploy from media/data mutation

For Human20 video/HLS work, code deploy and media rollout are separate tracks.

`deploy_prod_rf.sh` can deploy code and restart RF services, but it does not prove or perform:

- production HLS artifact copy/replacement;
- production `HUMAN20_HLS_ROOT` changes;
- production DB/portal `video_path` changes;
- nginx/CORS/proxy changes;
- DNS/CDN changes;
- media signing-key changes.

Keep those as separate explicit approval gates.

## Security scan fixture hygiene

Final cleanliness scanners often flag test strings such as `access=token%20value` as raw-token-looking values. Prefer obviously non-secret dummy values in tests:

```tsx
mediaAccessToken="t t"
expect(url).toContain("access=t%20t")
```

Docs and smoke scripts should print placeholders only:

```text
access=<token>
file=<segment.ts>
```

## Existing production defaults vs new local paths

A repo may already contain production defaults such as:

```text
<runtime-dir>
```

If the path is pre-existing, production-scoped, and env-overridable, classify it explicitly as an approved production default rather than a newly introduced local workstation path. New hardcoded workstation paths, especially `C:\...` or `ffmpeg.exe`, remain blockers.

## Final audit note

Before `AUDIT_COMPLETE`, re-run aggregate local gates and scan the actual deliverable files, not only the reports:

- focused tests (`npm test -- video` for this class);
- changed-code lint;
- build;
- debug print/TODO/FIXME scan;
- secret/raw token scan;
- copied-code/vendor marker scan;
- branding/dark-theme guardrail scan when UI changed.

## Live-runtime truth beats artifact labels

For production-adjacent sensing, cron, or LLM rollouts, inspect the current private runtime as well as tracked fixtures. Labels such as `safe_summary`, `redacted`, `raw_content_included=false`, `PASS`, or `last_status=ok` are claims to verify, not proof. Block completion when the live context still contains near-verbatim private source bodies, private targets embedded in model prompts, or internal tool failures hidden behind a final successful/silent response.

Verify that timeout and privacy gates are wired through the real CLI/cron path. A helper test that injects synthetic elapsed time does not prove a production entrypoint that hardcodes elapsed time to zero. Likewise, a repo-only privacy scan does not cover private runtime context that is actually sent to a model.

## Approval and rollback evidence binding

A production approval record should bind the human decision to the exact goal, manifest fingerprint/revision, bounded action scope, timestamp, and redacted source reference. Do not accept a mutable state sentence solely because it contains expected magic phrases; generic permission to continue a goal is not automatically approval of a specific production manifest.

A final scheduler snapshot cannot prove transition ordering or a rollback drill. Require an auditable event/receipt chain showing old paused before new enabled, staged delivery readback, an additional scheduler cycle, rollback to old, and restoration to the reviewed steady state. Read rollback verifier code adversarially: a rollback stage must expect old enabled/new paused, not reuse steady-state predicates.

## Aggregate-audit semantics

The final-audit command must execute or independently verify every acceptance gate, including tests, privacy, live validation, final schedule, receipts/rollback, exact SHA/worktree cleanliness, package manifest integrity, and final senior/RPD review. Searching reports for the substring `PASS` is insufficient; parse explicit status and reject contradictory text. Missing artifacts should produce structured fail-closed errors, not tracebacks.

When planner state changes after package compilation, recompute the package manifest. Resolve the real package root rather than assuming the execution checkout contains the same relative `.supergoal/...` path. If another executor mutates the worktree during review, timestamp the snapshot and require a fresh final check before completion.

## Interrupted activation: recover before retry

If the executor is interrupted after an external effect may have happened, never blindly rerun `activate`.

1. Inspect the manifest-scoped immutable journal, lock, transaction receipt, cron state, live file hashes, and external message fetchback.
2. Reconcile an intent without a terminal event. If the canary/receipt exists exactly once and matches the intended sender, chat, and body hash, record the discovered effect instead of sending again.
3. Hold the manifest lock while reconstructing the terminal path. Resume only from a stage whose postconditions can be independently recomputed; otherwise roll back to exact prestate.
4. Re-run independent files, cron, transaction, approval, privacy, and canary verifiers before declaring the rollout verified.

A recovery process naturally has a different PID from the original winner. Journal provenance should allow one bounded recovery PID after the interrupted intent, plus a final verifier PID, while requiring the same archived executable hash, UID/GID, stage ordering, and hash chain. Do not weaken provenance to “any later writer.”

## Versioned activator source

The activation lock binds the executable SHA used for the transaction. Editing that activator during recovery can make valid historical evidence unverifiable.

- Archive the exact lock-bound source by SHA before evolving the activator.
- Resolve verifier audits against either the current source or exactly one immutable archived source with the lock SHA.
- Audit cron-writer AST/source against the resolved lock-bound version, not automatically against the newest file.
- Install a new activator only for a new manifest; keep the previous transaction independently verifiable.

## Prestate and poststate verifier duality

A manifest verifier that passed before activation may fail after activation if it reads the current live file as the `before` image or expects a private root to remain absent.

Post-activation verification must:

- recover `before` bytes from the manifest-bound rollback source;
- verify live files against `after_sha256`;
- treat manifest-declared newly created parent directories/private roots as expected poststate while still excluding them from unrelated-surface digests;
- preserve symlink, owner, mode, and containment checks in both states.

Do not “fix” this by skipping guard checks after activation. Compute the state-appropriate guard from sealed evidence.

## Follow-on remediation manifest after a verified rollout

A follow-on manifest starts from the current verified live state, not from the original pre-activation seeding.

Required sequence:

1. Finish all local remediation first and place the exact remediated bytes at the canonical candidate path.
2. Capture fresh live seeding/metadata and fresh dirty-surface guards.
3. Treat every currently existing controlled file as `replace`, even if its original rollout classified it as newly created.
4. Allow unchanged operations only when their exact before/after hashes, metadata, inverses, and scope are valid; report the number of byte-changing operations separately.
5. Derive cron rollback argv from `before_stable.script`. If the cron already points to the desired script, forward and inverse edits may both be safe no-ops. Never hardcode the first rollout's legacy inverse into a follow-on manifest.
6. Run both the independent manifest verifier and the pending activator's exact-scope preflight before asking for approval.
7. Only then send and fetch back a new approval request, anchor its message ID in mutable runtime state, and require a fresh exact manifest-bound reply.

Do not reuse an old approval projection for a new manifest. Do not ask Chip repeatedly while local preflight defects remain. Complete every local handoff first; surface only the final irreducible external gate with the exact phrase and request message ID.

## Final-audit evidence must be earned

Before sealing phase specs, execute every mandatory command in its exact declared form. In particular, verify that CLI flags named by a smoke command actually exist; a compatibility wrapper that runs equivalent behavior does not prove the sealed command is executable.

Final audit must fail closed when:

- the exact collector/deploy CLI contract is missing;
- an operational score is below its threshold;
- criterion rows carry only phase-wide existence hashes rather than criterion-specific command spec, statement, deliverable, and postcondition hashes;
- crash matrices contain booleans without fresh probe provenance and per-case pre/post fingerprints;
- an aggregate report claims green while a required command cannot run.

Operational scores must be recomputed from live hashes, journal chain, cron projection, fresh recovery probes, privacy/effect receipts, and exact interface checks. Write the score report even on failure, then return non-zero. This preserves honest evidence without turning an 8/10 state into a false completion.
