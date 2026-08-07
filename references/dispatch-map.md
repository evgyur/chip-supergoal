# SuperGoal Reference Dispatch Map

This is the active reference taxonomy for `chip-supergoal`. Root `SKILL.md` should point here instead of growing a long incident list.

## Active canonical references

| Trigger / concern | Load first | Optional follow-ups |
|---|---|---|
| Core planner stages, plan-only boundary, human gates | `core-planning-contract.md` | `planning-depth.md`, `phase-design.md` |
| Artifact boundaries / startup pack v4: generated file ownership, exact three-file `startup_pack_v4`, receipts, planning-vs-final delivery | `artifact-boundaries.md` | `artifact-schemas.md`, `telegram-launch-and-delivery.md` |
| Launch body, standard `/goal` compatibility, structured completion | `upstream-goal-compatibility.md` | `upstream-goal-reconciliation.md`, `supergoal-goal-code-review-hardening.md` |
| One `/goal` supervising staged Project Flow runs separated by a foundation/admission barrier | `staged-project-flow-runs-in-one-goal.md` | `execution-state-machine.md`, `executable-contract-review.md`, `project-flow` |
| Execution loop, state transitions, final audit, recovery precedence | `execution-state-machine.md` | `goalmanager-recovery.md`, `repeated-complete-continuations.md` |
| Loop harness design before roadmap compilation | `loop-design-gate.md` | `rpd-review-gates.md` |
| RPD/Senior review gates and xhigh handoffs | `rpd-review-gates.md` | `rpd-to-supergoal-handoff.md` |
| Research, architecture, current facts, build-vs-buy | `research-and-architecture-gates.md` | `research-before-design.md`, `architect-plus-lite.md` |
| Source-lock recovery from missing URLs/dates/runtime mapping | `source-lock-recovery.md` | `ignored-supergoal-package-hygiene.md` |
| Telegram launch, review files, final file delivery | `telegram-launch-and-delivery.md` | `artifact-boundaries.md`; incident refs only for forensics |
| Production, auth, payments, destructive/data-sensitive work | `production-safety.md` | `production-deploy-gates.md`, `process-integrity-production-runs.md` |
| Skill editing, package validation, repo-backed delivery | `skill-maintenance.md` | `skill-feature-audit-user-stories.md`, `legacy-skill-phase-validation.md` |
| Dev-chat/systemic incident classes | `dev-history-hardening.md` | canonical refs above; do not add new incident rules to root |
| Human20 SEO/AEO/GEO SuperGoals | `human20-seo-aeo-geo-planning.md` | `research-and-architecture-gates.md` |

## Superseded incident clusters

These files may contain useful forensics, but they are not active policy when they disagree with canonical refs above:

- Telegram incident refs: `telegram-review-file-delivery-gate.md`, `telegram-md-goal-launch-hardening.md`, `telegram-md-goal-launch-ux.md`, `telegram-md-launch-pipeline-hardening.md`, `telegram-file-delivery-idempotency.md`, `telegram-delivery-idempotency.md`, `telegram-launch-card-ux.md`, `reply-md-goal-launch.md`, `rpd-reviewed-supergoal-launch.md`, `telegram-supergoal-artifact-delivery-correction.md`.
- Repeated/standing goal incident refs: `standing-goal-continuation-completion.md`, `standing-goal-continuous-execution-and-restart-recovery.md`, `standing-goal-disambiguation-and-audit-lookup.md`, `standing-goal-final-audit-completion.md`, `repeated-completed-wrapper-guard.md`, `goalmanager-completion-loop-incidents.md`.
- Gateway/restart incident refs: `gateway-restart-live-proof.md`, `gateway-restart-proof-and-bogus-goal.md`, `gateway-goal-startup-recovery.md`, `gateway-recovery-ledger.md`, `model-gateway-supergoal-live-failure.md`.
- Project-specific incident refs: auth, Polymarket, provider, old-server, and rollout references. Load only when the current SuperGoal is in that project/domain.
- Historical archaeology: `legacy-monolith-2026-06-19.md`. Do not load by default.

## Update rule

When a new incident only reinforces an invariant, patch the canonical reference and add a one-line incident pointer here if needed. Add a new root dispatch line only for a new class of work or a new public marker.

## Banned active-policy phrases

Active canonical references must not reintroduce these stale instructions:

- `exactly-three-native`
- `three-native-md-files`
- `one-numbered-phase-per-turn`
- `stop-with-SUPERGOAL_TURN_YIELD`
- `do-not-chain-phases`
- `execute-only-current-phase`

Historical/archive references may quote old phrases only if clearly marked as legacy or superseded.
