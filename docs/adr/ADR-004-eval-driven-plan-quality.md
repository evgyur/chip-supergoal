# ADR-004: Eval-driven plan quality authority

- Status: Accepted for candidate implementation
- Date: 2026-07-14
- Foundation: `5725192154dfca78032e861edbd29570bb2d94e8`
- Rollback: `35a22fe5bc4821559d9a186579bc1ea07ad6ac33`
- Reviewed plan SHA-256: `a269af6b6f7190a383d090430ec7ad155c474aa49646d15321d115c4177f132e`
- Promotion status: baseline freeze only; no default behavior changes

## Context

The existing compiler proves structural and runtime correctness. It does not prove that a plan covers the user's real requirements, chooses a sound architecture, exposes critical assumptions, or avoids unnecessary layers. Five independently reviewed B2 fixtures demonstrate this false-green class while still passing the old structural shape checks.

The selected whole-hardening foundation remains the runtime authority because B2 showed concrete reliability value, native Windows support, and no unresolved P0/P1 findings. Quality work is an opt-in layer above that foundation; it does not replace the state machine, evidence model, archive, delivery, or GoalManager compatibility contract.

## Decision

Adopt an eval-driven architecture with two candidate layers:

1. **B — deterministic quality contract and linter.** Fail closed on objective omissions, broken traceability, inconsistent policy routing, missing rollback, unbound critical assumptions, and structurally fake behavioral evidence.
2. **C — bounded semantic critic and targeted repair.** Use only when policy recomputation requires it. Allow at most two repair cycles, then stop.

Promotion authority belongs to blind evaluation and canary evidence, not to either candidate layer's self-report.

## Canonical planning authority

`CONTRACT.json.subject` is the single authority for quality-specific intent, requirements, constraints and non-goals, assumptions and falsifiers, architecture options, traceability, failure modes and rollback, permission/source-of-truth boundaries, the overengineering ledger, and budgets.

Existing top-level contract fields remain authoritative for their established runtime meanings. Generated Markdown and `reports/plan-quality.json` are projections or derived evidence. They may repeat stable identifiers, but copied planning text must match the canonical subject exactly and never becomes a second writable authority.

No hidden chain-of-thought is stored. Durable records contain claims, evidence, decisions, findings, mutations, checked holds, and costs.

## Acyclic hash DAG

Hash direction is fixed and acyclic:

```text
source inputs + policy/profile versions
              │
              ▼
canonical CONTRACT.json subject (attestation omitted from subject hash)
              │
              ├──► deterministic findings
              ├──► critic findings / bounded mutation ledger
              └──► final subject hash
                          │
                          ▼
                 reports/plan-quality.json
                          │
                          ▼
              attestation locator + report hash
                          │
                          ▼
                   final package MANIFEST
```

The report never hashes a manifest that already hashes the report. Attestation fields bind the report only after the canonical subject hash is stable. The final package manifest closes the DAG.

## Profile isolation and compatibility

- `quality-canary` is opt-in until a later promotion ADR says otherwise.
- Without the quality profile, compiler inputs and deterministic generated package bytes must remain compatible with the frozen selected-foundation outputs.
- Candidate tests execute separately from the immutable baseline adapter.
- The baseline adapter runs the compiler from a clean detached worktree pinned to the selected SHA or validates captured outputs cryptographically bound to that SHA.
- Candidate code may not reinterpret the moving current checkout as the baseline.
- Linux and native Windows evidence remain separate, hash-bound capability records.

## Budgets and stop rules

- Baseline B-only makes zero semantic-review model calls.
- B+C allows at most two critic/repair cycles.
- Prompt growth versus the frozen baseline must not exceed 10% for the canary profile.
- The final benchmark uses the preregistered `±6.25/100` MCID and the promotion policy frozen before sealed scoring.
- Timing, package size, token, and semantic-review costs are reported separately; no weighted aggregate may hide a hard regression.
- A repair cycle counts as progress only when it closes a named finding, adds a missing traceability edge, resolves a falsifiable assumption, removes an unnecessary layer, or changes an independently scored rubric dimension.
- If a cycle makes no measurable progress, stop immediately. Never run a third repair cycle.
- Unresolved policy/critic P0 or P1 findings block candidate publication and promotion.

## Deletion and rollback rules

Every new module, prompt, agent stage, compatibility shim, data flow, or policy layer must map to a reproduced failure class and a regression test. Delete or keep disabled any layer that:

- has no unique failure class or duplicates another authority;
- fails its preregistered incremental-gain gate;
- increases cost without closing a hard failure or clearing the MCID;
- cannot preserve profile-off compatibility;
- requires a third repair cycle or weakens the no-progress stop;
- leaks private sources, hidden reasoning, sealed labels, or live traces;
- cannot run within the approved Linux/native-Windows containment boundary;
- leaves no deterministic rollback to the selected foundation.

If C fails its incremental-gain/removal gate, delete C and retain B only. If B cannot bound false blocks, retain report-only mode and keep default strict behavior unchanged. If the final promotion study fails, ship a no-go ADR and retain the frozen baseline default.

## Non-goals

- Replacing the SuperGoal executor, state machine, evidence authority, archive, or delivery protocols.
- Making longer plans or more personas a success metric.
- Promoting from development fixtures, self-authored scores, or one polished demonstration.
- Tuning against sealed holdout labels.
- Changing production/default planner behavior in QL-00.

## Evidence and review

The baseline freeze must bind:

- foundation capability and provenance manifests;
- selected/rollback commit and tree hashes;
- compiler adapter and prompt/reference file hashes from the selected commit;
- three representative contract/package fingerprints;
- all five B2 false-green fixture and independent-review hashes;
- profile-off byte-compatibility results;
- this ADR and the reviewed plan hash.

RPD integration review is mandatory at phase closeout. A later phase may amend this ADR only through a new ADR with explicit hash migration and no retroactive change to frozen benchmark thresholds.

## Consequences

The system gains a measurable quality authority without making semantic review ubiquitous or turning derived reports into a second source of truth. The cost is a larger evaluation surface and explicit profile/policy plumbing. That cost is accepted only under the deletion rules above and remains reversible to the selected foundation.
