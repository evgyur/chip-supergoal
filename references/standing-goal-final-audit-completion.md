# Standing-goal final audit completion

Use when Chip sends a SuperGoal continuation that says to finish through final audit, or the current/last phase spec itself requires `AUDIT_COMPLETE` / `SUPERGOAL_RUN_COMPLETE`.

## Lesson

Do not stop at a normal phase-yield if the declared finish line includes final audit and the remaining audit steps are safe. Chip expects the run to continue through the declared completion markers without internal micro-approval prompts.

## Required behavior

1. Read `.supergoal/STATE.md` and the current phase spec.
2. Execute the current phase normally.
3. If the phase is the final numbered phase and the spec/goal says final audit is part of the phase or finish line:
   - run the final audit in the same bounded continuation when safe;
   - re-run aggregated mandatory commands;
   - re-check live/read-only status if the manifest permits it;
   - write `.supergoal/reports/final-audit.md`;
   - include `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE` in the artifact and visible transcript;
   - update `.supergoal/STATE.md` to `Status: COMPLETE` / `Current phase: COMPLETE`.
4. Only stop earlier for a real blocker: unsafe side effect, missing unretrievable context, failed command/criterion after recovery, or explicit human/provider approval boundary.

## Lifecycle-aware aggregate audit

Do not blindly rerun every historical mandatory command after production activation. Some commands are pre-rollout gates, non-deterministic live observations, or state-transition commands whose successful rerun would mutate a healthy steady state.

1. Classify each command before rerunning it:
   - **stable re-verification** — tests, privacy scans, schemas, read-only cron/delivery probes: rerun;
   - **lifecycle-aware validator** — make it accept both the declared preflight state and the verified steady state, with explicit tests for each;
   - **non-deterministic live gate** — preserve the canonical pre-rollout artifact and mark its semantic result `trust-prior`; rerun only the no-mutation/safety half;
   - **state transition / rollback drill** — do not repeat after successful rollout; verify the receipt and final state, then mark the transition `trust-prior`.
2. If a live rerun overwrites a canonical pre-rollout report with a context-dependent empty/blocked result, restore the versioned canonical report, disclose the attempted rerun, and keep only the current safety/no-mutation proof as fresh evidence.
3. Completion is blocked when a user-visible promised surface is absent even if transport/tests are green. Repair the real surface, restart if required, and require a post-restart receipt or fetch-back before terminal markers.
4. Record re-verified versus trust-prior criteria and compute audit coverage. Do not hide lifecycle exceptions inside a generic “all commands passed” claim.

## Safety boundary

This does not authorize side effects. For money/control-plane SuperGoals, final audit may use local checks, static scans, and read-only probes only. Funding, withdrawals, orders, cancels, closes, leverage/margin changes, new builder approvals, and new agent approvals remain forbidden unless separately approved.