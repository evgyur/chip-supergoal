# Dev-history hardening lessons

Use when Chip asks to review recent Dev history, repeated SuperGoal pain, or to harden `chip-supergoal` from real operator incidents.

## Evidence source

A Dev-history review over 2026-06-12..2026-06-19 found recurring failure classes, not one isolated bug:

- `/goal` did not reliably continue to completion after gateway restarts or open tool-tail interruptions.
- Agents sometimes executed phases manually or stopped with a report instead of launching/continuing through `/goal` from `STATE.md`.
- SuperGoal review artifacts were not always delivered as native Telegram files even when Chip explicitly required them.
- Approval UX became unusable when safe-lane work was split into repeated unnecessary approval prompts, while money/DNS/secrets/destructive production still require exact bounded approval.
- Agents asked for data that already existed in local overlays, repo docs, session history, or Telegram history.
- Repo/skill delivery was sometimes reported before push, remote HEAD verification, or clean status.

## Incident classes → gates

| Incident class | Trigger phrase / symptom | Required gate | Regression probe |
|---|---|---|---|
| goal stopped | “Почему goal стоит?”, “до конца”, status-only answer after a phase | read `STATE.md`; if not `DONE`/`BLOCKED`, continue current phase/audit | `/goal resume` after restart continues from phase |
| manual execution drift | “Снова вручную без goal делаешь?” | planner stops at launch; executor continues only from generated `PROTOCOL.md` | no phase work from planner session |
| repeated complete loop | repeated wrapper on already completed root | do not re-run; show completion evidence or require new clean SuperGoal | stale completed wrapper probe |
| missing or excessive startup files | “Где файлы SuperGoal”, “слишком много файлов” | send `startup_pack_v4`: exactly `THINKING.md`, `ROADMAP.md`, then `LAUNCH_GOAL.md` last; require exact three-entry file→message-ID receipt before `READY_TO_DISPATCH` | startup_pack_v4 inventory + receipt |
| approval spam | broad “делай всё до конца” on safe work | treat as safe-lane approval through repo/docs/tests/push; do not ask again | safe repo task proceeds through push |
| live side effect | money/DNS/secrets/grants/destructive prod/public post | require one bounded manifest; `/goal` continuation alone is not approval | money task blocks with manifest |
| existing data missed | “у тебя они уже есть” | search local ignored overlays, repo docs, session history, project skills, and Telegram history before asking | retrieval-before-ask probe |
| repo delivery false done | “git push”, “private repo” | commit/push when requested, verify remote HEAD and clean status | remote HEAD evidence required |

## Required package changes

When generating or updating a SuperGoal package:

1. Copy delivery templates from `templates/delivery/`. Every Chip-facing dispatch uses three-file `startup_pack_v4` from `references/artifact-boundaries.md`.
2. Write `LAUNCH_GOAL.md` as the only launch body; `ROADMAP.md` must not contain an actual `SUPERGOAL_GOAL_BODY:` line.
3. In `STATE.md`, include delivery state and baseline ref.
4. In `PROTOCOL.md`, keep continuation, approval, retrieval, and repo-delivery rules close to the executor loop, not only in historical references.
5. Add acceptance criteria for requested push/remote artifacts in the phase specs, not only in final prose.

## Retrieval-before-ask order

Before asking Chip for a value he says already exists:

1. current `.supergoal/` files and project docs/runbooks;
2. local ignored overlays (`.env*`, `*.local`, credential manifests) without printing secrets;
3. session search / previous transcript references;
4. project-specific skills (`chip-privy`, `chip-polymarket`, etc.);
5. Telegram history via `telegram-chip` when the value was exchanged in chat.

If still missing, ask for the smallest exact item and name the stores checked.

## Done bar for Dev-history hardening

The skill is not hardened until `scripts/test.sh` mechanically checks:

- delivery templates and receipt schemas exist;
- `dev-history-hardening.md` is linked from root/index;
- `PROTOCOL.md` mentions continuation, retrieval-before-ask, approval safe/live, and remote HEAD delivery;
- launch body remains single-sourced in `templates/LAUNCH_GOAL.md`.
