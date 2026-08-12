# Outcome definition + Shawl/Luna execution lane

Use this reference when compiling a non-trivial SuperGoal that benefits from an explicit measurable outcome and bounded Luna review through canonical Shawl.

## 1. Outcome definition gate

Adapt the public OpenAI `define-goal` quality bar before loop design. Do not install a second goal manager and do not copy its state workflow. SuperGoal keeps one `CONTRACT.json`, one standard Hermes `/goal`, and one file-first runtime.

The contract's `loop.outcome_definition` must answer:

- `outcome` — the concrete condition that becomes true;
- `evidence` — exact commands, artifacts, receipts, or observable behavior that prove it;
- `threshold` — binary or quantitative acceptance threshold;
- `in_scope` — bounded systems, repositories, paths, or behaviors;
- `out_of_scope` — exclusions that prevent accidental expansion;
- `stop_and_ask` — the smallest material ambiguity or authority boundary that stops execution.

Reject activity-only goals such as “investigate”, “improve”, or “make progress”. If the user's objective is already measurable, normalize it without another question. Ask one concise question only when the missing validator or boundary changes the outcome.

`LOOP_DESIGN.md` renders this as `## Outcome definition`. The outcome is binding; models, tools, phase mechanics, candidate SHA, and implementation tactics remain internal unless Chip explicitly binds them.

## 2. Execution profile

Use `loop.execution_profile`:

```json
{
  "owner": "Sol",
  "planner_effort": "high",
  "integrator_effort": "high",
  "engineering_mode": "shawl",
  "worker_model": "gpt-5.6-luna",
  "worker_mode": "scout",
  "max_parallel_scouts": 3,
  "max_review_rounds": 3,
  "phase_routes": {
    "P01": "shawl",
    "P02": "direct"
  }
}
```

Rules:

- Sol/standard GoalManager owns goal interpretation, state, code integration, protected effects, and final `GO`/`DONE`.
- Luna is launched only through canonical Shawl (`shaw-luna-pool.py`), never as an improvised provider call or nested `/goal`.
- Default Luna mode is read-only `scout`; one Sol/Shaw writer remains authoritative.
- `phase_routes` must cover every phase exactly. Use `shawl` for risky, architecture-heavy, debugging, migration, security, or materially parallel read-heavy phases. Use `direct` for tiny, serial, obvious phases.
- Every `rpd.required=true` or risk-tagged phase routes to `shawl`. If Luna is unavailable, stop with the exact blocker; do not silently substitute another model while calling the route Shawl.
- Maximum three scouts and three review rounds. Lower bounds are allowed; unbounded loops are not.

## 3. Sol → Luna → Sol loop

For each `shawl` phase:

1. Sol reads the phase, current candidate identity, acceptance IDs, and allowed paths.
2. Sol runs canonical Shawl readiness check.
3. Shawl dispatches one to three bounded read-only Luna packets.
4. Sol reproduces every finding locally. Luna output is a hypothesis, not proof.
5. A confirmed finding enters `RED → smallest fix → focused green`; disproved, duplicate, stale, or foreign-scope findings are classified explicitly.
6. Every code-affecting fix creates a new candidate identity and invalidates prior exact-candidate verdicts.
7. Submit the new candidate for a fresh bounded Luna review. Stop after `max_review_rounds`; unresolved P0/P1 becomes `FAILURE_HANDOFF`.
8. Sol alone decides whether acceptance is met and advances runtime state.

A saved Luna thread may be resumed only for a bounded follow-up when canonical Shawl exposes a verifiable session/thread ID. Never fake continuity. The final exact-candidate review must be fresh, because a worker should not certify its own earlier implementation or defend stale conclusions.

## 4. Evidence and state

Append to `out/runtime/REVIEW.md`:

- phase and review round;
- candidate identity before dispatch;
- Shawl report and worker artifact paths;
- each finding disposition: `confirmed+fixed+verified`, `disproved`, `duplicate`, `stale`, `out_of_scope`, or `blocked`;
- commands and exits used to reproduce and verify;
- candidate identity after mutation;
- final P0/P1 counts and Sol verdict.

Do not store raw private Telegram, secrets, tokens, or provider credentials in worker packets or reports.

## 5. Overengineering guard

Do not add a new runner, daemon, database, queue, or alternate state machine. This lane is a phase-level tool route inside the existing `/goal` protocol. If a phase has no real parallel read/review value, route it `direct`.
