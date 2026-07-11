# Artifact schemas

## `THINKING.md`

Required sections:

- Goal
- Non-goals
- Constraints and permissions
- Risks top 3
- Dependencies/order
- Assumptions
- Memory hits applied
- Tools/skills used
- Best practices applied

## `RESEARCH.md`

Use only when research gates run. Required sections:

- Research status
- Sources with URLs/tool names
- Existing-solution candidates
- Build-vs-buy verdict
- Planning implications
- Unverified assumptions and falsifiers

## `LOOP_DESIGN.md`

Required pre-launch loop harness. Use this to design how the `/goal` executor will run before compiling phases.

Required sections:

- Goal
- Context sources
- Host model
- Reviewer / judge model
- Verification gates
- State checkpoints
- Stop conditions
- Budget
- Boundaries
- Failure recovery
- Human approvals
- ASCII preview

`LOOP_DESIGN.md` must not contain a line beginning `SUPERGOAL_GOAL_BODY:`. It is an execution-shape artifact, not a launch surface. See `references/loop-design-gate.md`.

Validation:

```text
python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated
```

The Bash wrapper is an optional Unix compatibility entrypoint.

## `ROADMAP.md`

Required sections:

- Decision package
- Context summary
- Assumptions
- Risk top 3
- Phase map
- One section per phase with deliverables, acceptance criteria, mandatory commands, evidence, dependencies
- Final polish/hardening phase when the task is product-facing or risky

`ROADMAP.md` must not contain a line beginning `SUPERGOAL_GOAL_BODY:`. Launch belongs in `LAUNCH_GOAL.md`.

## `STATE.md` and `runtime/STATE.json`

`STATE.md` is a human projection. After execution starts, package-local Python
authority owns `runtime/STATE.json`, `runtime/events.jsonl`, and projection
consistency. The projection must include:

- Goal identity / title
- Current phase (`1..N`, `AUDIT`, `BLOCKED`, or `DONE`)
- Total phases
- Baseline ref or explicit non-git baseline reason
- Status snapshot
- Delivery receipt state when file delivery is required
- Event ledger

## `LAUNCH_GOAL.md`

The only replyable/human launch surface. The generated file must include exactly one actual line beginning with the launch marker. Documentation should quote it with a leading `>` so it is not mistaken for a launchable artifact:

```text
> SUPERGOAL_GOAL_BODY: Resolve the package root, read its sealed contract/views and authoritative runtime state, execute through package-local Python authority, and finish only when the exact package-bound terminal record validates.
```

## `phases/phase-N.md`

Must pass `python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md`
from the package root. The shell wrapper is Unix compatibility only.

## Delivery receipts

Planning review receipt:

```json
{"ok": true, "sent": true, "kind": "review-md-files", "pack_version": "review_pack_v2", "target": "...", "files": ["THINKING.md", "LOOP_DESIGN.md", "ROADMAP.md", "LAUNCH_GOAL.md"], "hashes": {}}
```

Final artifacts receipt:

```json
{"ok": true, "sent": true, "target": "...", "archive": "...", "hash": "..."}
```

Receipts are evidence, not decoration. Missing or false receipts keep the run blocked.
