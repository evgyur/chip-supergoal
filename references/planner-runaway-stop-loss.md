# Planner runaway stop-loss

Use this guard for every Chip-facing SuperGoal planning run. It exists because a planning task once produced a valid-looking package but consumed roughly 500 tool calls without delivering the required three-file startup pack.

## Incident pattern

The failure sequence was:

1. The planner produced the requested package.
2. Independent review found real defects.
3. Instead of repairing only the package, the planner began redesigning the shared `chip-supergoal` infrastructure.
4. Several review generations were launched in succession; late asynchronous verdicts referred to different candidates.
5. Each new finding triggered another infrastructure patch and another review.
6. Some large edits were damaged by literal truncation placeholders, creating repair work unrelated to the user outcome.
7. Fail-closed review correctly prevented delivery, but there was no stop-loss that converted repeated failure into a concise blocked handoff.

The user received no usable deliverable despite a large amount of internal work.

## Root causes

- **Outcome displacement:** “improve the planner” replaced “deliver this plan.”
- **Unbounded review recursion:** no maximum review generation and no single-review-in-flight invariant.
- **Shared-control-plane drift:** mission work mutated the source skill and compiler while the package was being reviewed.
- **Candidate ambiguity:** callbacks from older candidates remained active after newer candidates existed.
- **No blocked terminal:** fail-closed was treated as “keep repairing forever” instead of “stop after the bounded budget and report the exact blocker.”
- **Oversized edits:** large patches were accepted without scanning for literal truncation markers and syntax-checking immediately.

## Governing rules

### 1. Freeze the planner during a mission

Once a package compiles, treat the installed `chip-supergoal` skill, compiler, templates, and delivery infrastructure as read-only for that mission.

A shared-skill fix is allowed only when all three conditions hold:

1. the defect makes compilation, strict validation, or canonical delivery impossible;
2. the fix is narrower than the mission package itself;
3. it can be completed in one patch-and-test cycle.

Otherwise record the defect for separate maintenance and continue or block the current package honestly. Do not turn a user’s SuperGoal into a redesign of SuperGoal.

### 2. One review in flight

Never dispatch a second blocking semantic review while another review is queued or running. A callback for a candidate whose hash is not the current bound candidate is historical evidence, not a verdict and not a reason to restart work.

### 3. Maximum two review rounds

The default planning budget is exactly two blocking semantic-review rounds:

- Round 1: discover and repair concrete P0/P1 findings.
- Round 2: closure review of the repaired exact candidate.

If round 2 is not `GO` with `P0=0` and `P1=0`, stop. Do not launch round 3. Produce a compact `SUPERGOAL_REVIEW_BLOCKED` handoff containing the package path, current candidate hash, unresolved findings, and the smallest next repair. Ask Chip whether to continue only if he explicitly wants another maintenance cycle.

### 4. Maximum one meta-fix cycle

During one user package, at most one shared-skill/compiler/delivery-infrastructure fix cycle is permitted. A second meta defect is a maintenance blocker, not permission to keep expanding scope.

### 5. Artifact-first execution

The order is fixed:

1. compile the user package;
2. run deterministic package checks;
3. run one semantic review;
4. repair only the reported package findings;
5. run one closure review;
6. deliver on `GO`, otherwise stop with a blocked handoff.

Do not add architecture, receipts, leases, reviewer authentication, delivery machinery, or new generalized abstractions unless the current canonical contract already requires them and the package cannot pass without the narrow fix.

### 6. Small edits with immediate integrity checks

After every edit to planner infrastructure:

- scan changed files for literal `...[truncated]` and `[truncated]` placeholders;
- run syntax checks for the edited language;
- run the narrow regression first;
- run the full skill suite once after all narrow checks pass.

If an edit is corrupted, restore the last known-good file before further mutation. Do not patch on top of uncertain bytes.

## Executable guard

Use `scripts/planner-stop-loss.py` with a mutable ledger under the package `out/` directory:

```bash
python3 scripts/planner-stop-loss.py init --package-root <package>
python3 scripts/planner-stop-loss.py pre-review --package-root <package> --candidate-sha <sha256>
python3 scripts/planner-stop-loss.py review-result --package-root <package> --candidate-sha <sha256> --verdict NO_GO --p0 0 --p1 2
python3 scripts/planner-stop-loss.py meta-fix --package-root <package> --reason '<narrow blocking defect>'
python3 scripts/planner-stop-loss.py status --package-root <package>
```

The guard fails closed when:

- a review is already in flight;
- a result does not match the in-flight candidate;
- a third review is attempted;
- a second meta-fix cycle is attempted;
- round 2 closes without `GO`, `P0=0`, `P1=0`.

The ledger is runtime state, not immutable package identity and not a user-facing attachment.

## Regression matrix

The guard tests must prove:

- first review can start;
- a concurrent second review is rejected;
- result candidate mismatch is rejected;
- one repair and one second review are allowed;
- a third review is rejected after round-2 `NO_GO`;
- exactly one meta-fix is allowed and the second is rejected;
- a round-1 clean `GO` reaches terminal `go`;
- a normal package that needs no meta-fix remains usable.

## Required visible behavior

A blocked planner says what exists and why it is not launchable. It does not claim readiness, does not send the startup pack, and does not silently consume another review cycle.
