# chip-supergoal execution protocol

This protocol describes how a standard Hermes `/goal` executor reads a sealed
v3 package. Protocol prose is not authority for contract intent, runtime state,
evidence, approvals, delivery, audit results, or terminal completion.

## Authority and package root

- Resolve the package root as the parent directory of the `LAUNCH_GOAL.md` being executed.
- Resolve every path below relative to that package root.
- `CONTRACT.json` is the authority for declared execution intent.
- `runtime/STATE.json` is the authoritative runtime state.
- `STATE.md` is a generated projection of `runtime/STATE.json`, never an independently editable state store.
- Generated Markdown is an executor view. If it disagrees with its authority, package validation must fail closed.

Do not infer a package directory name. Do not substitute a compile-time output
path after a package has been moved.

## Python-authoritative package operations

Run currently implemented compiler/validation operations from the package root
through the packaged Python entry point:

```text
python scripts/sgctl.py validate-package . --strict
python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated
python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md
python scripts/sgctl.py research-gate CONTRACT.json --format json
```

The research command is applicable only when `RESEARCH.md` is emitted.

The package-local runtime/evidence/finalization control plane is:

```text
python scripts/sgctl.py state-show
python scripts/sgctl.py state-transition --to <lifecycle> --expected-revision <n>
python scripts/sgctl.py state-recover
python scripts/sgctl.py record-evidence --input -
python scripts/sgctl.py audit
python scripts/sgctl.py finalize
python scripts/sgctl.py validate-terminal
```

`record-evidence --input -` reads one strict JSON EvidenceRecord from standard
input. Same-lifecycle phase/status/attempt updates use `state-transition`
without `--to` (or with `--to` equal to the current lifecycle) and always name
the expected state revision. Do not replace these commands with a manual state
edit, ad-hoc evidence record, prose-only audit, or terminal-record generator.

## Optional Unix compatibility notes

The Python commands above remain authoritative. On Unix hosts only, these
package-relative validation wrappers are optional compatibility conveniences:

```text
bash scripts/validate-loop-design.sh --instantiated LOOP_DESIGN.md
bash scripts/validate-phase.sh phases/phase-NN.md
```

No runtime state, evidence, audit, finalize, or terminal operation has a shell
fallback.

## Launch context and preflight

Read `CONTRACT.json`, `THINKING.md`, `LOOP_DESIGN.md`, `ROADMAP.md`,
`runtime/STATE.json`, its `STATE.md` projection, `PROTOCOL.md`, and every emitted
`phases/phase-NN.md`. Read `RESEARCH.md` only when it exists in the sealed
package.

Before executing a phase, run:

```text
python scripts/sgctl.py validate-package . --strict
```

A non-zero result is `PREFLIGHT_RED`; a zero result is `PREFLIGHT_GREEN`.
Correct package drift before relying on a generated view.

## Contract boundaries

Use the exact `approvals` and resolved `delivery` values in `CONTRACT.json` and
the lossless projections in `LAUNCH_GOAL.md` and `ROADMAP.md`. If a boundary is
absent, its value is `not declared by CONTRACT.json`; do not invent one from
operator history, profile stereotypes, or protocol prose.

`BLOCKED_BY_APPROVAL` is applicable only to an unmet approval whose record has
`required: true` and whose exact class and scope match the current action.
Delivery is blocking only when the resolved delivery contract says so.

## Phase execution

Select the current phase from `runtime/STATE.json`. Validate its generated view
with the Python command above, then execute the work items and commands exactly
as declared. The phase contract contains lossless records for dependencies,
work items, deliverables, criteria, verifier fields, commands, risk tags, and
all RPD focus values.

