# `/goal` format reference

## What `/goal` actually is

`/goal <end-state condition>` is a host slash command available in both Claude Code and Codex (Codex CLI). It is **not** a task description. It is a **measurable end-state condition** that a fast evaluator checks against the transcript after each agent turn. The agent keeps working — running tools, editing files — until the condition holds, at which point control returns to the user.

Key implications:

1. **Condition is short.** A long task body in the `/goal` argument is the wrong shape. Long content belongs in files the agent reads from disk.
2. **The evaluator only sees the transcript.** Conditions must be phrased so the agent's own output can prove them ("X printed", "Y exit code surfaced", "Z file count reported"). The evaluator does not independently run tools or read files.
3. **Host behaviour:**
   - **Claude Code**: a small fast model (Haiku) checks the condition each turn; "no" → continue with the reason as guidance; "yes" → clear goal, return control.
   - **Codex**: auto-continuation loop drives the goal to terminal status (complete / budget_limited / paused / cleared). Five subcommands: `/goal <objective>`, `/goal` (status), `/goal pause`, `/goal resume`, `/goal clear`.

## Supergoal's single-`/goal` shape

Supergoal uses **one** `/goal` per run, dispatched by the **user** at the end of Stage 7. Slash commands fire only from user input on both Claude Code and Codex — the planner cannot fire `/goal` from its own message text. Stage 7's job is to write all phase specs to disk, then print a copy-paste-ready `/goal` block. The user pastes once; from there, the run is autonomous.

The condition is:

```
Resolve the sealed package root and read authoritative runtime/STATE.json.
Execute all phases of ROADMAP.md sequentially. Read phases/phase-N.md;
do the work;
run mandatory commands; print SUPERGOAL_PHASE_VERIFY then
SUPERGOAL_PHASE_DONE; transition state through scripts/sgctl.py; immediately continue to the
next phase/audit. Do not stop at phase boundaries. Use
SUPERGOAL_TURN_YIELD only for forced platform cutoff or a real
safety/approval blocker. Weak blockers are forbidden: private
verification/readback, local checks, read-only probes, usage/log
queries, report/state writes, and requested repo cleanup are not
approval blockers. Follow the failure-recovery protocol in
.supergoal/PROTOCOL.md if any criterion fails. After the last numbered
phase, enter AUDITING through package-local state authority and run the
FINAL AUDIT in PROTOCOL.md (re-verify against ROADMAP.md; re-run aggregated
mandatory commands; spot-check criteria; on gaps, write
audit-fix-<round>.md and execute inline). After a clean audit and legal
DONE transition, run python scripts/sgctl.py finalize and require
python scripts/sgctl.py validate-terminal to accept reports/terminal-record.txt.

Done only when validate-terminal succeeds for the current package. Then print
the exact finalized record, which contains AUDIT_COMPLETE before
SUPERGOAL_RUN_COMPLETE and Goal complete: yes. Footer text without the
validated package record means continue.
```

This works on both hosts. There is no per-phase `/goal` dispatch and no inter-session chain — once active, a single `/goal` session reads PROTOCOL.md, loops through every phase spec, runs the final audit, and only completes when the exact package terminal record validates.

## Required transcript blocks (Supergoal-specific)

The phase specs and PROTOCOL.md require the agent to print these named blocks during execution. They are what the human-readable evaluator (you, watching) AND the host evaluator both rely on.

### `SUPERGOAL_PHASE_START` (once per phase, at execution start)

```
SUPERGOAL_PHASE_START
Phase: <N> of <total> — <name>
Task: <one-line from ROADMAP.md>
Type: <greenfield|brownfield|bugfix|refactor|ui>
Mandatory commands: <comma-separated list>
Acceptance criteria: <count>
Evidence required: <comma-separated types>
Depends on phases: <list, or "none">
```

### `SUPERGOAL_PHASE_VERIFY` (once per phase, before DONE)

```
SUPERGOAL_PHASE_VERIFY
Acceptance:
- <criterion 1>: <pass|fail> — <evidence>
- <criterion 2>: <pass|fail> — <evidence>
...
Engineering:
- build: <pass|fail>
- typecheck: <pass|fail>
- lint: <pass|fail|pre-existing>
- tests: <pass|fail|N pre-existing>
Cleanliness (platform-native complete working-tree delta vs Baseline ref; optional Unix repo-state helper is supporting evidence only):
- debug prints added (console.log / print / etc.): <count>
- session TODO/FIXME added: <count>
- dead imports added: <count>
Files changed: <count>
Notable diffs:
- <file>: <one-line summary>
```

### `MEMORY_SAVED` (once per phase, between VERIFY and DONE)

```
MEMORY_SAVED: <memory-name>     (or "none — nothing non-obvious this phase")
```

### `SUPERGOAL_PHASE_DONE` (once per phase, final completion block of the phase)

