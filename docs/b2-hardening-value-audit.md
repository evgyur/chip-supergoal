# B2 hardening value audit

Status: **READY FOR DISCUSSION**  
Decision: **`adopt_whole`**  
Selected foundation: **`5725192154dfca78032e861edbd29570bb2d94e8`**  
Audit boundary: `35a22fe5bc4821559d9a186579bc1ea07ad6ac33..5725192154dfca78032e861edbd29570bb2d94e8`

## Executive decision

Adopt the whole `fix/b2-hardening` foundation. Do not return to plain `main`, and do not curate a partial subset.

The dependency-aware probe reproduces a useful boundary: clean main and cumulative compositions through C3 fail; the first passing Linux composition is through C4, and whole hardening remains green. Native Windows 3.11.9 and 3.13.14 independently pass the frozen whole-hardening probe. There are zero unresolved P0/P1 findings.

This decision is based on reproduced behavior and frozen receipts, not branch-authored test volume or CI greenness.

## Frozen audit design

- Main SHA: `35a22fe5bc4821559d9a186579bc1ea07ad6ac33`
- Whole hardening SHA: `5725192154dfca78032e861edbd29570bb2d94e8`
- Accounted history: **29/29 commits**, **151/151 changed files**, each assigned exactly once
- Diff size: 31,596 insertions, 2,651 deletions, net +28,945 lines
- Neutral probe: `evals/b2/b2-neutral-harness/probe.py`
- Probe SHA-256: `aad97c5401bf4b271d830c75395f63e2ee8b954667e085b8ed01fc9a66f0d0d5`
- Linux measurement: one warm-up plus five measured repetitions
- Native Windows matrix: Python 3.11.9 and 3.13.14
- Semantic false-green set: five frozen, hash-checked fixtures

The neutral probe is checked out from the audit branch while each target is checked out separately at its frozen SHA. Target-owned test count is not used as evidence.

## Composition results

| Composition | Included clusters | Linux result | Interpretation |
|---|---|---:|---|
| main | none | fail | Not self-contained; strict package and archive guarantees are absent. |
| through-C1 | C1 | fail | Portable contract pipeline alone is insufficient. |
| through-C2 | C1–C2 | fail | Runtime authority without the remaining platform/delivery closure is insufficient. |
| through-C3 | C1–C3 | fail | Native Windows authority alone does not close archive/delivery behavior. |
| through-C4 | C1–C4 | pass | First cumulative composition that closes the neutral Linux probe. |
| hardening-whole | C1–C5 | pass | Passes Linux and both required native Windows probes. |

## Cluster dispositions

| Cluster | Disposition | Reason |
|---|---|---|
| C1 — portable-contract-pipeline | `retain_valuable` | Establishes canonical contracts, profiles, diagnostics, and portable I/O prerequisites. |
| C2 — sealed-runtime-authority | `retain_required` | Makes packages self-contained and preserves runtime state, evidence, terminal authority, and recovery. |
| C3 — native-windows-authority | `retain_required` | Owns Windows path identity, locking, and runtime authority. |
| C4 — archive-delivery-hardening | `retain_valuable` | Closes freshness, atomic publication, and malformed-target preservation; this is the first passing cumulative boundary. |
| C5 — native-release-closure | `retain_required` | Preserves Windows path-race defenses, Linux parity, CI evidence, and compatibility closure. |

The complete commit-to-cluster ledger is `evals/b2/b2-disposition-manifest.json`.

## Native Windows evidence

The whole-hardening target passed both frozen native probes and all declared `native_windows_v1` capabilities:

- Python 3.11.9 receipt: `evals/b2/results/windows/hardening-whole-py3119.json` — SHA-256 `3dece1aacf15299d67f7e3c4908584e172f15f3cffe1ccbb34d8fbb8fdcca8e8`
- Python 3.13.14 receipt: `evals/b2/results/windows/hardening-whole-py31314.json` — SHA-256 `870832df9854b2a7ee6b6d1b4160fb7780ec602a8e9be3b8a9fd4576d8bfd058`

The clean-main receipts fail on both versions as expected:

- `main-py3119.json` — SHA-256 `919ea0426a0b5e1b5aea32579401a35b25253bb03ad76e37abf5845fb362867f`
- `main-py31314.json` — SHA-256 `7263ae1a3e8a4d3598496e3d0f864a91e1593dc2c22826ab0bf8c0e3551d621a`

Preserved capabilities: PowerShell-safe CLI, long/short paths, mixed separators, drive roots, `subst`, junction/symlink/reparse containment, atomic replacement, package locking, path-swap races, deterministic compile/archive, and public v2/v3 Linux parity.

## Performance and complexity

The preregistered relative margins are exceeded, so this audit does **not** call the candidate non-inferior. It records explicit written exceptions based on bounded absolute cost:

| Metric | Relative result | Candidate absolute | Decision |
|---|---:|---:|---|
| compile p50 | +288.654% | 0.2584 s | exception accepted |
| compile p95 | +244.732% | 0.2643 s | exception accepted |
| archive p50 | no main baseline | 0.4277 s | exception accepted |
| archive p95 | no main baseline | 0.4345 s | exception accepted |
| package size | +2350.374% | 743,321 bytes | exception accepted |

The cost is the self-contained validator, schemas, runtime, recovery, and deterministic archive implementation. The branch is materially larger, but the absolute package remains below 1 MiB and compile/archive p95 remains below 0.5 seconds on the Linux measurement host.

## Semantic false-green result

Five independently frozen semantic fixtures cover compound binding, source locators, command order, approval scope, and runtime authority. All five hashes and expected defects are confirmed in `evals/b2/results/false-green-review.json`.

Verdict: **no measured plan-quality improvement**. This is deliberately not upgraded to an equivalence claim: the audit has no powered 2×2 McNemar sample of independently generated plans. Infrastructure correctness improved; direct plan-quality effect remains unproven.

## RPD review

The required integration/data-loss review is recorded in `evals/b2/results/rpd-review.json`.

- Integration: pass — the cumulative dependency boundary is reproduced.
- Data loss/recovery: pass — sealed runtime authority and deterministic archive/recovery are retained.
- Privacy: pass — changed-only scan reports zero violations.
- Unresolved P0/P1: **0**.

## Evidence index

- Comparison report: `evals/baselines/b2-branch-comparison.json`
- Cluster ledger: `evals/b2/b2-disposition-manifest.json`
- Neutral harness: `evals/b2/b2-neutral-harness/`
- Linux receipts: `evals/b2/results/linux/`
- Native Windows receipts: `evals/b2/results/windows/`
- False-green review: `evals/b2/results/false-green-review.json`
- RPD review: `evals/b2/results/rpd-review.json`
- GitHub Actions receipt run: `29292944327`; whole-hardening native jobs `86960346812` and `86960346792` passed.

## Final verdict

**`adopt_whole`** at `5725192154dfca78032e861edbd29570bb2d94e8`.

The decision is deterministic and reversible: the selected SHA and every cluster/commit disposition are frozen. A future replacement must reproduce the same neutral Linux and native Windows capability receipts, retain `native_windows_v1`, and either satisfy the original relative margins or carry equally explicit bounded-cost exceptions.
