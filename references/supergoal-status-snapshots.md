# SuperGoal status snapshots

Use when SuperGoal execution needs human-readable progress in the style of Project Flow slice status, without importing Project Flow's supervisor, rails, or lane runtime.

## Why

The formal SuperGoal markers (`SUPERGOAL_PHASE_START`, `SUPERGOAL_PHASE_VERIFY`, `SUPERGOAL_PHASE_DONE`, `SUPERGOAL_TURN_YIELD`) are evaluator-friendly but operator-hostile. The operator needs the same quick readability as Project Flow slices: current phase, percent, health, evidence, next step.

## Contract

Print a compact `SUPERGOAL_STATUS` block at phase boundaries:

- after `SUPERGOAL_PHASE_START`
- before or inside `SUPERGOAL_PHASE_VERIFY`
- after `SUPERGOAL_PHASE_DONE`
- inside `SUPERGOAL_TURN_YIELD`
- on `FAILURE_PROBE`, `FAILURE_ESCALATE`, and `AUDIT_GAPS`

This is additive. Do not remove the formal markers; the evaluator still depends on them.

## Shape

```text
SUPERGOAL_STATUS
🚀 <title>
██████░░░░░░░░░░░░ <percent>%
Phase <N>/<total> · <pending|in_progress|verifying|done|blocked|audit> · updated <HH:MM>
▶️ <phase name>
┈ now: <current action>
┈ checks: build <pass|fail|—> · tests <pass|fail|—> · lint <pass|fail|—>
┈ evidence: <latest concrete proof or none>
┈ next: <VERIFY|DONE|TURN_YIELD|AUDIT|retry|handoff>
```

Failure variant:

```text
SUPERGOAL_STATUS
⚠️ <title>
██████░░░░░░░░░░░░ <percent>%
Phase <N>/<total> · retrying · attempt <1|2|3>/3
⛔ <failed criterion>
┈ hypothesis: <root cause>
┈ tried: <command/action>
┈ next: <auto-retry|fix-spec|handoff>
```

Audit variant:

```text
SUPERGOAL_STATUS
🧪 Audit: <title>
██████████████████ 100%
Audit round <R>/3 · <verifying|fixing|complete|handoff>
┈ commands: <pass/fail summary>
┈ gaps: <count + short title or none>
┈ coverage: <reverified>/<trust-prior>
┈ next: <AUDIT_COMPLETE|audit-fix|AUDIT_HANDOFF>
```

## Live status snapshot rendering inputs

Derive the snapshot at display time from sealed contract/phase names,
`runtime/STATE.json`, bound evidence, and the current audit. Do not add ad-hoc
fields to `runtime/STATE.json` or `STATE.md`: the state schema is strict and the
Markdown file must remain the exact generated projection. Last-action/check
summaries that are not canonical state belong in transcript status or bound
evidence, not a second persisted control plane.

## Pitfalls

- Do not turn SuperGoal into Project Flow. No pinned Telegram rail, supervisor, lanes, or StatusGate unless the user explicitly asks for a Project Flow run.
- Do not use status snapshots as completion proof. Completion requires successful `python scripts/sgctl.py validate-terminal` against the exact package-bound `reports/terminal-record.txt`; footer markers alone must continue.
- Do not spam long summaries. The snapshot must be readable in five seconds.
- Do not hide blockers behind green progress. If there is a retry, red command, or human handoff, the status headline must show it.