```
SUPERGOAL_PHASE_DONE
Phase <N> complete. Authoritative state transition recorded; STATE.md projection current.
```

### `SUPERGOAL_TURN_YIELD` (only at a real blocker or host-forced cutoff)

```
SUPERGOAL_TURN_YIELD
Next: <phase N+1 | AUDIT>
Reason: <real blocker or host-forced cutoff>.
```

This is not a completion marker or routine phase boundary. Safe numbered phases
continue in the same run; a later turn resumes from `runtime/STATE.json` only
when the host actually forces a cutoff or a real gate blocks progress.

### `AUDIT_START` (once per audit round, after the last phase)

```
AUDIT_START
Round: <1|2|3>
Phases to verify: <N>
Criteria to re-check: <count>
Commands to re-run: <comma-separated, deduplicated set>
```

### `AUDIT_VERIFY` (once per audit round, after re-checks complete)

```
AUDIT_VERIFY
Per-phase completeness:
- Phase 1: <DONE present | DONE missing>
- Phase 2: ...
Re-run mandatory commands:
- <cmd>: exit <code> — <last line>
- ...
Acceptance criteria spot-check:
- Phase 1 / "<criterion>": <pass | fail | trust-prior-verify> — <evidence>
- ...
Deliverables (bound evidence against the complete working-tree baseline):
- Phase 1 / "<deliverable bullet>": <present | missing> — <platform-native evidence record>
- Phase 2 / "<deliverable bullet>": <present | missing> — <evidence>
- ...
Summary: <pass count> pass, <fail count> fail, <trust count> trust-prior, <missing count> deliverable-gaps
```

### `AUDIT_GAPS` (only if gaps found this round)

```
AUDIT_GAPS
Round: <N>
Gaps:
- <gap 1>: <details>
- <gap 2>: <details>
Writing fix spec at .supergoal/phases/audit-fix-<N>.md, executing inline.
```

### `AUDIT_COMPLETE` (zero gaps — compatibility projection, not authority)

```
AUDIT_COMPLETE
Rounds: <N>
Phases re-verified: <count>
Commands re-run clean: <count>
Acceptance criteria: <pass count> pass / <0> fail / <trust count> trust-prior
Deliverables: <present count> present / <0> missing
Audit coverage: <re_verified> re-verified / <trust> trust-prior (<pct>%)
```

### `AUDIT_HANDOFF` (3 audit rounds all failed — stop)

```
AUDIT_HANDOFF
Round: 3
Persistent gaps:
- <gap>
- ...
Three audit rounds attempted; fix specs at .supergoal/phases/audit-fix-{1,2,3}.md
Suggested next move: <one line>
Authoritative state transitioned to `BLOCKED`; `STATE.md` projection refreshed.
```

### `SUPERGOAL_RUN_COMPLETE` (inside the exact finalized terminal record only)

```
SUPERGOAL_TERMINAL v1 goal=<goal-id> contract_sha256=<sha256> contract_revision=<n> state_revision=<n> audit_sha256=<sha256>
AUDIT_COMPLETE
SUPERGOAL_RUN_COMPLETE
Goal complete: yes
END_SUPERGOAL_TERMINAL
```

Do not hand-compose this block. Run `python scripts/sgctl.py finalize`, then
`python scripts/sgctl.py validate-terminal`; the exact record binds current
state, recomputed audit, inventory, and delivery authority.

## Failure blocks (used by recovery protocol)

### `FAILURE_PROBE` (first failure)

```
FAILURE_PROBE
Phase: <N> — <name>
Failed criterion: <text>
Tried: <what was attempted>
Hypothesis: <root cause guess>
Next: auto-retry with probe injected
```

### `FAILURE_ESCALATE` (second failure — fix spec)

```
FAILURE_ESCALATE
Phase: <N> — <name>
Failed criterion: <text>
Retry probe history:
  attempt 1: <summary>
  attempt 2: <summary>
Writing fix spec at .supergoal/phases/phase-<N>.fix.md
```

### `FAILURE_HANDOFF` (third failure — stop)

```
FAILURE_HANDOFF
Phase: <N> — <name>
Failed criterion: <text>
Three attempts tried:
  1. <summary>
  2. <summary>
  3. <fix spec summary>
Suggested next move: <one line>
Authoritative state transitioned to `BLOCKED`; `STATE.md` projection refreshed. User intervention required.
```

## Anti-patterns

- **Don't stuff long task content into the `/goal` argument.** Use a short condition; put work in files.
- **Don't treat marker prose as evidence.** Tests, state, audit, and completion must be bound to package-owned machine-readable records.
- **Don't chain `/goal` commands across sessions.** One run = one `/goal`. The agent loops internally inside that session.
- **Don't skip evidence to save space.** Files have no char budget — be exhaustive.
- **Don't stop at safe numbered phase boundaries.** Continue through phases and audit until a real gate, real blocker, host-forced cutoff, or validated terminal record.
