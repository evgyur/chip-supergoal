# Execution state machine

This is the precedence table for the generated `/goal` executor.

## States

- `PLANNED` — package exists, launch not started.
- `READY_TO_DISPATCH` — planner finished and emitted launch body.
- `PHASE_N` — executor is running numbered phase N.
- `AUDIT` — all numbered phases have `SUPERGOAL_PHASE_DONE`; final audit is pending.
- `BLOCKED` — approval, missing credentials, destructive action, failed preflight, or unrecoverable verification gap.
- `DONE` — `AUDIT_COMPLETE` and `SUPERGOAL_RUN_COMPLETE` printed.

## Official GoalManager loop

1. Read `STATE.md`.
2. If `Current phase: N`, read `phases/phase-N.md`.
3. Print `SUPERGOAL_PHASE_START` and `SUPERGOAL_STATUS`.
4. Do phase work and mandatory verification.
5. Print `SUPERGOAL_PHASE_VERIFY` with criterion-to-evidence mapping.
6. Run `RPD_PHASE_REVIEW` when required. If `Execution route: shawl`, invoke canonical Shawl only: Luna scouts read/review, then Sol reproduces findings, remains the single writer/integrator, reruns gates, and treats every code-affecting fix as a new candidate identity.
7. Save durable non-obvious lessons or print `MEMORY_SAVED: none`.
8. Print `SUPERGOAL_PHASE_DONE`.
9. Update `STATE.md` to next phase or `AUDIT`.
10. Continue immediately to the next phase in the same assistant turn until a real approval/safety gate, blocker, or final audit completion is reached.

Do **not** treat phase boundaries as a stop condition for Chip. `SUPERGOAL_TURN_YIELD` is only appropriate when yielding at a real gate/blocker or after the full run completes. A per-phase courtesy stop is a weak stop and violates Chip's expected SuperGoal execution mode.

## State ledger and ignored package artifacts

- Use a real timestamp for every `STATE.md` event (`date -u +%Y-%m-%dT%H:%M:%SZ` or tool-provided equivalent). Do not write placeholder times and patch them later unless unavoidable.
- `.supergoal/` is often intentionally git-ignored. Plain `git status --short` can look clean while the package exists only as ignored files. When verifying package presence or cleanliness, also run one of:
  - `git status --short --ignored .supergoal`
  - `find .supergoal -maxdepth 3 -type f | sort`
- Before creating a new package, check whether an ignored `.supergoal/` already exists. If it is stale and the user asked for a fresh SuperGoal, remove/recreate it explicitly and record that in `STATE.md`.
- Phase evidence must distinguish tracked repo cleanliness from ignored planning artifacts. A clean tracked status does not prove the `.supergoal/` package is absent, delivered, or current.
- During final residue cleanup, exclude runtime/vendor dirs such as `venv/`, `.venv/`, `.git/`, `.supergoal/`, and `node_modules/`. Clean `__pycache__`, `.pytest_cache`, and `*.pyc` with a bounded script that skips those dirs; do not sweep the whole repo blindly or you can hit permission-owned package caches inside the active virtualenv.

## Manual Telegram/no-stall fallback

If auto-continuation is visibly not happening and the user sends a continuation command or frustration signal, continue from `STATE.md` without debating protocol. You may process more than one phase in the same turn; preserve all phase markers and update state after each phase. Stop only at a real approval/safety gate, a real blocker, or `AUDIT_COMPLETE` / `SUPERGOAL_RUN_COMPLETE`.

If the user challenges a blocker, reassess it. Do not defend an over-broad gate. For Chip-owned private proof actions that are part of the requested verification (for example a private DM smoke/readback with no config change, restart, topup, plugin change, session reset, public/group send, or default switch), treat the correction as authorization to proceed with that bounded proof unless another safety rule applies.

## False blockers that must not stop Chip SuperGoals

These are progress checks, not approval gates, when they are already part of the requested goal and target Chip-owned/private surfaces:

- private DM smoke/readback to Chip's own bot or Chip DM;
- local/unit/integration tests, compile/lint/typecheck, repo cleanup, report/state writes;
- read-only service/config/log/usage/ledger inspections;
- direct low-risk model/API smoke using an already configured scoped key, with no topup and no config change;
- fetching Telegram readback for a message the agent just sent as part of private verification.

If one of these fails, classify it as a verification failure and repair/retry. Do not stop with `BLOCKED_BY_APPROVAL` unless the repair would require a real gate below.

## Real gates that may stop

Stop only for money/topup/trading, DNS, secrets/credential disclosure or creation, grants/access changes, destructive production mutation, public/mass posts, permanent default-model switch, plugin disable, session reset, or an unrecoverable missing credential/external outage after retrieval attempts.

## Blocked/approval precedence

- Money movement, DNS, secrets, grants, destructive production actions, and mass/public posts require explicit approval.
- A `/goal` continuation alone is not approval.
- If approval is missing, print `BLOCKED_BY_APPROVAL` or `READY_FOR_DELETE_APPROVAL` and stop.

## Audit

Final audit re-reads the original `ROADMAP.md`, not prior self-reports. It re-runs aggregate mandatory commands, checks deliverables with `repo-state.sh`, runs `RPD_FINAL_REVIEW`, and only then prints `AUDIT_COMPLETE`.

If gaps remain after bounded repair rounds, print `AUDIT_HANDOFF` and do not print `SUPERGOAL_RUN_COMPLETE`.


## Retrieval-before-ask gate

If the user says “у тебя уже есть”, references a prior approval/artifact/key/doc, or the plan depends on a value likely stored locally, search before asking:

- `.supergoal/` state and project docs;
- repo-local ignored overlays without printing secrets;
- session history and project skills;
- Telegram history through `telegram-chip` when the value was exchanged in chat.

If not found, ask for the smallest missing item and list the stores checked.

## Repo delivery completion gate

When a phase deliverable includes push/private repo/publication, `SUPERGOAL_PHASE_DONE` must cite remote HEAD match or explicit local-only boundary. Final audit treats missing remote proof as an `AUDIT_GAP`.

If the user adds a durable-doc/update instruction during the final phase or audit (for example: “пропиши это в server-doctor so future updates reapply the patch”), treat it as part of the current audit deliverable, not as a separate future promise:

- load the governing ops/update skill or reference;
- patch the reusable class-level runbook with the exact reapply shape and verification commands;
- if the runbook is repository-backed and the user did not forbid it, commit and push only that doc update, then verify remote HEAD / `HEAD...origin/main == 0 0`;
- do not let unrelated pre-existing dirty files in that repo block the targeted doc commit;
- include the durable-doc proof in `AUDIT_VERIFY` before printing `AUDIT_COMPLETE`.