`SUPERGOAL_PHASE_START`, `SUPERGOAL_STATUS`, `SUPERGOAL_PHASE_VERIFY`,
`RPD_PHASE_REVIEW`, and `SUPERGOAL_PHASE_DONE` are transcript compatibility
markers. They do not replace evidence records or state transitions.
Do not stop at numbered phase boundaries while a dependency-ready phase remains
and no contract-declared boundary blocks progress. Weak blockers are forbidden:
a blocker must point to the exact contract record that makes it blocking.
Inside `RUNNING`, phase advancement may select only a dependency-ready phase
that is not already complete; completed phases reopen only through explicit
audit remediation.

When the host forces a cutoff before authoritative completion, the compatible
yield footer is:

```text
SUPERGOAL_TURN_YIELD
Goal complete: no
Next: <phase-id|AUDIT|contract-declared blocker>
Completion requires: AUDIT_COMPLETE and SUPERGOAL_RUN_COMPLETE in the same final response.
```

## State projection

Never hand-edit `STATE.md` or treat conversation context as state. State transitions and
their projection belong to the packaged Python runtime. If
`runtime/STATE.json` and `STATE.md` disagree, stop using the projection and let
`python scripts/sgctl.py validate-package . --strict` report the drift.
Run `python scripts/sgctl.py state-recover` only as an explicit projection
replay from a fully valid journal; journal corruption is never swallowed.

## Final audit

After the declared phases, re-read `ROADMAP.md`. Audit every phase dependency,
work item, deliverable expectation and verification, blocking criterion,
evidence tier, verifier type/command/exit/assertion, command purpose/safety/
timeout, risk tag, and RPD focus. `AUDIT_START`, `AUDIT_VERIFY`,
`RPD_FINAL_REVIEW`, `AUDIT_GAPS`, `AUDIT_HANDOFF`, and `AUDIT_COMPLETE` are
compatibility marker names, not evidence by themselves.

`FAILURE_PROBE`, `FAILURE_ESCALATE`, and `FAILURE_HANDOFF` may describe failure
handling only when the declared loop contract supplies the corresponding retry,
recovery, or handoff rule. Otherwise that behavior is `not declared by
CONTRACT.json`.

Enter `AUDITING`, record all evidence, then run `python scripts/sgctl.py audit`.
Evidence must match the declared verifier type as well as its command, exit,
and assertion. Approval and delivery records are auxiliary evidence: they may
satisfy their own policy gates but never substitute for criterion proof. Bind
phase-scoped auxiliary records with `criterion_id: "__phase__"`, including on
phases that declare no criteria.
Only an unchanged clean audit authorizes `state-transition --to DONE`; that
transition immediately recomputes the audit against the DONE revision. Run
`finalize` only after that recomputation. Required delivery receipts may bind a
pre-terminal external archive, but the archive does not create terminal
authority. `AUDITING` and `DONE` keep the active phase `COMPLETE` and unblocked.
When an audit finds a repairable gap, `AUDITING -> RUNNING` may reopen any
previously completed phase as `EXECUTING` or `VERIFYING`; the next audit entry
starts a new audit round. Reopening invalidates completion of that phase and
every transitively dependent phase, all of which must be completed again before
audit re-entry.
The audit and terminal record also bind to the current sealed package inventory;
missing manifests, generated drift, symlinks, junctions, or hash mismatches
invalidate completion.

## Standard Hermes `/goal` compatibility

Use one standard Hermes `/goal` body from `LAUNCH_GOAL.md`. Do not start a custom
runner or nested `/goal`. The upstream host may use the documented markers to
decide whether to continue, but markers never supersede package authority.

Exact terminal marker documentation:

```text
AUDIT_COMPLETE
SUPERGOAL_RUN_COMPLETE
Goal complete: yes
```

The three lines must appear in the same final response for host compatibility.
Do not use `Goal complete: yes` anywhere else. This documentation does not
generate a terminal record and does not make protocol prose completion
authority. The only machine-authoritative completion record is the exact
five-line UTF-8/LF `reports/terminal-record.txt` written and printed by
`python scripts/sgctl.py finalize`; `validate-terminal` binds it to the current
DONE state and exact `reports/final-audit.json` bytes.
