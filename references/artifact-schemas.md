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

```bash
bash scripts/validate-loop-design.sh templates/LOOP_DESIGN.md
```

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

## `STATE.md`

Must include:

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
> SUPERGOAL_GOAL_BODY: From the project root, execute the SuperGoal in `<SUPERGOAL_ROOT>` using `<SUPERGOAL_ROOT>/PROTOCOL.md`, `<SUPERGOAL_ROOT>/LOOP_DESIGN.md`, `<SUPERGOAL_ROOT>/ROADMAP.md`, `<SUPERGOAL_ROOT>/STATE.md`, and `<SUPERGOAL_ROOT>/phases/phase-*.md`. Start from STATE.md current phase, continue through numbered phases, run the final audit, and finish only after AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE.
```

## `phases/phase-N.md`

Must pass `scripts/validate-phase.sh`. See root Phase spec contract.

## Delivery receipts

Planning review receipt:

```json
{"ok": true, "sent": true, "kind": "startup-files", "pack_version": "startup_pack_v4", "target": "...", "files": ["THINKING.md", "ROADMAP.md", "LAUNCH_GOAL.md"], "hashes": {"THINKING.md": "<sha256>", "ROADMAP.md": "<sha256>", "LAUNCH_GOAL.md": "<sha256>"}, "message_ids": ["<id1>", "<id2>", "<id3>"], "file_message_ids": {"THINKING.md": "<id1>", "ROADMAP.md": "<id2>", "LAUNCH_GOAL.md": "<id3>"}, "launch_file": "LAUNCH_GOAL.md", "launch_message_id": "<id3>"}
```

Final artifacts receipt:

```json
{"ok": true, "sent": true, "target": "...", "archive": "...", "hash": "..."}
```

Receipts are evidence, not decoration. Missing or false receipts keep the run blocked.
