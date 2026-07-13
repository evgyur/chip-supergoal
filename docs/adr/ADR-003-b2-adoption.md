# ADR-003: Adopt the whole B2 hardening foundation

- Status: Accepted for implementation
- Date: 2026-07-13
- Decision owner: SuperGoal `sg-20260714-chip-supergoal-quality-leap`, phase P01
- Selected SHA: `5725192154dfca78032e861edbd29570bb2d94e8`

## Context

The repository has a 29-commit, 151-file hardening range between clean main (`35a22fe5bc4821559d9a186579bc1ea07ad6ac33`) and `fix/b2-hardening` (`5725192154dfca78032e861edbd29570bb2d94e8`). The range mixes portable contract work, sealed runtime authority, native Windows behavior, archive/delivery hardening, and release closure.

Plain main cannot be selected because the quality-leap plan requires `native_windows_v1`, self-contained packages, authoritative runtime state, deterministic archive/recovery, and cross-platform receipts.

## Decision

Adopt the **whole hardening SHA** as the foundation for subsequent quality-leap work.

Do not:

1. return to plain main;
2. cherry-pick an ad hoc subset without rerunning the neutral harness;
3. treat branch-authored test count or green CI as proof of value;
4. claim measured plan-quality improvement from this infrastructure audit.

## Evidence

The preregistered neutral audit records:

- 29/29 commits and 151/151 changed files assigned exactly once;
- Linux failures for main and cumulative compositions through C3;
- Linux success beginning at through-C4;
- Linux success for whole hardening;
- native Windows success for whole hardening on Python 3.11.9 and 3.13.14;
- native Windows failure for clean main on both versions;
- zero unresolved P0/P1 findings;
- five frozen semantic false-green fixtures with no powered equivalence claim.

Canonical evidence:

- `docs/b2-hardening-value-audit.md`
- `evals/baselines/b2-branch-comparison.json`
- `evals/b2/b2-disposition-manifest.json`
- `evals/b2/results/windows/`
- `evals/b2/results/rpd-review.json`

## Why whole adoption beats curation

C1–C3 remain necessary foundations but do not independently close the neutral probe. C4 is the first cumulative passing boundary. C5 carries native release closure and is required to preserve the declared compatibility foundation. Removing clusters based only on local passing tests would recreate the exact false-green risk this phase is designed to eliminate.

## Consequences

### Positive

- Packages are self-contained and validate without ambient repository imports.
- `runtime/STATE.json` remains authoritative.
- Native Windows capability coverage is preserved.
- Archive publication and recovery are deterministic and evidence-linked.
- Cluster and commit ownership is explicit and reversible.

### Costs

The candidate is larger and slower than clean main under the frozen Linux probe:

- compile p50: 0.2584 s (+288.654%);
- compile p95: 0.2643 s (+244.732%);
- archive p50: 0.4277 s (main has no comparable archive command);
- archive p95: 0.4345 s (main has no comparable archive command);
- package size: 743,321 bytes (+2350.374%).

These exceed the relative margins. We accept explicit exceptions because compile/archive p95 remains below 0.5 seconds and the self-contained package remains below 1 MiB. This is not a non-inferiority claim.

### Unproven

Direct plan-quality improvement is not measured. The five false-green fixtures freeze known failure classes, but the sample is not a powered 2×2 paired comparison.

## Guardrails

Any later change to this foundation must:

1. keep plain main inadmissible unless it independently satisfies all frozen capabilities;
2. preserve `native_windows_v1` on Python 3.11 and 3.13;
3. rerun the neutral Linux and native Windows probes;
4. update the cluster ledger and exact artifact hashes;
5. carry explicit exceptions for any exceeded relative performance margin;
6. avoid credentials, private historical content, sealed holdout data, and unfiltered live traces.

## Reversibility

The decision is pinned to one immutable SHA, not a moving branch. Rollback means selecting another immutable candidate and rerunning the same frozen manifest, probe, Windows matrix, disposition verifier, privacy scan, and RPD review. No replacement may silently fall back to plain main.
