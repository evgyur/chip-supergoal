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
