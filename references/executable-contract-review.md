# Executable contract review for SuperGoal packages

Use when independently reviewing a generated package for false completion, wrong-root execution, stale progression, approval drift, or commands that cannot actually run. Structural phase validators are necessary but not sufficient.

## Review objective

Audit the package as one executable state machine, not as a collection of plausible Markdown files. Trace one run from planner state through every phase, approval stop, final audit, delivery check, and terminal marker. Every command must have a defined working directory, target, mutation class, and evidence output.

## 1. Root and baseline trace

Build a root table before reviewing phase semantics:

| Field | Required meaning |
|---|---|
| Package root | Stable location of STATE, PROTOCOL, phases, scripts, evidence, and receipts |
| Source/recon root | Checkout inspected by the planner |
| Active execution root | Checkout/worktree where the current phase mutates and verifies code |
| Baseline ref | Exact base commit for the active execution root, not merely the planner's current HEAD |

Required checks:

- PROTOCOL explicitly establishes the working directory; a launch file merely naming an implementation root is not enough.
- Relative commands run under the intended package/repository/subproject root.
- If a phase creates a clean worktree, STATE and PROTOCOL define an atomic transition to that worktree for all later phases.
- `repo-state.sh` or equivalent runs against the active worktree and its own base commit.
- A prod-based candidate must not retain a divergent beta/audit SHA as its cleanliness or deliverable baseline.
- Use `git -C <root>` or explicit `cd <root>` for commands whose correctness depends on cwd.

Wrong-root defects are material because they can make tests pass against old code, make cleanliness checks vacuous, or attribute pre-existing branch divergence to the current run.

## 2. Command executability and interface compatibility

For every mandatory command, verify:

1. the command exists now or is an explicit earlier-phase deliverable;
2. its cwd contains the required manifest/config (`package.json`, `pyproject.toml`, etc.);
3. placeholders are replaced by values the called script accepts;
4. the called script's argument allowlist and preconditions match the phase contract;
5. a command intended to mutate actually has a mutation invocation, not only `--preflight`, `--dry-run`, or validation mode;
6. outputs map to required receipts/evidence;
7. a later phase does not assume an unplanned commit, push, branch promotion, or remote ref update.

Typical fixes:

- use `npm --prefix <subproject> ...` or explicit `cd` when the repo root has no package manifest;
- add a controlled candidate commit/promotion step when a deploy script only accepts `origin/prod`;
- replace `<approved-exact-ref>` with a manifest-pinned value and verify local HEAD, remote ref, approved SHA, and deploy SHA are identical;
- specify distinct preflight and apply commands for migrations.

## 3. Mutation classification for final audit

Annotate every command as one of:

- `verify-read-only`
- `verify-idempotent`
- `setup-local`
- `mutate-repo`
- `mutate-production`
- `destructive/high-risk`

The final audit may rerun only read-only or genuinely idempotent verification commands. It must not blindly rerun the union of all phase commands.

Never rerun during audit:

- production deploy/restart;
- migration apply;
- worktree creation;
- force-push/history rewrite;
- provider/secret mutation;
- public send;
- destructive restore;
- any action whose bounded approval authorized one execution.

Audit those actions through immutable receipts, exact live SHA/readback, DB reconciliation, service health, protected-content probes, and action-count evidence.

## 4. Phase/audit ownership

Terminal audit artifacts and markers have one owner.

- The last numbered phase may prepare aggregate checks and audit inputs.
- Only the `AUDIT` state produces `RPD_FINAL_REVIEW`, final audit verdict, `AUDIT_COMPLETE`, and `SUPERGOAL_RUN_COMPLETE`.
- Do not require a numbered phase to provide markers that the protocol can produce only after that phase advances STATE to `AUDIT`.
- If Phase N is itself the sole final audit, remove the second protocol audit instead of duplicating ownership.

A duplicate final-audit layer causes deadlock or premature completion markers.

## 5. Ignored package evidence

`.supergoal/` is commonly git-ignored. A Git-diff deliverable verifier using `git ls-files --others --exclude-standard` cannot prove newly generated ignored evidence; it may classify a real file as unchanged or missing.

Use two proof lanes:

- implementation deliverables: Git-aware comparison against the active execution baseline;
- package evidence/receipts: package-aware verification of path, non-empty content, schema/marker validity, checksum, timestamp/event linkage, and phase identity.

Do not force ignored package evidence through a tracked-file verifier. Alternatively, place required evidence in a tracked repository evidence directory.

## 6. Approval and delivery semantics

- A bounded approval must identify target, exact action, SHA/checksum, stop conditions, rollback class, and whether it authorizes one execution or a repeatable operation.
- Final audit must not replay an approved mutation.
- Planning review delivery blocks dispatch, not product completion after the user explicitly launched anyway.
- After launch, a missing planner review receipt is a nonblocking warning, not an `AUDIT_GAP`; otherwise the generic gap loop can incorrectly end in `AUDIT_HANDOFF`.
- Final-artifact delivery remains blocking only when requested by the goal.

## 7. State-machine simulation

Manually simulate these transitions:

```text
PLANNING_REVIEW
  -> READY_TO_DISPATCH
  -> PHASE_1 ... PHASE_N
  -> BLOCKED_BY_APPROVAL (optional, exact manifest)
  -> PHASE_N continuation
  -> AUDIT
  -> COMPLETE/DONE
```

At each transition ask:

- What exact STATE mutation occurs?
- What command runs next and in which cwd?
- Can the required evidence exist at that point?
- Can a blocker accidentally count as a pass?
- Can a repeated continuation rerun a mutation?
- Can completion markers appear while STATE is still in a numbered phase?

## 8. Minimum independent-review probes

In addition to phase and loop validators:

- assert exactly one launch-body line;
- compare phase count across ROADMAP, STATE, LOOP_DESIGN, and phase headers;
- inspect package-manager roots;
- inspect deploy/apply script argument contracts;
- enumerate mutation commands and ensure audit excludes them;
- verify active root/baseline after every worktree transition;
- test one tracked deliverable and one ignored package-evidence deliverable through the declared verifier;
- cross-check review-receipt wording against generic audit-gap handling;
- confirm the final numbered phase does not require post-phase audit markers.

Report only material findings with severity, file/section, failure scenario, direct evidence, and a concrete cross-file fix.