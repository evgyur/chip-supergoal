# Core planning contract

This reference expands the root Stage 0-7 workflow. The root is the public controller; this file holds operational detail.

## Stage 0 — context and resume

- Resolve the live `skill_dir` from `skill_view`/runtime discovery before trusting hard-coded paths.
- Detect whether the task is a new SuperGoal or a continuation from an existing `runtime/STATE.json`; use `STATE.md` only to locate legacy/manual packages and then validate or migrate them.
- Preload durable memory and session context only when relevant to the user/task.
- Detect available tools/skills: research, GitHub, browser, MCP/context docs, terminal, file tools, Telegram delivery.
- For repo-backed work, capture repo root, git status, baseline ref, package manager, and obvious test/build commands.

## Stage 1 — intake

Brownfield: inspect first and ask at most 0-2 batched questions for gaps tools cannot answer.

Greenfield: ask enough batched questions to cover platform, stack, UX direction, audience, integrations, data, deployment, security, and done criteria. Do not over-interview when assumptions are safe to record.

## Stage 2 — recon

Use native file, Git, and search tools on every platform. The included scripts
below are optional Unix-only recon helpers when Bash is available; their absence
must not block native Windows planning:

```bash
bash "$SUPERGOAL_DIR/scripts/detect-stack.sh" > "$SUPERGOAL_ROOT/context.md"
bash "$SUPERGOAL_DIR/scripts/summarize-repo.sh" > "$SUPERGOAL_ROOT/repo-map.md"
```

For greenfield/non-repo work on Unix:

```bash
bash "$SUPERGOAL_DIR/scripts/detect-env.sh" > "$SUPERGOAL_ROOT/context.md"
```

Print a five-line summary: stack, package manager, build/test/lint commands, notable modules, risky areas.

## Stage 3 — think before writing

Write `THINKING.md` before `ROADMAP.md` with:

- goals and non-goals
- constraints and permissions
- top 3 risks with mitigation
- non-obvious dependencies/order
- assumptions accepted vs blockers
- memory hits applied
- tools/skills/research sources used
- build-vs-buy / existing-solution verdict when relevant

If current facts shape architecture, write `RESEARCH.md` too.

## Stage 3.5 — loop design gate

Write `LOOP_DESIGN.md` before `ROADMAP.md`. This is the pre-launch harness design, not implementation. It must cover:

- goal, context sources, and canonical truth;
- host model / executor;
- reviewer or judge seat and rubric;
- verification gates and evidence tiers;
- state checkpoints and continuation path;
- stop conditions, retry limits, and budget;
- boundaries, approvals, egress, and redaction;
- failure recovery and ASCII preview.

Run the loop health rubric from `references/loop-design-gate.md`. If the loop is vague, unbounded, or review-theater, mutate `LOOP_DESIGN.md`, `ROADMAP.md`, or phase specs before Stage 6.

## Stage 4 — decompose

Phase count is derived from the task. No fixed cap. Each phase must leave the project in a verifiable state and have independent acceptance criteria.

## Stage 5 — write files

Write/update:

- `THINKING.md`
- optional `RESEARCH.md`
- `LOOP_DESIGN.md`
- `ROADMAP.md`
- authoritative `runtime/STATE.json` plus generated `STATE.md` projection
- `PROTOCOL.md`
- `LAUNCH_GOAL.md`
- `phases/phase-N.md`
- package-local `scripts/sgctl.py` and `lib/chip_supergoal/` as Python validator authority; optional Unix wrappers may be copied only with those dependencies.

For nested roots such as `<repo>/.supergoal/<slug>/`, bind protocol paths without global self-replacement, distinguish compiler-built strict packages from manual plan-first packages, and handle ignored-artifact baseline dependencies honestly. Follow `references/nested-package-preflight.md`.

From the package root, validate loop design with `python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated`, every phase with `python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md`, and cross-file phase/launch consistency with `python scripts/check-cross-file-consistency.py .`. Bash wrappers are optional Unix conveniences.

## Stage 6 — embedded plan review

Run `RPD_PLAN_REVIEW` from `references/rpd-review-gates.md`. Every material finding must mutate an artifact or be recorded `checked-holds` with evidence tier.

Then show a compact review summary and wait for explicit go/no-go.

## Stage 6.5 — preflight

Run the cheapest real checks that prove the plan can launch safely: required files, phase validation, baseline commands, repo status, delivery configuration, and approval blockers.

Print `PREFLIGHT_GREEN` only with evidence. Print `PREFLIGHT_RED` with a concrete blocker and next move.

## Stage 7 — dispatch

Emit `READY_TO_DISPATCH` plus a launch card/file. Stop. Do not start phase 1 in the planner session.
