# Loop Design Gate

Use this reference when upgrading, generating, or reviewing a SuperGoal package. The gate turns SuperGoal from a roadmap compiler into a governed execution-loop compiler.

## Purpose

Before `ROADMAP.md` and phase specs become launchable, the planner must design the loop that will run them:

- goal and non-goals;
- context sources and canonical truth;
- host model / executor;
- reviewer or judge seat;
- verification gates and evidence tiers;
- state/checkpoint ownership;
- stop conditions and retry limits;
- budget for iterations, tokens, and time;
- boundaries, approvals, egress, and redaction;
- failure recovery path.

Before `LOOP_DESIGN.md`, run the pre-plan `PONYTAIL_SCOPE_GATE` from `references/ponytail-scope-gate.md`. Loop design must stay inside its owner/phase/helper/reviewer budget unless a concrete requirement or reachable trust boundary justifies the exception. Do not make the loop-governance machinery larger than the mission.

Do **not** create a separate `/looper` command by default. For Chip's SuperGoal workflow, the LOOPER idea belongs inside `chip-supergoal` as a pre-roadmap design gate.

## Required artifact: `LOOP_DESIGN.md`

Every non-trivial SuperGoal package must include `LOOP_DESIGN.md` next to `THINKING.md` and `ROADMAP.md`. Required sections:

- `Goal`
- `Outcome definition` — outcome, exact evidence, threshold, in/out scope, and stop-and-ask condition
- `Context sources`
- `Host model`
- `Reviewer / judge model`
- `Verification gates`
- `State checkpoints`
- `Stop conditions`
- `Budget`
- `Boundaries`
- `Failure recovery`
- `Human approvals`
- `ASCII preview`

For `engineering_mode: shawl`, `Host model` and `Reviewer / judge model` must also name Sol/GoalManager as sole owner/integrator, `gpt-5.6-luna` as a read-only scout reached only through canonical Shawl, per-phase `direct|shawl` routing, maximum three parallel scouts, maximum three fresh review rounds, local reproduction of findings, and new candidate identity after code-affecting fixes.

The file must be human-readable and executor-usable. It is not a decorative diagram.

Fail the gate before dispatch if:

- any required section is missing or placeholder-only;
- `LOOP_DESIGN.md` contains an actual `SUPERGOAL_GOAL_BODY:` launch line;
- the preview omits the `LOOP_DESIGN.md → /goal → FINAL AUDIT` chain;
- stop/budget/boundary sections do not name concrete limits and approval boundaries.

Use `bash scripts/validate-loop-design.sh <LOOP_DESIGN.md>` for the deterministic section gate; RPD still judges quality and fit.

## Loop health rubric

Before dispatch, check:

1. Is the goal falsifiable and scoped?
2. Are context sources named, with canonical truth separated from assumptions?
3. Is there a clear host model/executor?
4. Is the reviewer/judge role explicit: notes vs pass/fail verdict?
5. Are programmatic checks preferred where possible?
6. Are human approvals reserved for real sensitive gates, not routine phase boundaries?
7. Are retry limits and no-progress stop conditions explicit?
8. Are budget limits explicit enough to prevent token burn?
9. Are boundaries and egress/redaction rules clear for secrets, private Telegram, payments, and production data?
10. Does failure recovery name the next action instead of looping vaguely?

If material answers are missing, mutate `LOOP_DESIGN.md`, `ROADMAP.md`, or phase specs before launch. If the gap cannot be closed without the user, block with one concrete question.

## ASCII preview contract

Include a compact preview of the execution loop. Example:

```text
INTAKE / RECON
  ↓
THINKING + RESEARCH
  ↓
LOOP_DESIGN.md
  ↓ gate: loop health rubric + RPD/Senior pressure
ROADMAP + PHASE SPECS
  ↓ gate: phase validation + launch contract
/goal EXECUTION
  ↓
PHASE N
  ↓ gate: tests + RPD_PHASE_REVIEW where risky
FINAL AUDIT
  ↓ gate: RPD_FINAL_REVIEW
DELIVER / DONE
```

Keep the preview short. Its job is to expose bad loop shape before execution.

## Council / judge seat

The loop design must distinguish:

- `host model` — the executor doing the work;
- `reviewer` — gives critique/notes that must mutate artifacts or become checked-holds;
- `judge` — gives pass/fail verdict against a rubric;
- `Senior Gate` — required for production, money, privacy, credentials, auth, payments, model/provider routing, gateway/cron/routing, architecture/migration, public launch, recurring bugs, or risky completion claims.

Reviewer/judge output is not useful if it becomes commentary. It must either mutate artifacts or record checked-holds with evidence tier.

## Egress and redaction

For any second model, external agent, or cross-tool reviewer, state what can leave the local context:

- `.env`, credentials, tokens, session strings: never;
- private Telegram text/media: only if explicitly required and redacted/summarized;
- payment/legal/user data: minimize, redact, and require approval when material;
- source code/config: allowed only within the task scope;
- generated SuperGoal files: allowed unless they include private/secrets material.

## Overengineering guard

A new runner such as `run-loop.py`, a standalone `/looper`, or another orchestration layer must pass the overengineering budget:

- why existing `/goal` + `PROTOCOL.md` is insufficient;
- simpler alternative rejected;
- removal condition.

Default answer: no new runner; design the loop, then launch the existing `/goal` executor.

For deterministic probes and bounded operations, prefer **one tested operator/verifier CLI with subcommands** over a pile of phase-specific helper scripts. It may validate, diff, read back, or apply one reviewed operation; it must never claim TODOs, advance phases, retry autonomously, or become an alternate runner. Record its necessity, rejected simpler alternative, and removal condition in the architecture.

## Approval authenticity and staged activation

For skill/config/gateway work, separate build evidence from live effects:

1. Build and test the skill under the project workspace first.
2. Freeze a file manifest and gateway patch manifest.
3. Keep the active skill directory and gateway unchanged until the live-effect approval boundary.
4. At that boundary, install through the canonical skill-management path, apply only the reviewed config diff, restart/reload, and prove live behavior by readback.

A phase must not authorize itself by writing `approved: true` or accepting a plain `--approved APP-ID` string. Approval authority must pre-exist as a trusted external locator, such as a fresh immutable Telegram message from the authorized actor, and bind actor, target, nonce, expiry, exact manifest hashes, one-shot/replay scope, allowed effects, stop conditions, and rollback owner. Cache files are receipts, not authority. Add negative probes for fabricated, stale, wrong-actor, wrong-target, wrong-hash, and replayed receipts.

## Stage placement

Insert as Stage 3.5:

```text
Intake
 → Recon / Research
 → PONYTAIL_SCOPE_GATE
 → LOOP DESIGN
 → LOOP HEALTH REVIEW
 → ROADMAP / PHASES
 → RPD_PLAN_REVIEW + PONYTAIL_FINAL_CHECK
 → PREFLIGHT
 → LAUNCH_GOAL
```

RPD_PLAN_REVIEW must inspect `LOOP_DESIGN.md` as a first-class artifact.
