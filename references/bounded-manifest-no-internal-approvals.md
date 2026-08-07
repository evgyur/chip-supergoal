# Bounded manifest, no internal approvals — Pear/Privy/Hyperliquid pattern

Use when Chip asks to restart or rewrite a SuperGoal “до конца без апрувалов внутри” after an approval-card loop, especially for wallet/trading/gateway-control work.

## Core rule
“Без апрувалов внутри” is not unlimited consent. It means: convert the previously approved intent into one launch-level bounded manifest, then run autonomously inside that manifest. Anything outside the manifest becomes a terminal fail-closed blocker, not another approval card.

## Manifest contents
Include exact values:
- wallet/user address;
- builder address;
- agent address;
- max builder fee / fee cap in the raw unit actually returned by readback;
- allowed read/setup/report actions;
- explicitly forbidden side effects.

For Pear/Hyperliquid setup the forbidden list should include:
- funding movement;
- withdrawals;
- order submit/cancel/close;
- leverage or margin changes;
- new builder approval;
- new agent approval;
- secret print/rotation.

## Early safety phase
Add Phase 0 before implementation if money/resource state is involved. It should perform read-only live readbacks and write a report before any other work:
- Pear `GET /agentWallet` only;
- Hyperliquid `POST /info` only;
- never Hyperliquid `/exchange`;
- balances / open orders / fills / extraAgents / approvedBuilders / maxBuilderFee;
- redacted evidence file;
- explicit “no mutation endpoint called” line.

## Implementation pattern
A good runtime module returns structured results such as:
- `manifest-verified` for exact matches;
- `manifest-terminal-blocker` for wrong wallet/builder/agent, higher fee, or forbidden action;
- `noInternalApprovalPrompt: true` so the runner never asks another approval mid-phase;
- `terminalBlocker: true` for outside-manifest actions.

## Readback classification
Separate surfaces and classify them explicitly:
- Pear `/agentWallet`;
- Hyperliquid `extraAgents`;
- Hyperliquid `approvedBuilders`;
- Hyperliquid `maxBuilderFee`;
- Hyperliquid `clearinghouseState` / `spotClearinghouseState`;
- open orders, frontend open orders, fills;
- stale endpoint drift such as `/auth/authenticate` 404;
- browser-signature/Cloudflare 403 separately from auth failure.

This prevents a future agent from treating API drift or browser-signature blocks as a reason to ask Chip for another approval.

## Tests to require
- valid manifest passes;
- wrong wallet fails;
- wrong builder fails;
- wrong Pear agent fails;
- wrong Hyperliquid agent fails;
- higher fee fails;
- trade/order action fails;
- withdrawal/funding action fails;
- report redacts raw signed payloads and secrets;
- default runtime still has network mutation disabled.

## Reporting shape
Each phase should show:
- files changed;
- exact criteria map;
- negative cases and reason codes;
- command output summary;
- report/evidence paths;
- RPD result as checked-holds or mutation applied.

Do not hide behind “approval gated”; the point is to make the safe boundary machine-checkable and then keep moving.

## Direct beta/prod rollout correction

When Chip explicitly says variants of “убери все апрувалы”, “можно сразу в прод”, or “не спрашивай на beta/prod deploy” about a visible SuperGoal for a known Chip-owned internal system:

1. Treat the message as Stage-6 plan approval.
2. Treat reversible repo push, beta rollout, app-code production deploy, and required rollback-capable service restart as standing authorization on the named target.
3. Remove redundant beta/routine-prod gates from `THINKING.md`, `LOOP_DESIGN.md`, `ROADMAP.md`, `STATE.md`, `LAUNCH_GOAL.md`, and affected phase specs together.
4. For a strict compiler-shaped package, mutate `CONTRACT.json` as the source of truth and increment `contract_revision`; do not hand-edit canonical rendered views and then merely rebuild `MANIFEST.json`, because `validate-package` can correctly reject them as generated drift.
5. Compile into a fresh sibling directory, not over the active package. Convert the required approval to a non-required standing-authorization entry, change phase text/criteria/commands from approval-bound to manifest-bound, and rename runtime artifacts such as `approvals/essential-rollout.json` to neutral `manifests/essential-rollout.json` when practical.
6. Inspect the regenerated `ROADMAP.md`, `THINKING.md`, `LOOP_DESIGN.md`, `STATE.md`, `LAUNCH_GOAL.md`, and affected phase specs for contradictory generic approval language. A generic protocol may retain compatibility markers such as `BLOCKED_BY_APPROVAL`; mission-specific contract and phase text must explicitly state that no internal prompt occurs and that out-of-scope actions become terminal blockers rather than approval requests.
7. Run strict contract/package validation, loop validation, every phase validator, and verify the new package fingerprint. Only then atomically swap the fresh package into the canonical `.supergoal` path; keep the old approval-gated package as a timestamped rollback backup.
8. Keep at most one bounded manifest only for concrete high-risk exceptions actually required: secret rotation/revocation, history rewrite/force-push, destructive or irreversible DB migration/grant, firewall/IP/TLS/DNS cutover, new human/admin grants, real money/asset movement, or public/mass send.
9. If a high-risk action is not part of the authorized mission, encode it as forbidden/out-of-scope and stop without prompting. If no high-risk exception is required, continue without a human gate. Never ask piecemeal approvals.

User-facing correction should be short: say that approval count is zero, name the autonomously authorized rollout boundary, and list forbidden out-of-scope classes without lecturing or reproducing the full safety policy. Attach the regenerated review pack when the Chip delivery default applies.
