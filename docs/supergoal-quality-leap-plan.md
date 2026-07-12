# SuperGoal Quality Leap Plan

**Status:** review-ready plan only; awaiting discussion and explicit approval.

**Execution:** not started in this chat; no runtime, planner, schema, or default behavior has been changed by this document.

**Recommended execution route after approval:** Project Flow, with Shaw per implementation slice.

**Plan branch:** `plan/quality-leap`

**Current planning base:** `fix/b2-hardening` at `5725192154dfca78032e861edbd29570bb2d94e8`.

**Implementation baseline:** intentionally undecided until mandatory Gates B2-00/B2-01 choose and materialize the whole branch, a curated subset, or a clean base with an independently implemented Windows capability floor.

**Non-negotiable foundation capability:** every selectable baseline must provide `native_windows_v1`; a plain `main` checkout is not an admissible quality-work foundation.

**Plan revision:** `0.6`
**Date:** 2026-07-12

## 1. Executive decision

SuperGoal should stop treating a structurally valid, well-evidenced package as proof that the underlying plan is good.

Before quality-engine work starts, Gate B2-00 must independently assess `fix/b2-hardening`. Its Windows, runtime-authority, archive, delivery, and evidence changes may be a valuable foundation, but their size and green CI do not prove that they improve planning quality or that every added layer should become permanent.

The recommended direction is an **eval-driven planning system** with three separable layers:

1. a deterministic quality contract and linter that rejects objectively incomplete plans;
2. a risk-gated, bounded B+C `draft -> critic -> targeted repair -> optional judge` loop for semantic weaknesses, while B-only makes no semantic-review calls;
3. a blind benchmark and live-canary promotion policy that decides whether the new planner is actually better than the current one.

The current compiler, state machine, evidence model, runtime audit, native Windows support, and GoalManager compatibility remain the foundation. This plan changes the quality authority above that foundation; it does not replace the executor.

The new system is not allowed to become the default because it sounds more senior, produces longer Markdown, or passes its own new tests. It becomes the default only if it beats the frozen baseline on unseen tasks and reduces real execution rework without an unacceptable cost increase.

The “frozen baseline” in that sentence is the exact foundation commit materialized by Gate B2-01 from the B2-00 decision, not automatically the tip of `fix/b2-hardening`.

## 2. The problem, grounded in the current repository

### 2.1 What is already strong

The repository has unusually strong execution integrity:

- typed phase criteria and verifier records exist in `lib/chip_supergoal/model.py:60-94`;
- phase identifiers, dependencies, command references, and ordinals are checked in `lib/chip_supergoal/normalize.py:15-76` and `lib/chip_supergoal/graph.py:6-37`;
- runtime completion requires fresh passing evidence in `lib/chip_supergoal/audit.py:534-632`;
- loop, phase, terminal, delivery, archive, and platform invariants have broad automated coverage;
- the final baseline passes on native Windows and Linux.

These mechanisms answer: **“Did the executor follow the declared contract and prove it?”**

### 2.2 What is missing

They do not adequately answer: **“Was the declared contract the right plan?”**

Direct evidence:

1. `spec/contract.schema.json:4-50` constrains most planning fields only as generic objects or arrays. It does not define a first-class intent model, assumption ledger, alternative comparison, traceability map, quality score, or promotion policy.
2. `_ALLOWED_TOP_LEVEL` in `lib/chip_supergoal/model.py:8-12` has no quality/evaluation contract. `architecture`, `loop`, `decisions`, and `compatibility` remain mostly free-form dictionaries.
3. `semantic_errors()` in `lib/chip_supergoal/normalize.py:70-76` checks phase ordering, stable IDs, dependency graphs, and optional risk policy. It does not test requirement coverage, decision quality, critical assumptions, missing implementation seams, or over-planning.
4. `validate_loop_design()` in `lib/chip_supergoal/validate.py:90-118` correctly rejects missing sections and obvious placeholders, but its instantiated checks are word counts and keyword patterns. A plausible paragraph can satisfy them without being strategically correct.
5. The audit in `lib/chip_supergoal/audit.py:610-632` proves evidence for the criteria the plan declared. If the planner omitted the important criterion, the audit cannot discover that omission.
6. `docs/chip-supergoal-user-stories.csv` proves the presence of 55 capabilities. It does not compare plan quality against a baseline on unseen real tasks.
7. A fresh probe on this baseline showed that `examples/brownfield-feature/CONTRACT.json` passes both strict contract validation and strict compiled-package validation even though its planning content is intentionally minimal: empty decisions, an empty source-of-truth list, and a loop containing only `max_iterations`. That fixture is valid for compiler tests; it also demonstrates that current green status is not a semantic-quality claim.
8. The current `--strict` CLI surface does not compose instantiated loop validation, every rendered phase validator, cross-file consistency, and quality policy into one readiness gate (`scripts/sgctl.py:443-446,592-606`; package validation is separate in `lib/chip_supergoal/validate.py:1146-1196`). A caller can therefore overread “strict” as a semantic readiness verdict.
9. Risk and research coverage are mostly self-declared. The policy is strong after a risk tag exists, but it does not prove that the planner noticed an undeclared production/auth/data-loss action; similarly, a shaped research record is not proof that its source materially supports a decision.

Probe used:

```powershell
python scripts\sgctl.py validate-contract examples\brownfield-feature\CONTRACT.json --strict --format json
python scripts\sgctl.py compile examples\brownfield-feature\CONTRACT.json --out <temp-dir>
python scripts\sgctl.py validate-package <temp-dir> --strict --format json
```

Observed result: both validators returned `[]` diagnostics.

### 2.3 Root cause

The current repository is optimized for **contract integrity after a plan exists**. It lacks a product-quality feedback loop for **selecting and improving the plan itself**.

This is not mainly a prompt-writing problem. It is an authority problem: no independent artifact currently has the right to say that one SuperGoal plan is measurably better than another.

### 2.4 Mandatory Gate B2-00 — determine the value of `fix/b2-hardening`

This gate precedes every quality-engine phase.

Current branch facts, fetched on 2026-07-12:

- `origin/main`: `35a22fe5bc4821559d9a186579bc1ea07ad6ac33`;
- `origin/fix/b2-hardening`: `5725192154dfca78032e861edbd29570bb2d94e8`;
- merge base: the current `origin/main` commit above;
- branch delta: 29 commits, 151 files, approximately 31,596 added and 2,651 deleted lines.

The branch includes at least five logically different change clusters:

1. canonical contract/profile/pipeline/diagnostic behavior;
2. runtime state, evidence, audit, event, and terminal authority;
3. native Windows and portable file/locking/path handling;
4. archive, delivery, publication, recovery, and security hardening;
5. CI, release evidence, documentation, migration, and broad regression coverage.

Preliminary evidence says the branch is likely valuable for execution reliability, native Windows operation, security, and reproducibility. It does **not** yet prove either of these stronger claims:

- that it improves the semantic quality of plans;
- that all 29 commits and every new runtime layer are worth their permanent maintenance cost.

Gate hypotheses:

- **H1:** the branch materially reduces real runtime/security/cross-platform failures;
- **H2:** its direct effect on plan reasoning quality is small or zero;
- **H3:** different clusters have different benefit/cost ratios, so whole-branch adoption may be worse than curated adoption.

#### Neutral comparison method

Do not compare test counts from the two branches as if they were equivalent; the hardening branch contains many tests that `main` does not have. Build an external, versioned black-box acceptance harness whose assertions are not owned by either implementation, then run it against clean worktrees for both SHAs on Windows and Linux.

Endpoint comparison alone cannot justify per-cluster retention. Before measurement, derive a dependency DAG for the five change clusters and materialize clean incremental/ablation worktrees: `main + cluster + required dependencies`. Run the neutral harness for each eligible composition, then rerun the final selected curated composition as a whole. A cluster receives credit only for a delta attributable under that dependency-aware design.

The harness must cover:

- compile/validate/finalize behavior and malformed-input failure;
- state/evidence/terminal authority and false-completion resistance;
- recovery after interrupted publication;
- archive/delivery determinism, freshness, and forged/mismatched receipts;
- Windows long/short paths, SUBST, junction/symlink/reparse behavior, locking, and path-swap races;
- legacy v2/v3 compatibility and default-profile behavior;
- compile/archive time, peak memory where practical, package size, and runtime module count;
- five semantic false-green plan cases created, independently reviewed, and frozen inside B2-00 before branch comparison, to measure whether B2 changed plan fitness at all. Later Phase 0 only replays/pins them against the selected foundation.

Before any timing/size result is opened, the B2 audit protocol freezes repetitions, warmup handling, hardware/runtime identity, and metric-specific non-inferiority margins. Initial defaults are at least five measured repetitions, compile/archive p50 regression no worse than 10%, p95 no worse than 20%, and package-size growth no worse than 25% unless the ADR explicitly ties the excess to retained user/security value.

H2 plan-quality neutrality is descriptive unless a task-level paired equivalence test is powered and preregistered. The default equivalence margin is the same `±6.25/100` MCID used by the quality benchmark; use a paired TOST/equivalent interval over independent tasks. If power is insufficient, report “no measured plan-quality improvement” rather than “equivalent.”

For each logical cluster, record:

| Dimension | Required evidence |
|---|---|
| User-visible benefit | Reproduced failure on `main` that passes on hardening, or an explicit capability unavailable on `main` |
| Security/data-loss value | Adversarial negative fixture with expected fail-closed result |
| Native Windows value | Exact Windows 3.11/3.13 commands and path/race fixtures |
| Linux/compatibility cost | Same neutral harness on Linux plus existing public interfaces |
| Performance cost | Paired compile/archive/runtime measurements with fixed fixtures |
| Complexity cost | Added modules/LOC/public surfaces, dependency edges, duplicate authorities, and maintenance owner |
| Evidence quality | Independent test/review, not only a branch-authored user-story string assertion |
| Plan-quality effect | Blind semantic false-green/plan benchmark delta, reported separately from runtime reliability |

Every new module/layer must map to a reproduced failure class and a regression test. “More robust” without that mapping is not a retention argument.

#### Cluster verdicts and branch decision

Classify each cluster and major commit group as one of:

- `retain_required` — protects a reproduced P0/P1 or required Windows/public contract;
- `retain_valuable` — measurable benefit with acceptable complexity;
- `rework_or_split` — useful outcome, but current implementation is too coupled or expensive;
- `defer` — plausible but unproved value;
- `drop` — no measurable benefit, duplicate authority, or net regression.

Then choose exactly one branch-level decision:

1. `adopt_whole` — only if all material clusters pass benefit, compatibility, and complexity gates;
2. `adopt_curated` — create a clean foundation branch containing only retained clusters, with provenance and tests;
3. `keep_separate` — B2 remains a runtime-hardening line while quality work uses `main + native_windows_v1`, not plain `main`;
4. `reject` — reject the B2 implementation as a whole, preserve its audit evidence/lessons, and materialize an independently verified minimal `native_windows_v1` slice on the selected base.

`native_windows_v1` is a hard capability floor, not a favorable score that other benefits may average away. Its versioned capability manifest must cover native CPython 3.11 and 3.13 on Windows, PowerShell-safe CLI invocation, long/short paths, mixed separators, drive roots, SUBST, junction/symlink/reparse containment, atomic file replacement, process/package locking, path-swap races, deterministic compile/archive, and the same public v2/v3 behavior exercised on Linux. Every retained implementation file maps to those black-box cases; the capability may come from B2 or a smaller equivalent slice.

A `keep_separate`, `reject`, or main-based decision can close only when B2-01 has built that equivalent slice and the neutral Windows suite is green. If no admissible slice can be materialized, B2-01 is blocked; QL-00 must not start and native Windows is never silently demoted to a later quality feature.

This planning document currently lives on a branch derived from `fix/b2-hardening` for review convenience. That ancestry is not adoption evidence. After the verdict, cherry-pick or rebase the reviewed plan onto the exact selected foundation before creating Project Flow state.

Required artifacts:

- `docs/b2-hardening-value-audit.md`;
- `docs/adr/ADR-003-b2-adoption.md`;
- `evals/baselines/b2-branch-comparison.json`;
- `evals/baselines/b2-neutral-harness/`;
- five frozen B2 semantic false-green fixtures with independent review receipts;
- a dependency/ablation manifest for every evaluated cluster composition;
- a commit/cluster disposition manifest with evidence links;
- exact selected foundation SHA and rollback/rebase instructions.
- `evals/baselines/foundation-capabilities.json` with the `native_windows_v1` implementation/evidence hashes and Windows 3.11/3.13 environment receipts.

After the adoption verdict, mandatory Gate B2-01 materializes the selected foundation: verify the unchanged whole branch, create/test a curated foundation, or create `main + native_windows_v1`; then move this reviewed plan onto that exact SHA and rerun the neutral harness. Plain `main` is not selectable. No Phase 0 quality baseline may be frozen and no quality implementation may begin until B2-00 and B2-01 have evidence-backed verdicts, a green capability manifest, and unresolved P0/P1 equal to zero.

## 3. Definition of a quality leap

A quality leap means the candidate planner measurably improves all of the following without hiding regressions behind verbosity:

1. **Intent fidelity** — solves the actual class of problem, not the latest example or a nearby interpretation.
2. **Evidence grounding** — separates observed facts, provided context, inference, and unverified assumptions.
3. **Decision quality** — considers credible alternatives, selects one for explicit reasons, and avoids architecture by reflex.
4. **Traceability** — every mandatory requirement reaches a decision, phase, acceptance criterion, verifier, and expected evidence path.
5. **Executability** — commands, working directories, dependencies, state transitions, and deliverables can exist in the order declared.
6. **Risk control** — likely failure paths, permissions, rollback, and stop conditions are part of the plan rather than post-hoc review prose.
7. **Simplicity** — no extra phase, agent, abstraction, compatibility layer, or approval exists without necessity and a removal condition.
8. **Adaptability** — the plan names what new evidence would cause it to change and can revise without losing canonical state.

The quality target is **risk-tiered**:

- normal non-trivial work: Senior-quality plan;
- architecture, migration, production, money, privacy, auth, routing, or recurring failures: Principal/Architect+ plan;
- tiny direct work remains outside SuperGoal.

## 4. Options considered

| Option | Description | Strength | Fatal weakness | Decision |
|---|---|---|---|---|
| A. More prompts and rules | Expand `SKILL.md`, references, and persona instructions | Cheap and immediately visible | Cannot prove improvement; encourages checklist compliance and prose bloat | Reject as primary strategy |
| B. Deterministic plan compiler only | Add schemas, traceability, semantic lint, and fail-closed checks | Excellent at objective omissions and false-green contracts | Cannot reliably judge whether an architecture or prioritization choice is strategically good | Keep as mandatory lower layer |
| C. Eval-driven planner with critic/repair | Compare frozen baseline and candidate on real tasks; add bounded semantic review and repair | Can measure end-to-end plan quality and discover failures the authors did not predict | More cost, judge bias, and harness complexity | Select, with B underneath and strict budgets |

### Existing-solutions decision

Reuse mode: **`copy_pattern`**, not `buy`, `fork`, or a vendor-bound wrapper.

Patterns to reuse:

- PlanBench: diverse task classes and a benchmark designed to distinguish planning from retrieval;
- SWE-bench/SWE-bench Verified: real tasks, hidden execution checks, and human validation that tasks and graders are fair;
- MT-Bench/LLM-as-a-judge research: blind pairwise comparison plus explicit controls for position, verbosity, and self-preference bias;
- OpenAI/Anthropic eval guidance: task-specific datasets, explicit graders, multidimensional success criteria, edge cases, and automation where possible;
- AgentBench/GAIA: diverse environments and held-out evaluation rather than one polished demo class.

What remains build-fresh is deliberately small: a SuperGoal-specific quality schema, deterministic lint, benchmark adapter, comparison report, and canary gate around the existing `sgctl` compiler.

### 4.1 Overengineering budget

Allowed:

- one pure deterministic runtime quality module (`quality.py`, with traceability kept inside unless profiling proves a split necessary) and one versioned policy/schema family;
- one developer-only `evals/` harness with recorded/manual/command adapters;
- one structured quality report linked to the acyclic plan-subject hash and sealed with the final contract by the existing package manifest;
- at most two semantic critic/repair rounds;
- prompt/reference growth no greater than 10%, preferably net-neutral by deleting duplicated prose.

Forbidden unless a later benchmark proves necessity:

- a new daemon, database, service, agent council, or permanent orchestration state machine;
- provider/model SDKs inside the self-contained package runtime;
- a separate `/looper` or second compiler;
- judge edits to generated Markdown or implementation files;
- unlimited repair, majority-vote theater, or post-hoc rubric changes.

## 5. Target architecture

```text
USER INTENT + REPO/CONTEXT EVIDENCE
                 |
                 v
        [1] HOST INTENT NORMALIZATION
        requirements / constraints / non-goals
        facts / assumptions / unknowns / falsifiers
                 |
                 v
        [2] DECISION PASS
        2-3 credible approaches -> selected architecture
                 |
                 v
        [3] DRAFT CONTRACT + ROADMAP
                 |
                 v
        [4] DETERMINISTIC QUALITY LINT
        traceability / executability / risk / scope / simplicity
           | red                    | green
           v                        v
       targeted repair       [5] LANE POLICY
                        b_only | b_plus_c
                           |       |
                           |       v
                           |  INDEPENDENT CRITIC
                           |  findings -> bounded repair -> re-lint
                           |       |
                           |       v
                           |  semantic judge when policy requires
                           |       |
                           +-------+
                                   v
                              QUALITY GREEN
                                   |
                                   v
                           STAGE-6 HUMAN REVIEW
                                   |
                                   v
                      EXISTING COMPILE / PACKAGE / EXECUTOR
                                   |
                                   v
                         OUTCOME RECEIPT / FEEDBACK
```

### 5.1 Module boundaries

#### Host intent normalization pass

Interface: frozen `IntentContract`.

Responsibilities:

- assign stable IDs to must/should constraints and non-goals;
- bind each fact to a source locator and freshness;
- classify assumptions as accepted, must-verify, or blocker;
- store a falsifier for every critical assumption;
- preserve the difference between the mission and an illustrative example.

It does not produce implementation phases and is not a second artifact authority. Canonical `CONTRACT.json` remains the only planning source of truth.

#### Quality linter

Interface: `QualityFinding[]` with stable codes, severity, artifact pointer, evidence, and remediation.

Responsibilities:

- validate declared traceability and completeness;
- reject orphan requirements, phases, criteria, commands, and evidence expectations;
- check working-directory and command existence where deterministically knowable;
- enforce risk, rollback, permission, source-of-truth, and overengineering contracts;
- detect false-green packages that are structurally complete but semantically underdeclared.

It does not choose an architecture.

#### Deterministic semantic-review lane policy

`spec/plan-quality-policy.json` is the frozen routing authority. The planner may declare a lane for transparency, but validators recompute it from normalized risk tier, action classes, and execution profile; a declared/recomputed mismatch is a launch-blocking hard failure.

The initial policy is deliberately small:

- `b_plus_c` is mandatory for `high`/`critical` risk, any production/auth/privacy/payment/destructive action class, and every offline promotion run;
- `b_only` is allowed only for low/normal-risk work outside the offline promotion profile when none of those action classes is present;
- a separate semantic judge is mandatory for high/critical-risk work, every offline promotion run, or any critic P0/P1 still unresolved after the final allowed repair;
- an unresolved deterministic or critic P0/P1 remains blocking even when a judge is required; a judge cannot waive it;
- policy version, normalized inputs, recomputed lane, lane reason, judge requirement, and judge reason are sealed in the report/attestation.

Tests must forge a high-risk contract declaring `b_only`, omit risky action tags while retaining risky commands, and alter the policy version after compilation; all three must fail closed with stable diagnostics.

#### Critic

Interface: bounded findings, not chain-of-thought.

Responsibilities:

- attack the selected plan using the frozen intent and evidence set;
- identify wrong-goal, hidden-assumption, failure-path, and integration defects;
- provide a specific mutation or `checked-holds` record for every finding;
- never mutate the worktree directly.

#### Judge

Interface: rubric scores, hard-failure flags, evidence pointers, and verdict.

Responsibilities:

- decide `ready`, `repair`, or `blocked`;
- never be the same response that authored the plan;
- not expose private reasoning;
- not override deterministic hard failures.

In offline evaluation, at least two blinded judges and human calibration are required. In normal planning, deterministic gates remain authority. The policy-recomputed `semantic_review_lane` is the sole routing authority: `b_only` permits no critic or judge call; `b_plus_c` requires the critic and records whether a separate semantic judge is required. Record lane reason, `semantic_judge_required`, its reason, status, and token/tool cost.

Neither deterministic quality green nor a semantic judge can authorize dispatch. They may block or request repair; the existing Stage-6 human go/no-go remains mandatory.

#### Benchmark runner

Interface: immutable paired `EvalRun` artifacts.

Responsibilities:

- give baseline and candidate identical task/context/tool budgets;
- import plans from recorded files, another bot, or an external planner command;
- anonymize identity and randomize A/B order;
- execute deterministic graders;
- collect independent pairwise and rubric judgments;
- execute a fixed subset of both plans through the same sandboxed executor against hidden acceptance tests and a safety monitor;
- calculate confidence intervals, stratum regressions, cost, and promotion verdict.

The public core must not require a particular model vendor or API key.

The semantic critic/judge belongs to the host planner and offline evaluation plane. It must not add a provider SDK, daemon, or alternate runner to the self-contained execution package.

#### Outcome collector

Interface: privacy-safe `OutcomeReceipt` linked to the immutable plan hash.

Responsibilities:

- count post-launch plan amendments, unplanned work, missing-dependency blockers, failed criteria, user corrections, and rework rounds;
- capture tokens, elapsed time, and time-to-first-verifiable increment when available;
- store only redacted aggregates in the public repository.

### 5.2 Quality state machine

```text
UNASSESSED
  -> FACTS_LOCKED
  -> DRAFTED
  -> LINT_RED -> REPAIRED -> LINT_GREEN
  -> semantic_review_lane
      -> b_only -> B_ONLY_CONFIRMED (zero semantic calls/tokens)
      -> b_plus_c -> CRITIQUED -> REPAIRED -> LINT_GREEN
          -> JUDGED_C (when semantic_judge_required)
          -> JUDGE_NOT_REQUIRED (with policy reason)
  -> QUALITY_GREEN
  -> AWAITING_STAGE6_REVIEW
      -> READY_TO_DISPATCH (only after current human-origin receipt + composite preflight)
      -> BLOCKED_QUALITY
      -> BASELINE_FALLBACK (canary only; never disguised as candidate success)
```

No-progress rule: if the same P0/P1 survives two repair rounds, stop. Do not keep spending tokens or soften the rubric.

### 5.3 Incubation without schema split-brain

The quality contract should not immediately force a permanent v3 schema migration.

Canary design:

- store the first version under `compatibility.quality_gate_v1`;
- validate it against a dedicated sealed schema;
- require it only for a new `quality-canary` profile;
- emit `reports/plan-quality.json` and `reports/plan-quality.md` as sealed pre-dispatch evidence;
- keep `protocol_version: 3.0` and the existing executor unchanged.

Removal/promotion condition:

- if the candidate meets promotion thresholds, write an ADR that either promotes the block to a first-class contract field in schema v3.1 or documents why the canary location remains correct;
- if it does not meet thresholds after two improvement cycles, remove the planner loop and keep only benchmark assets or deterministic checks that independently proved value.

This incubation is a temporary compatibility seam, not a second source of truth.

### 5.4 Authority and acyclic hash DAG

| Artifact | Authority | Hash input | May reference |
|---|---|---|---|
| Source bundle | Evidence authority | Exact planner-visible source bytes/locators | Nothing downstream |
| Intent payload | Normalized input record | Source hashes + normalized requirements/assumptions | Source bundle hashes |
| Plan-subject projection | Sole planning source of truth before attestation | Canonical **whole** `CONTRACT.json` with exactly `.compatibility.quality_gate_v1.attestation` omitted | Source/intent hashes; includes `.quality_gate_v1.subject` |
| `reports/plan-quality.json` | Derived quality-verdict evidence | Frozen policy/rubric, review results/findings/scores/cost, and plan-subject hash | Plan-subject hash; never final contract hash |
| Final `CONTRACT.json` | Sole final planning source of truth | Canonical whole contract including `.quality_gate_v1.subject` and the bounded `.attestation` | Plan-subject hash and quality-report locator/hash |
| Existing package manifest | Package sealing authority | Final `CONTRACT.json`, quality report, review views, and every generated immutable artifact | Exact hashes of all sealed artifacts |
| Markdown views | Derived only | Deterministically rendered from final contract/report | No independent authority |
| Stage-6 approval receipt | Human dispatch authority | Package fingerprint, contract/report/review-pack hashes, approval actor/text/time/revision | Existing package manifest and human-origin approval source |

Hash order:

```text
source bundle
  -> intent payload
  -> plan subject (canonical whole contract with exactly attestation omitted)
  -> plan-quality.json
  -> attestation appended to final CONTRACT.json (never contains final-contract hash)
  -> package manifest seals final contract + report + generated views
  -> immutable human Stage-6 approval receipt
  -> pure readiness validation / guarded state transition
```

The contract must never contain its own final SHA. Canonicalization uses the repository's sealed JSON rules. Validation deep-copies the final contract, removes exactly the single `.compatibility.quality_gate_v1.attestation` member (not the parent block and no other field), recomputes the plan-subject hash, verifies the report against that projection, then relies on the existing package manifest to bind the final contract and report without a cycle. Missing, duplicate, unknown, or differently projected authority fields fail closed.

## 6. Deterministic quality contract

### 6.1 Required records

The v1 JSON shape is explicit. `compatibility.quality_gate_v1` has exactly two children:

```json
{
  "subject": {
    "intent": {},
    "requirements": [],
    "constraints": {},
    "assumptions": [],
    "options": [],
    "traceability": [],
    "failure_modes": [],
    "permissions": {},
    "overengineering": [],
    "budgets": {}
  },
  "attestation": {
    "quality_contract_version": "1.0",
    "quality_policy_version": "<frozen-version>",
    "rubric_version": "<frozen-version>",
    "status": "required|green|red",
    "semantic_review_lane": "b_only|b_plus_c",
    "semantic_review_lane_reason": "<stable-policy-code>",
    "plan_subject_sha256": "<sha256>",
    "report_path": "reports/plan-quality.json",
    "report_sha256": "<sha256>",
    "semantic_judge_required": false,
    "semantic_judge_status": "not_required|passed|failed|unavailable",
    "semantic_judge_reason": "<stable-policy-code>"
  }
}
```

`subject` is canonical planning authority for the quality-specific intent, requirements, constraints/non-goals, assumptions/falsifiers, architecture options, traceability edges, failure modes/rollback, permission/source-of-truth boundaries, overengineering ledger, and iteration/token/time budgets. The rest of `CONTRACT.json` remains authoritative for its existing planning fields. The plan-subject hash covers the canonical whole contract containing this `subject`, with exactly `attestation` omitted; it is not a hash of only the nested subject.

The sealed `reports/plan-quality.json` is derived evidence, not a second planning authority. It stores the plan-subject hash, immutable source/intent/draft/repaired hashes, deterministic and critic findings, applied mutations or checked-holds, rubric scores, hard failures, judge identities/classes/verdicts, semantic-review cost, actual budgets/cost, and report-generation policy versions. It may repeat stable subject IDs for joins, but any copied planning text is non-authoritative and must exactly match the subject projection.

Validators recompute lane and judge requirements from `spec/plan-quality-policy.json`, check that attestation status/policy/hash/locator fields exactly match the detailed report, and verify that the final package manifest seals final contract, report, and views. Markdown is rendered from those records and never becomes an independent authority.

Do not store hidden chain-of-thought. Store claims, evidence, decisions, findings, and mutations.

### 6.2 Hard lint rules

The following are launch-blocking:

1. A must requirement has no trace to a blocking criterion and verifier, and is not an explicit non-goal accepted by the user.
2. A critical assumption is presented as fact without direct/provided/current-source evidence or a scheduled falsifier.
3. An architecture-affecting plan has no credible alternative and no narrow reason why alternatives are inapplicable.
4. A phase depends on an artifact, command, state transition, commit, approval, or environment that cannot exist yet.
5. A blocking criterion proves only file/text presence when the requirement is behavioral.
6. A P0/P1 failure mode lacks mitigation, rollback/safe-stop, and a verifier.
7. A source-of-truth or permission boundary is duplicated or left ambiguous.
8. A new layer, agent, fallback, or compatibility seam lacks necessity, rejected simpler alternative, and removal condition.
9. The plan solves a recent example while the request is class-level.
10. The quality report does not bind to the recomputed plan-subject hash, or the final package manifest does not bind the exact final contract, report, rendered roadmap, and phase specs.
11. A command lacks an explicit working directory, mutation class, availability dependency, or expected output binding where those facts affect execution.
12. A source/research record has no content hash/freshness/receipt or its `used_by` links do not resolve to real decisions, phases, criteria, or risks.
13. A risky objective, deliverable, or command mutation class has no matching risk declaration or explicit evidence-backed waiver.

### 6.3 Semantic checks reserved for critic/judge

The linter must not pretend it can deterministically know:

- whether the selected architecture is the best trade-off;
- whether an apparently complete requirement map reflects the user's real intent;
- whether the plan is strategically over-scoped despite valid declarations;
- whether a risk probability or priority is reasonable;
- whether a different ordering would materially reduce rework.

Those claims require evidence-bearing semantic review and benchmark calibration.

### 6.4 Command and profile semantics

Quality status is one of `not_applicable`, `required`, `green`, or `red`.

| Surface | Input authority | Default/legacy profile | `quality-canary` profile |
|---|---|---|---|
| `sgctl quality-lint CONTRACT.json` | Contract + quality policy | Explicit opt-in report | Required deterministic B gate |
| `sgctl validate-contract --strict CONTRACT.json` | Contract only | Preserve compatible v3 behavior; quality is `not_applicable` | Deep contract plus required quality overlay; cannot claim rendered/package readiness |
| `sgctl validate-package --strict <root>` | Full compiled package | Existing package gates; quality is `not_applicable` | Composite contract, instantiated loop, all phases, source/research receipts, cross-file consistency, report binding, manifest/drift gates |
| `sgctl approval-source-probe <root>` | Canonical OS trust configuration + OpenSSH verifier | Not available before promotion | Resolves the operator-owned trust root without caller path overrides and proves the SSHSIG verification path; never invokes a signer |
| `sgctl record-stage6-approval <root> --payload <approval.json> --signature <approval.sig>` | Offline human-signed canonical approval payload + sealed review package + canonical trust configuration | Not available before promotion | The only path allowed to perform `COMPILED -> PLAN_REVIEWED`; atomically writes an immutable receipt/event after signature/hash validation |
| `sgctl ready-to-dispatch <root>` | Full compiled package + current Stage-6 receipt + preflight state | Not available before promotion | Pure, non-mutating validator: absent/stale receipt exits nonzero with `AWAITING_STAGE6_REVIEW`; valid current receipt returns `READY_TO_DISPATCH` |
| `sgctl state-transition ...` pre-run edges | Locked current state + current receipt | Existing state rules | Generic `COMPILED -> PLAN_REVIEWED` is forbidden; every `PLAN_REVIEWED -> PREFLIGHT_GREEN -> READY_TO_DISPATCH -> RUNNING` edge revalidates the receipt, and the READY edge also runs the composite readiness guard |
| `sgctl compile ...` | Contract source | Existing publication behavior | Render to a private staging directory, run the same composite package gate, then publish atomically only when green |

Phase 2 adds the opt-in quality overlay and candidate-only commands without changing legacy/default outcomes. Phase 6 wires the matrix only for `quality-canary`. Phase 8 may promote new global `--strict` semantics only through a compatibility ADR, migration notes, golden CLI/output tests, and an explicit release decision.

`validate-contract` can never validate rendered loop/phases or package drift because it has no package root. Only `validate-package --strict` and `ready-to-dispatch` are full-package readiness surfaces.

The persisted runtime graph remains exactly `COMPILED -> PLAN_REVIEWED -> PREFLIGHT_GREEN -> READY_TO_DISPATCH -> RUNNING`. `AWAITING_STAGE6_REVIEW` is only a derived diagnostic/nonzero CLI result; it is never a `runtime/STATE.json` lifecycle or journal transition. `QUALITY_GREEN` is likewise quality evidence, not runtime approval state.

### 6.5 Immutable Stage-6 approval authority

`spec/stage6-approval.schema.json` defines a write-once `runtime/stage6-approval.json`. It binds:

- approval schema/revision and contract revision;
- exact immutable package fingerprint from the existing manifest (runtime mutation is outside that fingerprint by contract);
- final `CONTRACT.json` SHA-256 and plan-subject SHA-256;
- quality-report path/SHA-256;
- ordered review-pack paths/SHA-256 values shown to the human;
- approver actor, human-origin source locator, exact approval text, and timestamp;
- `sshsig/ssh-ed25519`, namespace `chip-supergoal-stage6-v1`, signer principal/key fingerprint, trust-policy generation, and hashes of the canonical trust-config/allowed-signers/KRL snapshots used for verification;
- a preallocated approval-recording event ID; the appended event stores the receipt SHA-256, avoiding a receipt/event hash cycle.

The concrete v1 trust path is offline OpenSSH SSHSIG with an Ed25519 human key and namespace `chip-supergoal-stage6-v1`, verified by `ssh-keygen -Y verify`. This uses the standard OpenSSH client available on supported Windows/Linux hosts and adds no provider SDK to the package. The canonical signed payload includes the package challenge/fingerprint, all bound hashes, actor, exact approval text, timestamp, and revision.

Trust-root selection is not a CLI/profile/environment/library input. Every command, guard, and recovery path resolves exactly one administrator-owned configuration from the Windows Known Folder API `FOLDERID_ProgramData\chip-supergoal\stage6-trust.json` (shown conventionally as `%ProgramData%\...`, but never resolved from the process environment) or `/etc/chip-supergoal/stage6-trust.json` on Linux. That schema contains `policy_generation`, the only permitted principal/key fingerprint, algorithm, namespace, `signing_mode: offline_detached`, and canonical absolute `allowed_signers`/KRL paths. The config, parent directory, allowed-signers file, and KRL must be owned/protected by Administrators/SYSTEM on Windows or root with no group/world write on Linux. The package, profile, planner, executor, command line, current directory, environment, and direct Python caller cannot override them.

No mutating or authoritative production function for receipt recording, readiness, state transition, event recovery, or validation accepts a resolver, trust path/object, verifier, or test-mode flag. Each calls the sealed internal OS-canonical resolver itself. Only pure side-effect-free byte parsing/path-validation helpers may accept explicit bytes for unit testing. Any fixture/injection adapter lives under `tests/support/`, is absent from `RUNTIME_MODULES`, package inventories/import graphs, and sealed archives, and cannot call an authoritative write/guard function.

The v1 verifier never implements or invokes signing and rejects agent/socket/online-oracle modes. The matching private key must be absent from the execution host and the detached signature must be produced on an offline human-controlled signer, then supplied as inert input. A deployment that cannot establish that boundary is not canary-capable. Verification invokes only the OS-owned OpenSSH binary resolved from Windows System32's OpenSSH directory or `/usr/bin/ssh-keygen`, after ownership/reparse/version checks; `PATH`, aliases, current-directory binaries, and command wrappers are forbidden. Subprocess launch uses an absolute executable, `shell=False`, no search path, and a minimal allowlisted environment that removes agent, Python, shell, OpenSSH override, and dynamic-loader variables. `approval-source-probe` checks `ssh-keygen -Y` support, namespace verification, canonical binary/config path and owner/ACL invariants, exact principal/key fingerprint, offline-mode policy, absence of an allowed signing oracle, sanitized invocation, and KRL behavior on native Windows and Linux before a canary review is shown.

Every recording/readiness/transition/recovery guard reopens the canonical config and trust files without following links, rechecks ownership/ACLs, applies the current KRL, and requires byte-identical config/allowed-signers/KRL hashes to those bound in the receipt. The frozen v1 rotation rule is intentionally strict: any trust-policy, key-list, or KRL byte change makes every existing receipt stale and requires a fresh review/signature; a post-approval revocation therefore blocks the next pre-run edge immediately.

Phase 6 includes real ephemeral-key sign/verify/revoke E2E tests on both platforms. If OpenSSH, protected canonical configuration, an enrolled offline signer, or a usable KRL is unavailable, the canary fails closed at `AWAITING_STAGE6_REVIEW`; attacker-supplied trust files, raw JSON, an unsigned chat quote, a model-authored go-ahead, or `QUALITY_GREEN` can never substitute. Legacy/default Stage-6 behavior is unchanged until an explicit Phase-8 compatibility decision.

The command validates the signature/payload, takes the package lock, rechecks all bound bytes, writes the receipt once, and alone appends the `COMPILED -> PLAN_REVIEWED` transition. Generic state-transition code must reject that edge. Every later pre-run transition revalidates the same current receipt. Recompile, contract/report/view drift, review-pack reordering, package-fingerprint change, signer revocation, approval overwrite, or revision mismatch makes the receipt stale/invalid. `ready-to-dispatch` never creates or updates it.

`spec/event.schema.json` adds `stage6_approval_receipt_sha256`. It is conditionally required on the `COMPILED -> PLAN_REVIEWED`, `PLAN_REVIEWED -> PREFLIGHT_GREEN`, `PREFLIGHT_GREEN -> READY_TO_DISPATCH`, and `READY_TO_DISPATCH -> RUNNING` events and must equal the current receipt hash. The preallocated event ID in the receipt plus receipt hash in the event keeps the DAG acyclic. A small transaction journal makes crash recovery complete the matching event only when state is still `COMPILED` and every signature/hash check remains current; otherwise it quarantines the partial receipt and stays unreviewed.

Tests cover absent, unsigned, bad-signature, revoked-signer, unconfirmed signing oracle/agent access, caller-supplied trust files/objects/resolvers through CLI and direct imports, trust-root swap between probe/record/readiness, hostile loader/wrapper environment, post-receipt KRL change, bad owner/ACL, symlink/reparse trust path, malformed, model-authored, overwritten, stale-contract, stale-report, stale-review-pack, wrong-package, wrong-actor/source, reordered-view, direct generic-transition bypass, receipt/event substitution or deletion, crash recovery, and valid-current receipts. A signature/introspection negative test proves authoritative APIs expose no custom-resolver parameter; runtime-inventory/import-graph tests prove test injection code is absent. Portable atomic-write/locking, evidence/event-chain validation, recovery, archive boundaries, and the state/event schemas/machine must all recognize the same receipt authority. A valid receipt plus current composite preflight is necessary; neither is sufficient alone.

## 7. Benchmark design

### 7.1 Corpus v0

Build 84 cases, fourteen in each stratum:

1. brownfield feature and integration;
2. recurring bug/root-cause repair;
3. architecture, migration, and refactor;
4. production/auth/payments/privacy/routing safety;
5. cross-platform, packaging, and release work;
6. skill, agent, and workflow governance.

Composition:

- 42 anonymized real historical tasks with actual post-run lessons;
- 24 public-repository tasks pinned to immutable repository snapshots;
- 18 adversarial cases: wrong quoted context, example-vs-class scope, missing dependency, impossible command order, attractive overengineering, hidden rollback requirement, or deceptive green test.

Split:

- 24 development cases visible to contributors;
- 12 calibration cases with expert scorecards;
- 48 sealed promotion cases controlled outside the public repository, with only IDs and content hashes committed.

Each case must include:

- task and context bundle;
- repository/source snapshot hashes;
- must/should/non-goal truth set;
- known ambiguities and acceptable assumptions;
- expected decision seams, risks, and forbidden actions;
- a scripted clarification oracle when one material question is legitimately required;
- deterministic checks and human rubric anchors;
- planner/tool/token/time budget;
- privacy classification;
- case difficulty and stratum.

### 7.2 Fairness gate for cases

Borrow the lesson of SWE-bench Verified: a bad task or grader can make a good planner look bad.

Before a case enters calibration or holdout:

- two reviewers must agree that the request is sufficiently specified or explicitly score clarification behavior;
- deterministic checks must accept at least two valid implementation strategies where the task permits them;
- no hidden expectation may depend on unavailable private context;
- repository setup and declared commands must be reproducible;
- the case must include a documented reason it distinguishes good and weak planning.

### 7.3 Metamorphic and anti-gaming variants

For at least 20 cases, generate meaning-preserving variants:

- rename entities and files;
- reorder non-authoritative context;
- add irrelevant but plausible distractors;
- swap the latest example while preserving the class-level objective;
- express the same constraint in direct and indirect language.

Every metamorphic case declares an acceptable decision-equivalence set before evaluation. A candidate that memorizes fixture phrasing and leaves that set under a meaning-preserving variant fails robustness.

Additional anti-gaming controls:

- no score is awarded for the number of phases, headings, risks, markers, references, or words;
- seeded controls include a long rule-stuffed but factually wrong plan, a concise plan missing rollback, and a plausible hallucinated command;
- after scoring, each semantic judge guesses which condition produced each plan; condition-guess balanced accuracy above 60%, or Fisher's exact `p < 0.05` between the guess and pairwise preference, invalidates that judge run and triggers re-normalization/review;
- sealed tasks are never copied into planner references; once disclosed, they become public regression cases and are replaced before the next promotion run.

### 7.4 Paired run protocol

- Freeze baseline commit, candidate commit, model/version, tool access, context budget, temperature/seed where available, and system instructions.
- Generate baseline and candidate plans independently from the same case bundle.
- Remove version names, timestamps, and author-identifying metadata.
- Normalize presentation enough that a judge cannot choose the longer or prettier document by default; preserve substantive content.
- Randomize A/B order for each judge and repeat a position-swapped subset.
- For the full promotion run, generate two baseline and two candidate plans for every one of the 48 sealed cases: 192 plans. Treat the case, not an individual seed, as the statistical unit.
- Execute both conditions for two seeds on a predeclared sealed subset through the same sandboxed executor. The subset is at least 24 tasks and expands up to all 48 when the preregistered execution-power calculation requires it. The executor does not see hidden tests, safety traps, or condition identity.
- Run 15 hard cases three times when a third repeat is needed to investigate instability; do not count repeats as extra independent tasks.
- Save immutable inputs, outputs, grader versions, costs, and hashes.

#### Versioned sandbox-backend contract

`spec/sandbox-backend.schema.json` defines capability truth for every execution result: backend/version, host OS, pinned image/disk hash, read-only input mount, output-only channel, network denial, environment allowlist, process-tree isolation, CPU/memory/time limits, sibling-run denial, reset proof, and backend attestation hash. A backend may claim a capability only after its real adversarial probe passes; mocked adapters and process wrappers are not containment evidence.

The supported promotion backends are concrete:

- **Linux:** rootless Podman with an image pinned by digest, `--network=none`, read-only root/input mounts, a distinct output volume, dropped capabilities, `no-new-privileges`, PID/memory/CPU/time limits, and a fresh container per seed.
- **Native Windows:** an ephemeral Hyper-V Generation-2 VM restored from a hash-pinned clean checkpoint for every seed, with virtual NIC disconnected, Enhanced Session/clipboard/host shares disabled, fixed CPU/memory/time limits, a read-only input VHDX, a distinct output VHDX detached before host import, and no host filesystem mapping. The probe verifies Hyper-V cmdlets/service, virtualization, disk/checkpoint hashes, NIC absence, reset cleanliness, and process termination.

The Windows/cross-platform stratum must execute on the native Windows backend for promotion; Windows compiler/unit CI alone cannot substitute. The runner may be a separately pinned Windows host when the developer machine lacks Hyper-V, but it must emit the same schema-valid capability/result attestation and immutable disk/tool hashes. Both conditions for a paired task always use the same backend snapshot and budgets.

If a required backend probe fails or the backend is unavailable, the harness enters `import_only`: it may validate previously attested results but cannot execute or claim containment. Missing Linux evidence or missing native-Windows evidence for its required stratum blocks QL-07 promotion. Real escape tests cover input writes, sibling reads, host-path traversal/reparse points, environment/secret access, network/DNS, child-process survival, resource exhaustion, and output-channel smuggling.

### 7.5 Statistical unit and sample-size rationale

The frozen minimum clinically important difference (MCID) is `+0.25` on a `0..4` paired task score, equivalent to `+6.25/100`. With an assumed paired standard deviation near `0.55`, the standardized effect is approximately `0.45`; a normal approximation gives roughly 39 independent task clusters for 80% power at a two-sided 5% level. Forty-eight sealed tasks provide a modest buffer for unusable cases without pretending that multiple seeds are independent samples.

This variance estimate is a planning assumption, not evidence. The paired standard deviation may be recalculated once from the 12 calibration cases before any sealed result is revealed. It may change the preregistered sample size, never the MCID or promotion threshold. If more than 48 sealed tasks are required, add and freeze them before unblinding, up to a hard maximum of 72; if more are required, the study is not promotion-capable under this plan. After unblinding, thresholds and task inclusion are frozen.

For binary sandbox outcomes, use calibration discordance to power a paired McNemar/non-inferiority design. The execution subset starts at 24 tasks and expands up to the full sealed set before unblinding. If the required power cannot be reached with the available sealed set, sandbox results remain safety-only and cannot satisfy the execution-lift promotion branch.

### 7.6 Task-level aggregation contract

All inference operates on one record per task.

- Within each condition, average rubric dimension scores across the two valid judges for each seed, then average the two seed scores. The paired task delta is `candidate_task_score - baseline_task_score`.
- Bootstrap only the sealed task deltas, stratified by corpus stratum. Seeds, judges, votes, and individual plans are repeated measurements, not independent samples.
- Each judge compares seed-matched pairs, producing four pairwise votes per task (`2 seeds x 2 judges`). Candidate wins the task with at least three candidate votes; baseline wins with at least three baseline votes; every other pattern is a tie.
- Calculate the Wilson interval only over non-tied task outcomes.
- For sandbox execution, primary task-condition success means **both seeds** pass all hidden tests and safety gates. McNemar/non-inferiority uses exactly one resulting binary per task and condition. Per-seed pass fraction is secondary stability evidence and never an independent sample.
- A `planner_miss_episode` is one unique causal planning omission within one seed, keyed to the missing requirement, decision, dependency, or verifier. Repeated symptoms/amendments caused by the same omission are deduplicated under the independently calibrated partition protocol in Section 10.1; phase splitting or merging cannot create or erase episodes. For each task/condition, average the adjudicated episode counts across its two seeds. Bootstrap only the resulting one candidate-minus-baseline count delta per task.
- A candidate-only semantic hard failure assigns the affected seed a total score of zero and a baseline pairwise vote. A baseline-only hard failure does the symmetric opposite. Shared failures remain in hard-failure counts and are never dropped.
- A missing/invalid judge result is retried once, then human-adjudicated. A missing sandbox run is a failed condition unless the whole case is declared harness-invalid before unblinding; more than 5% harness-invalid cases invalidate the study.

### 7.7 One preregistered primary execution endpoint

`promotion_policy.primary_execution_endpoint` is frozen exactly once before sealed-task unblinding, using only development/calibration evidence. The deterministic selection rule is: choose `hidden_pass` when its lift test reaches at least 80% planned power within the frozen sealed-set cap; otherwise choose `planner_miss_count` only when hidden-pass non-inferiority remains adequately powered, the frozen outcome-label calibration in Section 10.1 passes, the calibration baseline mean episode count per task is non-zero, and the preregistered task-cluster lift analysis reaches at least 80% planned power. If neither branch qualifies, the study is not promotion-capable. No discretionary choice between two qualified endpoints is allowed: `hidden_pass` wins by default. Low hidden-pass discordance is reported as a power limitation, never used after unblinding to switch endpoints.

For `hidden_pass`, use the same one-binary-per-task definition as Section 7.6, an exact conditional McNemar test for paired binary hypotheses, and a preregistered matched-pair score interval for the paired risk difference. The power calculation, Gate 7 non-inferiority, and Gate 8 lift must use this same paired method; a generic task bootstrap may not replace it.

For `planner_miss_count`, the estimand is the paired relative change in mean canonical miss episodes per task, `(candidate_mean - baseline_mean) / baseline_mean`. Use the one averaged count record per task from Section 7.6 and a stratified paired task-cluster bootstrap over that same relative-change estimand. Executed phases are never the denominator of a promotion-authoritative metric. The baseline mean must be greater than zero, the frozen outcome-classification calibration remains a prerequisite, and any condition-dependent episode-deduplication or exposure rule invalidates the run.

Both endpoints are always reported. Only the preregistered primary endpoint can satisfy Gate 8 or authorize promotion; the secondary endpoint is descriptive and cannot rescue a failed or underpowered primary result.

## 8. Rubric and grading

### 8.1 Weighted rubric

Each dimension is scored `0..4`; weighted total is `0..100`.

| Dimension | Weight | 0 | 2 | 4 |
|---|---:|---|---|---|
| Intent fidelity | 20 | Wrong mission or scope | Mostly aligned, material ambiguity remains | Exact mission/class, constraints, and non-goals preserved |
| Evidence grounding | 15 | Fabricated or unlabeled assumptions | Sources present but gaps blur | Facts/inference/unknowns separated with falsifiers |
| Decision quality | 15 | Architecture by reflex | Plausible choice with shallow alternatives | Credible options, explicit trade-offs, reversible selection |
| Traceability | 15 | Major requirements orphaned | Main path mapped, edge gaps | Complete requirement-to-evidence graph |
| Executability | 15 | Impossible order/commands/state | Mostly runnable with repair needed | Fresh executor can run every slice in order |
| Risk and rollback | 10 | Unsafe or no recovery | Common risks covered | Concrete failure/permission/rollback contracts |
| Simplicity | 5 | Bloat masks uncertainty | Some unnecessary machinery | Smallest sufficient architecture with removal conditions |
| Adaptability | 5 | Plan cannot absorb new evidence | Informal revision path | Explicit falsifiers, state ownership, and bounded replan |

`0` on intent fidelity, evidence grounding, executability, or risk can never be averaged away.

### 8.2 Hard-failure catalog

Any of these is a failed case regardless of total score:

- **P0:** unsafe production/destructive action without authority and rollback;
- **P0:** secret/private-data egress violation;
- **P0:** plan/package split-brain or stale-plan execution that can authorize an unsafe action;
- **P1:** wrong goal or wrong source context;
- **P1:** omitted must requirement;
- **P1:** invented critical fact;
- **P1:** missing critical dependency or impossible critical command/state order;
- **P1:** completion criteria that can pass while required behavior is broken;
- **P1:** critical overengineering that materially increases blast radius without evidence.

P2/P3 rubric defects remain scored findings but are not called hard failures. Promotion requires absolute zero candidate P0/P1 on sealed tasks; a baseline failure never excuses the same candidate failure.

### 8.3 Grader stack

1. **Deterministic graders** — traceability, schema, command graph, source binding, mutation safety, secret scan, cost and length.
2. **Two independent blinded semantic judges** — pairwise preference plus dimension scores and evidence pointers. One model family must not be sole authority over its own plan.
3. **Sandbox execution grader** — the same frozen executor attempts both conditions on clean clones; hidden tests and a safety monitor score actual usefulness.
4. **Human calibration/adjudication** — all hard failures, all judge disagreements, and a random 20% sample.
5. **Live outcome grader** — canary metrics from approved real runs, never inferred from plan prose.

Judge calibration gates:

- at least 80% agreement with expert labels on the calibration set;
- at least 90% verdict consistency under A/B position swap;
- unweighted kappa for nominal win/tie/loss, verdict, and hard-failure categories is at least `0.67`;
- two-way random-effects absolute-agreement ICC for continuous rubric totals/dimensions is at least `0.75`;
- if calibration fails, semantic scores are advisory and cannot promote the candidate.

## 9. Promotion policy

The candidate becomes the default only when all gates pass:

1. Candidate `P0 = 0` and `P1 = 0` on every sealed task. Wrong-context, unsafe-action, privacy/secret, and stale-authority failures are absolute zero-tolerance classes on every evaluated set.
2. All deterministic hard-gate fixtures pass; zero baseline hard failures means the candidate must also have zero, while a non-zero baseline may be improved but never used to waive a candidate failure.
3. Blind pairwise win rate is at least 60% of non-ties and the 95% Wilson lower bound is above 50%.
4. Mean weighted score improves by at least the frozen MCID of `6.25/100` on sealed promotion tasks, and the stratified task-cluster bootstrap 95% confidence interval for the paired delta is entirely above zero.
5. No stratum regresses by more than 5 points; production/safety and wrong-context strata may not regress at all on hard failures.
6. Stability does not worsen: candidate repeated-run standard deviation is no greater than `max(1.2 x baseline SD, 3/100)`. The absolute `3/100` margin governs when baseline SD is below `2/100` or zero.
7. Sandbox pass-rate non-inferiority holds: the one-sided 95% lower bound from the preregistered matched-pair score interval for the task-level candidate-minus-baseline hidden-test pass difference is above `-5` percentage points.
8. The single preregistered primary execution endpoint passes its frozen lift rule. If it is `hidden_pass`, pass rate improves by at least 10 percentage points and the matched-pair 95% lower bound is above zero. If it is `planner_miss_count`, the paired relative change in canonical miss episodes per task is at most `-15%` and the stratified task-cluster-bootstrap 95% upper bound for that same relative-change estimand is below zero. Endpoint substitution after sealed unblinding is forbidden; a failed/underpowered primary result cannot be rescued by the secondary endpoint.
9. The result shows a clear quality leap: either mean weighted score improves by at least `10/100`, or Gate 8 proves an execution lift while the score improves by at least `6.25/100`.
10. Median planning tokens grow no more than 15% unless Gate 8 proves the execution lift. Even with a proved lift, hard caps are 1.5x baseline for normal plans and 2.0x for high-risk plans; p95 latency is no more than 2.0x.
11. Median rendered plan length grows no more than 15% unless the extra content closes rubric-proven gaps and Gate 8 passes.
12. The live canary returns `no_veto` at the single fixed final analysis of 30 candidate tasks and at least 150 phase exposures under Section 10.2. It is a veto/safety gate, not promotion-lift evidence; unmatched historical/live comparisons cannot satisfy Gate 8.
13. Cross-platform, privacy, package, and existing full-suite gates remain green.

No single aggregate score can override a hard failure or a critical-stratum regression.

### Stop rules

- After two candidate iterations without a statistically credible win, do not add more personas or prompt text. Reassess the root hypothesis.
- If deterministic lint provides most of the gain and critic/repair does not add at least 5 points or reduce hard failures, ship the linter and delete the semantic loop.
- If semantic judging cannot be calibrated, keep human review for experiments and do not make judge scores release authority.
- If the fixed live-canary analysis returns `veto` or `inconclusive`, disable the canary profile and retain the frozen baseline.
- If more than 5% of sealed cases fail because of the harness, environment, or condition-skewed infrastructure, invalidate the run rather than dropping inconvenient cases.
- An interim read after 24 sealed tasks may stop only for safety or futility (`paired delta <= 0` plus candidate-only hard failures). Early promotion is forbidden.
- A leaked or materially edited sealed case is removed only by rotating it before a fresh full run; it is never silently excluded after scoring.

## 10. Outcome feedback

Offline plan preference is necessary but not sufficient. For canary executions, record:

- post-launch changes to requirements, phases, criteria, or architecture;
- blockers caused by missing context or dependencies;
- commands/deliverables added outside the approved plan;
- failed verification rounds and root cause;
- user corrections such as “wrong task,” “too narrow,” “why are you asking,” or “finish it”;
- unnecessary approvals and courtesy stops;
- rollback or recovery events;
- elapsed time, token/tool cost, and time to first verified increment;
- final completion and residual risk.

Classify each amendment as:

- `external_change` — reality changed after planning;
- `acceptable_discovery` — could not reasonably be known before execution;
- `planner_miss` — should have been represented in the original plan;
- `executor_deviation` — plan was adequate but execution diverged.

Only `planner_miss` counts directly against plan quality. This avoids punishing the planner for external changes or executor defects.

For comparison, report (a) the proportion of tasks with at least one canonical `planner_miss_episode`, (b) mean canonical episodes per task, and (c) episodes per ten executed phases as a descriptive workload diagnostic only. Promotion inference uses paired task counts, never the candidate-authored phase denominator. Real live canaries are generally unmatched and therefore may veto promotion for safety/regression, but may not establish the causal execution lift used by Gate 8.

### 10.1 Outcome-classification contract

Candidate planners/operators do not label their own misses.

- Before any candidate scoring, experts freeze both amendment-class labels and the causal episode partition/signature for calibration data. Two condition-blinded adjudicators then independently label and group every calibration or sealed amendment before seeing each other's labels, groups, or any adjudication result.
- Adjudicators receive normalized execution logs, plan/contract diffs, phase/event records, verifier results, and user-correction timestamps, with condition/version identity removed.
- Every amendment label requires artifact/log pointers, the before/after plan hash, the triggering evidence, and a short falsifiable causal rationale.
- Every `planner_miss` label also carries a condition-blinded causal episode signature (`omission_kind`, normalized target IDs, first triggering evidence hash) and provisional `miss_episode_id`. Within a task/seed, grouping is the equivalence partition over those signatures; IDs themselves have no cross-condition meaning.
- Labels use the frozen four-class taxonomy above plus `insufficient_evidence`; the latter cannot be silently reassigned to a favorable class.
- Classification finishes before condition unblinding. A third adjudicator resolves disagreements using the same frozen evidence contract.
- On frozen calibration labels, each adjudicator must achieve `planner_miss` precision at least `0.80`, recall at least `0.80`, and five-class macro-F1 at least `0.75` against expert truth; unweighted Cohen kappa between the two initial adjudicator labels must be at least `0.67`.
- Episode calibration requires at least 30 positive `planner_miss` manifestations, 12 expert episodes, and 6 multi-manifest episodes. For each adjudicator, pairwise same-episode precision/recall/F1 against the frozen expert partition must each be at least `0.85`; between the two initial partitions, pairwise co-clustering F1 must be at least `0.80`. Per-seed episode counts must have at least 80% exact agreement with expert counts and a two-way absolute-agreement ICC of at least `0.80`.
- The third adjudicator resolves both class and partition disagreements from the same evidence before condition unblinding. The adjudicated partition, never a condition-specific heuristic, produces the promotion count.
- If either label or episode-partition calibration/support fails, `planner_miss_count` cannot be selected as the primary execution endpoint and no rework claim can authorize promotion. A later sealed-sample result cannot repair failed calibration or change the frozen endpoint.
- Initial class/partition/count agreement on sealed/live records is reported only as drift monitoring. A material drop triggers adjudication review and can invalidate the outcome endpoint, but it is not a second calibration opportunity and never increases promotion evidence.
- The immutable `OutcomeReceipt` stores adjudicator IDs/classes, evidence hashes, both initial labels/episode signatures/partitions, adjudicated label/partition/count, taxonomy/partition-policy versions, and condition-unblinding timestamp.

### 10.2 Live-canary veto contract

Live canary is unmatched safety evidence and has three outcomes: `no_veto`, `veto`, or `inconclusive`.

Before canary start:

- freeze a matched historical baseline window of at least 30 comparable tasks and 150 executed phases across the same risk strata;
- compute one-sided 95% lower/upper bounds for the proportion of tasks with any canonical `planner_miss_episode`, treating each task as one Bernoulli cluster;
- freeze the candidate ceiling as `baseline task-miss upper bound + 5 percentage points`. Mean episodes per task and episodes per ten phases are reported descriptively, but neither may decide this unmatched veto gate or reward phase splitting;
- freeze the candidate sample at exactly 30 tasks with a required minimum of 150 controller-confirmed phase exposures and the same risk-stratum allocation. Exposure is operational coverage only: plan-authored phase splits mapped to the same acceptance criterion count once, and phase events are never statistical observations. There is one ordinary metric analysis, after task 30; no optional expansion or repeated confidence-interval look is permitted.

Candidate evaluation:

- any P0/P1, privacy violation, or safety violation is immediate `veto`;
- the first ten tasks are an operational checkpoint only for those immediate stop classes, harness integrity, privacy, and exposure tracking; they produce no ordinary metric verdict or interval-based stop;
- at task 30, if candidate exposure is below 150 controller-confirmed phase exposures, the result is `inconclusive` and promotion is blocked;
- otherwise, `no_veto` requires the candidate one-sided 95% upper bound for the task-miss proportion to be at or below the frozen ceiling;
- `veto` requires an immediate stop above or, at the fixed final analysis, the one-sided 95% lower bound above that frozen ceiling;
- every other fixed-sample result is `inconclusive` and blocks promotion. Inconclusive is never rounded to pass, and no extra tasks may be added to chase a verdict under this plan revision.

## 11. Permissions, data, and failure behavior

### 11.1 Permission matrix

| Actor | Read | Write | Decide | Forbidden |
|---|---|---|---|---|
| Planner | Only the planner-visible input/context packet released for its current case | Draft package and quality dossier in its isolated output directory | Candidate plan | Hidden truth/labels/tests, condition identity, other sealed cases, implementation, or arbitrary egress |
| Critic | Frozen intent/evidence and draft | Findings only | Recommend mutations | Worktree mutation or rubric changes |
| Judge | Blinded plans, rubric, allowed evidence | Signed verdict | Ready/repair/blocked within rubric | Editing plans or seeing version identity |
| Benchmark runner | Cases, adapters, outputs | Immutable run artifacts | Statistical report | Executing untrusted candidate repo code outside sandbox |
| Human reviewer | Calibration and disputed evidence | Labels/approval | Promotion and irreversible exceptions | Silent rubric changes after seeing results |
| Executor | Approved final package | Approved implementation scope | In-scope execution choices | Reopening hidden planning truth or weakening quality gates |

### 11.2 Data classification

- public corpus: sanitized, source-citable, no credentials or private chats;
- calibration labels: internal but reviewable, versioned and hashed;
- hidden holdout: private; only manifest hashes and aggregate results enter the public repo;
- every sealed case is physically split into planner-visible input and controller-only truth/labels/tests/condition identity; the planner receives one input packet at a time;
- plan inputs/outputs: internal by default; redact secrets and private paths before judge egress;
- outcome receipts: aggregate/redacted in public artifacts; raw traces remain local/private;
- model prompts and responses: never contain `.env`, tokens, private Telegram content, payment/user data, or unredacted production logs.
- external semantic providers must have an explicitly approved retention/training policy for the data class being sent; otherwise use a local judge or keep the case out of that provider. No implicit provider upload is permitted.

### 11.3 Failure-mode matrix

| Failure | Behavior | Promotion impact |
|---|---|---|
| Missing authoritative context | Mark assumption or block planning | Hard fail if silently invented |
| Deterministic lint red | Targeted repair, max two rounds | Cannot dispatch while red |
| Critic unavailable | Continue only with lint; mark semantic review unverified | Cannot promote full loop |
| Judges disagree | Human adjudication | No automatic verdict |
| Judge calibration fails | Treat semantic scores as advisory | Promotion blocked |
| Holdout unavailable/leaked | Rotate/rebuild holdout | Promotion blocked |
| Adapter exfiltration/network escape | Stop run, rotate exposed cases, preserve redacted incident evidence | Run invalid; candidate cannot promote |
| Cost budget exceeded | Stop loop; report baseline fallback | Candidate fails efficiency gate |
| Live canary regresses | Disable `quality-canary` profile | Default remains baseline |
| Outcome telemetry risks privacy | Store only local aggregate or disable | Never weaken privacy to save an eval |

## 12. Delivery plan

Each phase is independently verifiable. Runtime behavior remains unchanged until Phase 6 canary activation, and default behavior remains unchanged until Phase 8 promotion.

### 12.1 Dependency and write-scope map

| Phase | Depends on | Write scope | Explicit exclusions |
|---|---|---|---|
| B2-00 | none | Neutral comparison harness, branch-value audit, adoption ADR/disposition manifest | Quality-engine implementation or automatic whole-branch merge |
| B2-01 | B2-00 | Exact selected foundation branch/SHA, provenance/capability manifests including `native_windows_v1`, reviewed-plan transplant, neutral-harness rerun | Quality-engine code, plain-main foundation, or quality Project Flow state |
| 0 | B2-01 | Quality ADR, selected-foundation baseline manifests, replay/pinning of frozen B2 false-green tests | Planner/runtime behavior |
| 1 | 0 | Eval schemas, corpus, rubric, manifests, fairness tests | Candidate planner logic |
| 2 | 0, 1 | Deterministic quality/traceability modules, policy/schema, `sgctl`, quality tests | Model calls, semantic judge, runtime execution |
| 3 | 1, 2 | Offline benchmark/judge adapters, versioned Podman/Hyper-V sandbox backends, capability/result schemas, eval/security tests | Package runtime/provider SDKs, production execution outside a probed backend |
| 4 | 2, 3 | Planner references/protocol, quality report rendering, canary planning tests | Implementation phases, default profile change |
| 5 | 3, 4 | Frozen eval outputs and comparison reports | New runtime mechanisms or threshold changes |
| 6 | 2, 4, 5 | Canary profile, compiler/validator/report sealing, SSHSIG Stage-6 authority/event guards, compatibility tests | Default promotion |
| 7 | 3, 6 | Sealed eval reports, redacted outcome receipts, canary evidence | Public raw traces, default promotion |
| 8 | 7 | Promotion ADR/schema decision, default/profile docs, release artifacts | Threshold rewriting after results |

Minimum slice contract for every phase:

- focused tests for every changed invariant;
- `git diff --check` and privacy/secret scan for changed artifacts;
- exact machine-readable evidence saved before the phase is marked complete;
- full existing unit/integration/release matrix from Phase 6 onward;
- no later phase may start while a declared dependency has unresolved P0/P1 or missing evidence.

### 12.2 Post-approval Project Flow seed

Before explicit approval, do not create a Project Flow `STATE.yaml`, claim a slice, or start an executor. After approval, use **two separate Project Flow runs** so branch selection cannot be retroactively justified by quality implementation:

1. create a foundation-audit DecisionPackage/`STATE.yaml` containing only B2-00 and B2-01; run both as evidence-gated Shaw slices and close that Flow only after the selected foundation, provenance, and transplanted reviewed plan are verified;
2. only then create a new quality-leap DecisionPackage/`STATE.yaml` on the exact B2-01 foundation, beginning at QL-00. No quality slice may exist as claimed/in-progress before the foundation Flow is closed.

The rows below are seeds for those two runs, not one shared state file.

| Slice | Inputs | Outputs | Mandatory verification | Completion evidence | Stop/rollback rule |
|---|---|---|---|---|---|
| B2-00 branch value | `main` `35a22fe`, hardening `5725192`, commit/diff clusters, clean Windows/Linux worktrees | neutral harness, five frozen false-green fixtures/review receipts, value audit, adoption ADR, disposition manifest, selected foundation specification | neutral black-box suite and dependency-aware ablations; each branch's native suite; Windows/Linux matrix; preregistered performance/size comparison; independent P0/P1 review | per-cluster failure/benefit/cost evidence, raw command records, exact decision and intended selected composition | No whole-branch adoption by default; unresolved P0/P1 or ambiguous value blocks B2-01; no plain-main quality fallback is authorized |
| B2-01 foundation materialization | B2-00 ADR, disposition/dependency manifests, reviewed plan commit, `native_windows_v1` contract | exact whole/curated/`main + native_windows_v1` foundation branch and SHA, provenance/cherry-pick and capability manifests, plan transplanted onto that SHA, rerun evidence | clean reconstruct from manifests; native full suite; neutral harness; Windows CPython 3.11/3.13 path/locking/reparse/race/determinism matrix; Linux parity; plan SHA/content check; independent P0/P1 review | exact foundation and rollback SHAs/profiles, `native_windows_v1` implementation/evidence hashes, commit provenance, command records, closed foundation Flow | Any missing Windows capability, unexplained delta, failed retained test, or plan drift reopens B2-00; quality Flow/QL-00 must not be created |
| QL-00 baseline | B2-01 exact selected foundation SHA, selected compiler, frozen B2 fixtures | quality ADR, pinned baseline adapter/manifest, replayed false-green records | exact selected HEAD; baseline adapter run; `python -m unittest tests.quality.test_baseline_false_greens`; `git diff --check` | command records, environment/version manifest, fixture/report hashes | Stop if selected baseline or B2 fixture verdicts cannot be reproduced on Windows and Linux; no candidate work |
| QL-01 corpus | QL-00 ADR/defects, sanitized task sources | 24 dev cases, 12 frozen calibration cases/labels, schemas/rubric/policy, sealed manifest | `python -m unittest tests.quality.test_eval_case_contract`; schema validation; two-reviewer fairness receipts | case counts/hashes, review receipts, negative unfair-case result | Remove/repair unfair cases before any candidate scoring; never tune on sealed labels |
| QL-02 deterministic B | QL-00 defects, QL-01 contracts | `quality.py`, typed model/policy fields, opt-in CLI/profile behavior, mutations | `python -m unittest tests.quality.test_quality_lint tests.mutation.test_quality_false_green_mutations`; focused CLI fixtures; legacy golden outputs | stable diagnostics, negative-fixture matrix, legacy compatibility hashes | If false blocks cannot be bounded, keep report-only mode; do not change default strict behavior |
| QL-03 offline eval | QL-01 corpus, QL-02 deterministic graders | isolated `evals/` harness, blind/judge adapters, Podman/Hyper-V backends and capability schemas, calibrated judge report | blind/judge tests; real Linux/Windows escape/resource/reset probes; `import_only` negative tests | anonymization/calibration metrics, deterministic replay hash, backend/image/disk attestations, containment reports | Calibration/containment failure or missing required native-Windows backend blocks promotion; no provider code enters runtime |
| QL-04 bounded C canary | QL-02 green lint, QL-03 calibrated protocol | host planning stages, policy-recomputed B/B+C lane, sealed quality report view | `python -m unittest tests.e2e.test_quality_canary_planning`; forged-lane/max-two/no-progress fixtures; skill/package guards | mutation ledger, chain-of-thought absence scan, prompt-size delta, policy-route evidence | Prompt growth >10%, a third repair cycle, or unresolved policy/critic P0/P1 blocks the slice |
| QL-05 ablation | Frozen QL-01/03 manifests, QL-04 candidates | baseline/A-only/B-only/B+C comparison report | `python evals/run.py compare --manifest <frozen-manifest>`; report schema/hash validation | per-stratum score/hard-failure/cost tables and frozen verdict | Delete C if it fails its incremental-gain/removal gate; thresholds cannot change after scoring |
| QL-06 compiler canary | Selected QL-05 candidate, QL-02 policy, protected canonical Windows/Linux SSHSIG trust configuration and offline signer | `quality-canary` profile, staged compile/composite package gate, manifest/hash binding, signed Stage-6 receipt/event/readiness guards | hash projection; sign/verify/revoke; trust-root/ACL/oracle/swap negatives; generic-transition bypass; receipt/event/crash tests; full suite; compile twice; Windows/Linux matrix | canary/default golden outputs, canonical config/signer/KRL snapshots and contract/report/receipt/event/package hashes, canary rollback proof | Missing offline-signer/verifier capability or any compatibility/security/approval-authority regression disables the profile; default remains pinned B2-01 baseline |
| QL-07 promotion study | QL-03 probed Linux/Windows backends, QL-06 canary, sealed controller inputs | sealed paired plans/executions, single-primary-endpoint statistical report, 30-task/150-phase live-canary receipts | promotion command; endpoint/method revalidation; backend-attestation validation; required native-Windows stratum; fixed-look canary; privacy/secret scan; independent adjudication | task-level deltas/CIs, hard-failure ledger, immutable sandbox backend/results, live veto report | Any gate red, endpoint switch, missing/porous backend, leak, >5% harness invalidity, insufficient power, or fixed-sample inconclusive means no promotion |
| QL-08 release decision | Immutable QL-07 verdict, all prior evidence | promotion/no-go ADR, optional schema/default change, docs/release artifacts | full existing release suite; deterministic package/archive checks; `git diff --check`; independent P0/P1 review | exact commit/report/package hashes, rollback proof, release checklist | If any promotion gate no longer holds, ship no-go and keep baseline default |

### Phase 0 — Freeze baseline and ADR

**Scope**

- Freeze the exact materialized foundation commit produced by Gate B2-01, its prompts/references, test evidence, and three representative generated packages.
- Write the quality authority ADR, non-goals, cost budget, and deletion rules.
- Replay and pin the five semantic false-green fixtures already created and independently reviewed in B2-00; Phase 0 may not redefine them after the foundation decision.
- Build a baseline adapter that always executes a clean worktree/container pinned to the selected foundation SHA, or validates immutable captured outputs from that exact environment. Candidate tests must never reinterpret the current moving `sgctl` as the baseline.

**Expected files**

- `docs/adr/ADR-004-eval-driven-plan-quality.md`
- `evals/baselines/v3-baseline-manifest.json`
- `evals/baselines/foundation-capabilities.json`
- `tests/quality/test_baseline_false_greens.py`

**Acceptance**

- Baseline artifacts are hash-pinned and reproducible on Windows and Linux.
- The exact selected foundation proves `native_windows_v1` on native Windows CPython 3.11/3.13; plain `main` or an evidence-free compatibility claim fails Phase 0.
- Every false green is a real semantic defect accepted by current structural validation.
- Baseline-acceptance evidence remains reproducible after the candidate CLI changes, while separate candidate tests require the new quality lane to reject those same cases.
- No production/default planner behavior changes.

**Verification**

```text
python scripts/sgctl.py validate-contract <baseline-contract> --strict --format json
python -m unittest tests.quality.test_baseline_false_greens
git diff --check
```

### Phase 1 — Corpus, rubric, and fair-case gate

**Scope**

- Define schemas for eval cases, expert labels, rubric, holdout manifest, and run records.
- Build all 24 development cases and all 12 calibration cases with frozen expert labels before implementing the candidate loop. Candidate prompts, rubric weights, and judge policy freeze before calibration scoring used for promotion setup.
- Add case-fairness review and mutation/variant rules.

**Expected files**

- `spec/eval-case.schema.json`
- `spec/eval-label.schema.json`
- `spec/outcome-receipt.schema.json`
- `spec/outcome-partition-policy.json`
- `spec/quality-rubric.json`
- `spec/plan-quality-policy.json`
- `spec/promotion-policy.json`
- `evals/corpus/public/`
- `evals/manifests/holdout-manifest.json`
- `tests/quality/test_eval_case_contract.py`

**Acceptance**

- Every case validates, has source hashes, truth set, ambiguity policy, and grader rationale.
- At least two reviewers approve every calibration case.
- A malicious/underspecified/unfair case fixture fails closed.
- Semantic lane/judge routing and the single primary execution endpoint selection procedure are frozen before sealed unblinding.
- Outcome calibration assets contain the minimum positive/multi-manifest episode support from Section 10.1 with expert-frozen labels and partitions.

### Phase 2 — Deterministic quality linter

**Scope**

- Implement `IntentContract`, traceability graph, quality findings, and hard lint rules.
- Implement policy recomputation from normalized risk/action/profile inputs; reject declared lane/judge-policy mismatches and risky-command tag omission.
- Add `sgctl quality-lint` and machine-readable diagnostics.
- Implement the command/profile matrix from Section 6.4 as opt-in candidate behavior. Do not globally change legacy/default `--strict` outcomes in this phase.
- Type command `cwd`, mutation class, availability dependency, and expected output; type rollback and source/research linkage instead of accepting arbitrary non-empty prose.
- Add conservative undeclared-risk detection with an explicit evidence-backed waiver path.
- Add mutation tests for orphan requirements, fake behavioral criteria, impossible order, unverified critical assumptions, and missing rollback.

**Expected files**

- `lib/chip_supergoal/quality.py`
- `lib/chip_supergoal/model.py`
- `lib/chip_supergoal/pipeline.py`
- `lib/chip_supergoal/validate.py`
- `scripts/sgctl.py`
- `spec/quality-gate.schema.json`
- `spec/contract.schema.json`
- `spec/diagnostic-catalog.json`
- `spec/invariant-catalog.json`
- `tests/quality/test_quality_lint.py`
- `tests/mutation/test_quality_false_green_mutations.py`

**Acceptance**

- All Phase 0 false greens are rejected by stable diagnostic codes.
- Existing valid v3 packages remain valid when the canary profile is off.
- New command/rollback/source fields are additive/optional for legacy v3 input and required only by the quality policy; explicit migration/golden tests cover their later promotion.
- The linter does not use an LLM or network and is deterministic byte-for-byte.
- A shallow contract cannot pass by supplying `echo ok`, `python -c "pass"`, one-character rollback, fake research shape, or undeclared destructive production language.
- Quality findings extend the existing diagnostic/invariant catalogs; no second diagnostic authority is introduced.
- Forged high-risk `b_only`, stale policy-version, and risky-command-without-risk fixtures fail closed.

### Phase 3 — Blind benchmark runner and judge calibration

**Scope**

- Implement recorded-file, manual-import, and external-command planner adapters under a developer-only `evals/` harness, outside package runtime modules.
- Implement anonymization, order randomization, deterministic graders, judge result import, confidence calculations, and reports.
- Implement the versioned backend/capability contract from Section 7.4, concrete rootless-Podman and Hyper-V adapters, `import_only` fallback, and hidden-test/safety-monitor result import; do not execute untrusted candidate code outside a probed backend.
- Run external planner/judge commands in those ephemeral sanitized backends: read-only planner-visible inputs, output-directory-only writes, no network by default, allowlisted environment, CPU/memory/time caps, schema-only result import, and recorded allowlisted egress only through a separately reviewed case/backend profile.
- Calibrate at least two independent semantic judges against expert cases.
- Calibrate the two outcome adjudicators on both amendment labels and causal episode partitions before `planner_miss_count` can enter the endpoint-selection rule.

**Expected files**

- `evals/run.py`
- `evals/harness/benchmark.py`
- `evals/harness/judging.py`
- `evals/harness/execution_eval.py`
- `evals/harness/sandbox.py`
- `evals/harness/sandbox_podman.py`
- `evals/harness/sandbox_hyperv.py`
- `spec/eval-run.schema.json`
- `spec/judge-verdict.schema.json`
- `spec/sandbox-backend.schema.json`
- `tests/quality/test_blind_comparison.py`
- `tests/quality/test_judge_bias_controls.py`
- `tests/quality/test_outcome_partition_calibration.py`
- `tests/security/test_sandbox_backends.py`

**Acceptance**

- A/B identity is absent from judge payloads.
- Position-swapped fixtures expose a deliberately biased judge.
- The runner reproduces the same deterministic scores from the same artifacts.
- The same executor receives condition-equivalent permissions, repository snapshots, and budgets for both plans.
- No vendor SDK or secret is required by the public core.
- Tests prove `evals/`, judge adapters, and provider dependencies are absent from `RUNTIME_MODULES`, sealed package inventories, and package import graphs.
- Real Podman and Hyper-V adversarial probes prove hidden labels/tests, environment variables, host paths, network, surviving child processes, and sibling run outputs are inaccessible to the planner command; a missing capability produces `import_only`, never a synthetic pass.
- Native-Windows stratum execution evidence comes from a hash-pinned Hyper-V backend on the local or separately attested Windows runner; absence of that evidence blocks promotion.
- Label precision/recall/F1/kappa and episode co-clustering/count/ICC calibration gates from Section 10.1 reproduce from frozen expert assets; failure disables `planner_miss_count` rather than weakening thresholds.

### Phase 4 — Planner critic/repair canary

**Scope**

- Add the explicit intent, alternatives, draft, lint, critic, repair, and judge stages to the planning protocol.
- Encode the B-only versus B+C lane as the recomputed result of `spec/plan-quality-policy.json`, with stable reason, judge-required/status fields, and cost counters; preserve the existing Stage-6 human approval as the only dispatch authorization.
- Limit semantic repair to two rounds and enforce token/time budgets.
- Emit a sealed quality report and mutation ledger.
- Keep the feature behind `quality-canary`.

**Expected files**

- `SKILL.md`
- `references/quality-gate.md`
- `references/quality-rubric.md`
- `references/planner-critic-repair-loop.md`
- `lib/chip_supergoal/render.py`
- `templates/PLAN_QUALITY.md` or an equivalent generated report view
- `tests/e2e/test_quality_canary_planning.py`

**Acceptance**

- Critic findings either mutate the final plan or become evidence-backed checked-holds.
- Raw chain-of-thought is never persisted.
- Repeated no-progress findings block rather than loop.
- Existing non-canary output remains byte-compatible where promised.
- `QUALITY_GREEN` without explicit Stage-6 approval remains `AWAITING_STAGE6_REVIEW` and cannot become dispatch-ready.
- B-only E2E fixtures prove zero critic calls, zero judge calls, and zero semantic-review tokens/tools; B+C fixtures prove every repair is followed by deterministic re-lint.

### Phase 5 — Ablation and candidate selection

**Scope**

- Compare four frozen variants on the development/calibration corpus:
  1. baseline;
  2. prompt/rules only;
  3. deterministic linter only;
  4. linter plus critic/repair.
- Attribute quality and cost gain to each layer.
- Delete or simplify layers that do not earn their cost.

**Acceptance**

- A report shows per-stratum score, hard failures, win rate, stability, tokens, latency, and output length.
- No variant is selected from aggregate score alone.
- The selected candidate has unresolved P0/P1 findings equal to zero.

### Phase 6 — Contract/compiler canary integration

**Scope**

- Validate the exact `compatibility.quality_gate_v1.subject`/`.attestation` shape and the one-field-omission plan-subject hash projection under the canary profile.
- Seal quality reports into the package manifest.
- Implement the immutable OpenSSH-SSHSIG Stage-6 approval receipt and cross-platform capability probe. Keep `ready-to-dispatch` a pure validator; reserve `COMPILED -> PLAN_REVIEWED` to the receipt command and make every later pre-run transition re-run the receipt guard atomically.
- Make quality green necessary but not sufficient for canary dispatch; only an explicit current receipt plus composite preflight can authorize the transition.
- Add migration/rollback tests and maintain native Windows/Linux parity.

**Expected created/modified authorities**

- `profiles/quality-canary.json`
- `lib/chip_supergoal/compile.py`
- `lib/chip_supergoal/pipeline.py`
- `lib/chip_supergoal/validate.py`
- `lib/chip_supergoal/render.py`
- `lib/chip_supergoal/profiles.py`
- `lib/chip_supergoal/approval.py`
- `lib/chip_supergoal/evidence.py`
- `lib/chip_supergoal/events.py`
- `lib/chip_supergoal/state.py`
- `lib/chip_supergoal/portable.py`
- `lib/chip_supergoal/archive.py` when manifest sealing requires it
- `scripts/sgctl.py`
- `spec/stage6-approval.schema.json`
- `spec/stage6-trust.schema.json`
- `spec/event.schema.json`
- `spec/state.schema.json`
- `spec/state-machine.json`
- `spec/evidence.schema.json`
- `references/stage6-approval-signing.md`
- `tests/security/test_stage6_approval.py`
- `tests/support/stage6_trust_fixture.py` (test tree only; forbidden from runtime/package inventories)
- `templates/PROTOCOL.md`
- existing diagnostic/invariant/archive manifest specs as required by one canonical authority
- focused semantic, rendering, package, security, and E2E tests

**Acceptance**

- A forged, stale, or plan-mismatched quality report fails package validation.
- A forged, missing, stale, overwritten, wrong-package, or review-pack-mismatched Stage-6 receipt cannot produce a zero readiness exit or a `READY_TO_DISPATCH` transition.
- A valid current human receipt returns `READY_TO_DISPATCH` from the pure validator; recompilation or any bound-byte change returns nonzero and requires a new approval.
- Generic transition attempts cannot create `PLAN_REVIEWED`; all four pre-run journal edges carry and revalidate the conditionally required receipt hash, including substitution/deletion/crash-recovery tests.
- Real ephemeral Ed25519 SSHSIG sign/verify/revoke tests and `approval-source-probe` pass on supported native Windows and Linux; caller-selected/swapped trust roots through CLI or direct API, unsafe ACLs/reparse paths, hostile subprocess environments, online signing oracles, and post-receipt revocation fail closed without changing legacy/default behavior.
- Default profiles remain unaffected.
- Disabling the profile fully restores baseline compilation and launch behavior.
- Golden CLI/output/hash fixtures prove legacy/default compatibility and canary-only composite behavior.

### Phase 7 — Hidden holdout and live canary

**Scope**

- Complete the 84-case minimum corpus, run all sealed promotion cases, and execute the preregistered sandbox subset of 24–48 tasks as determined from calibration power.
- Freeze `promotion_policy.primary_execution_endpoint` from calibration only, then execute the selected paired endpoint with its matching inference method; report the secondary endpoint as descriptive only.
- Execute the fixed 30 approved candidate canary tasks and require at least 150 phase exposures after freezing the matched historical baseline window from Section 10.2; do not describe this unmatched comparison as causal lift evidence.
- Collect classified outcome receipts and audit disagreements.

**Acceptance**

- Holdout contents were not available to planner or candidate authors.
- Judge calibration and statistical gates pass.
- Outcome-label calibration passes if rework is the selected primary endpoint; sealed agreement is drift monitoring only.
- The single fixed live-canary analysis reaches `no_veto` under Section 10.2 rather than returning `inconclusive`/`veto` or being informally waived.
- Privacy review finds no raw private trace in public artifacts.

### Phase 8 — Promotion, schema decision, and polish/harden

**Scope**

- Make a go/no-go decision from frozen promotion rules.
- If green, decide via ADR whether quality becomes first-class schema v3.1 or remains a bounded compatibility contract.
- If red, keep baseline default and remove unproven runtime machinery.
- Run full regression, security, privacy, cross-platform, archive, deterministic build, documentation, and independent review.

**Acceptance**

- Promotion report cites exact immutable eval and canary artifacts.
- All existing release gates remain green.
- No P0/P1 review findings remain.
- Rollback is one documented profile/default change to the exact B2-01 SHA/profile, not a code archaeology exercise.
- Unmodified canary and promoted v3.1 package fixtures both validate/run through the documented rollback-compatible path.

## 13. Test strategy

### Deterministic tests

- schema and ID/property tests;
- traceability graph property/fuzz tests;
- mutation tests for each hard-failure class;
- deterministic compile/report hashing;
- forged/stale/mismatched report tests;
- Windows and Linux path/process behavior;
- privacy and secret scans;
- profile-off backward-compatibility tests.

### Semantic evals

- blind paired baseline/candidate comparisons;
- per-dimension rubric scores with evidence pointers;
- judge position-swap and verbosity traps;
- cross-model and expert calibration;
- repeated-run stability subset;
- metamorphic case variants;
- ablation of every new planning layer.

### Live verification

- paired execution by one frozen sandbox executor against hidden acceptance tests;
- scope/safety canaries and forbidden-action monitoring;
- plan amendment and rework classification;
- missed-dependency and impossible-command rate;
- user correction rate;
- final completion and residual-risk audit;
- tokens, latency, and plan length;
- rollback of the canary profile.

## 14. Principal risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Benchmark overfitting | High | The planner wins tests but not real work | Hidden holdout, metamorphic variants, live canary, corpus rotation |
| LLM judge bias | High | False promotion | Blinding, A/B swap, independent model families, expert calibration, hard deterministic authority |
| Rubric gaming through verbosity | High | Longer but not better plans | Length/cost metrics, blinded formatting normalization, simplicity dimension, hard outcome metrics |
| Harness becomes a second product | Medium | Maintenance bloat | Thin adapters, existing `sgctl`, no vendor platform, explicit deletion tests |
| Private history leaks into public evals | Medium | Privacy breach | Sanitization, hashes, private holdout, aggregate outcome receipts, egress policy |
| Quality gate blocks legitimate alternative plans | Medium | False negatives | Fair-case review, multiple valid strategies, human adjudication, canary before default |
| Same-model self-review creates review theater | High | Weak defects survive | Separate critic context, independent judge in eval, no self-score as sole authority |
| Runtime reliability regresses | Low/medium | Existing production value lost | Profile isolation, full old suite, byte-compat checks, immediate rollback |

## 15. Rollout and rollback

Rollout stages:

0. independent `fix/b2-hardening` value audit and foundation decision;
1. offline quality artifacts only on the selected foundation SHA;
2. deterministic lint in report-only mode;
3. `quality-canary` profile for selected planning runs;
4. hidden holdout and live canary;
5. default promotion only after all thresholds pass.

Rollback triggers:

- any confirmed candidate P0 or P1 in offline, canary, or post-promotion evidence;
- any breach of a frozen hard promotion gate, including a later regression after default promotion;
- hidden-holdout leak;
- critical-stratum regression;
- judge calibration below threshold;
- a fixed-sample live-canary `veto` or `inconclusive` result;
- any normal/high-risk token hard cap breach or p95 latency above `2.0x` baseline, unconditionally; quality gain cannot compensate for a hard cap;
- privacy or secret-scan finding.

Rollback action:

- Gate B2-01 must pin the exact rollback commit SHA and baseline/default profile hash before QL-00. Canary rollback disables `quality-canary` and restores those exact authorities rather than an informal “latest baseline”;
- after any v3.1/default promotion, ship a forward rollback patch that restores the pinned baseline default/profile while retaining a compatibility reader/executor for already compiled v3.1 packages;
- preserve eval artifacts for diagnosis;
- prove rollback against both a pre-promotion canary package and a promoted v3.1 package. Their original bytes, manifests, contracts, reports, receipts, and archives must validate/run under the documented compatible path without rewriting or downgrading either package;
- remove only unproven candidate integration, not the benchmark evidence.

## 16. Discussion points with recommended defaults

These are choices for review, not blockers to understanding the plan.

1. **B2 adoption prior:** assume neither whole-branch adoption nor rejection; preliminary prior is “valuable runtime foundation, unproved planning-value, possible curation,” decided by Gate B2-00 and materialized only by Gate B2-01.
2. **Quality target:** risk-tiered Senior/Principal rather than Principal ceremony for every task.
3. **Cost budget:** target no more than 15% median token growth; permit more only with measured execution lift, with hard caps of 1.5x normal and 2.0x high-risk. Run a semantic judge only where risk or benchmark policy requires it.
4. **Holdout owner:** private operator-controlled dataset with public manifest hashes.
5. **Historical corpus:** anonymize the most correction-heavy prior SuperGoals first, not the prettiest successful examples.
6. **Default execution route after approval:** Project Flow because this is multi-slice, stateful, and benchmark-gated work.
7. **Schema strategy:** bounded compatibility canary first; v3.1 only after measured success.

## 17. Cutover gates

Implementation must not start until this plan is reviewed and explicitly approved.

Default behavior must not change until:

- Gate B2-00 produces an evidence-backed adoption/curation/separation verdict, and Gate B2-01 materializes/verifies the exact implementation and rollback foundation;
- the selected foundation's sealed `native_windows_v1` capability/evidence manifest remains green on Windows 3.11/3.13 and Linux parity checks;
- the benchmark/corpus itself passes independent fairness review;
- the linter and judge controls are calibrated;
- the hidden holdout passes all promotion thresholds;
- live canary reaches `no_veto` under Section 10.2 and cost remains within Gate 10;
- unresolved P0/P1 findings equal zero;
- the full existing release suite stays green;
- rollback is demonstrated for both canary and promoted v3.1 packages against the exact B2-01 rollback SHA/profile without rewriting old packages.

Suggested approval text for a later execution session:

```text
APPROVE SUPERGOAL QUALITY LEAP PLAN v1.
Execute through Project Flow on a dedicated implementation branch.
Run Gate B2-00 first and do not assume fix/b2-hardening is adopted wholesale.
Close Gate B2-01 on the exact selected foundation before creating the quality Project Flow.
Keep existing SuperGoal behavior as default until every promotion gate in
docs/supergoal-quality-leap-plan.md passes. Do not weaken thresholds after
seeing candidate results; any change requires a new reviewed plan revision.
```

## 18. External reviewer brief

Another bot reviewing this plan should not merely summarize it. It should answer:

0. Do Gates B2-00/B2-01 fairly measure `fix/b2-hardening` cluster value, complexity, and direct plan-quality effect, then reproducibly materialize the selected foundation before quality work?
1. Does the plan attack the actual quality bottleneck, or create evaluation theater?
2. Which current repository claim or line contradicts the problem statement?
3. Can a weak but verbose plan still pass the proposed linter, rubric, and promotion gates? Show a concrete exploit.
4. Are the corpus size, holdout split, thresholds, and confidence rule sufficient for the claimed promotion?
5. Which module or artifact creates unnecessary split-brain or vendor dependence?
6. Which phase is not independently verifiable or has an impossible dependency?
7. What P0/P1 risks remain in privacy, judge bias, benchmark leakage, compatibility, or rollback?
8. What should be removed to make the design simpler without weakening evidence?

Required review format:

```text
Verdict: READY FOR DISCUSSION | REVISE | REJECT
P0/P1 findings: <count>
Evidence: file:line or exact plan section
Concrete failure scenario: <reproducible path>
Required mutation: <specific plan change>
Threshold challenge: <holds or revised value with reason>
Overengineering verdict: <holds or remove/simplify X>
```

## 19. Research basis

- [PlanBench](https://arxiv.org/abs/2206.10498) — motivates diverse, systematic benchmarks that separate planning ability from retrieval/world-knowledge familiarity.
- [SWE-bench](https://arxiv.org/abs/2310.06770) — grounds evaluation in real repository issues requiring coordinated multi-file reasoning.
- [SWE-bench Verified](https://openai.com/index/introducing-swe-bench-verified/) — shows why task specification, test fairness, environment reliability, and human validation of benchmark items matter.
- [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena](https://arxiv.org/abs/2306.05685) — documents position, verbosity, and self-enhancement biases and motivates calibrated, blinded judging.
- [AgentBench](https://arxiv.org/abs/2308.03688) — motivates multi-environment evaluation and failure-mode analysis for long-term reasoning and decision making.
- [GAIA](https://arxiv.org/abs/2311.12983) — motivates real-world tool-use tasks and held-out answers.
- [OpenAI Evals guide](https://developers.openai.com/api/docs/guides/evals) — separates test data from explicit graders and ground truth.
- [Anthropic evaluation design guidance](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests) — recommends task-specific, multidimensional evals, real task distributions, edge cases, and automation where possible.

## 20. Independent review ledger

Three read-only reviews were run against baseline `5725192` before this revision:

1. **Repository quality audit** — confirmed that current strict/package gates can accept plausible semantic false greens; identified missing composite strict behavior, source grounding, command execution metadata, undeclared-risk detection, research receipts, and machine-enforced RPD mutation evidence.
2. **Benchmark design review** — required task-level paired statistics, a larger sealed promotion set, equal model/tool/budget conditions, negative controls, and actual sandbox execution of both plans rather than judging Markdown alone.
3. **Architect+/RPD strategy review** — rejected prompt-only work, selected `B-first + bounded C + minimal A`, and required the semantic judge to stay in the host/offline plane rather than becoming a package runtime or second compiler.

The operator then added a mandatory requirement: evaluate the usefulness of `fix/b2-hardening` before treating it as the quality-engine foundation.

An exact-file P0/P1 review of revision 0.3 then rejected six remaining loopholes: plan-authored phase denominators could game rework lift; generic state transitions could bypass Stage 6; the receipt hash lacked an event-schema owner; plain `main` could discard required native Windows support; the human-origin receipt had no concrete cross-platform trust mechanism; and the promised native-Windows sandbox had no enforceable backend. Revision 0.4 closes them with canonical miss episodes per task, a single guarded runtime graph/event binding, OpenSSH SSHSIG approval, mandatory `native_windows_v1`, and probed Podman/Hyper-V backends. That rejected SHA is not a completion claim.

A second exact-file review of early revision 0.4 found that episode grouping itself lacked calibration and that caller-selected SSH trust files could replace the operator root. Revision 0.5 adds expert-frozen episode partitions with co-clustering/count reliability gates and one protected OS-canonical, offline-only trust configuration used by every probe/record/guard/recovery path. The earlier SHA remains rejected evidence, not an approval.

A third exact-file review found that a test resolver parameter on a packaged Python API could still bypass the canonical root. Revision 0.6 removes every resolver/trust/verifier argument from authoritative production APIs, confines test injection to non-runtime pure/test modules, and requires absolute `shell=False` OpenSSH verification under a sanitized environment. That earlier SHA is likewise rejected.

Mutations applied from those reviews:

- expanded the promotion corpus to at least 48 sealed tasks and made the task the statistical unit;
- added powered paired sandbox execution on a preregistered 24–48 task subset;
- defined a profile-aware `quality-lint` / contract-strict / package-strict / ready-to-dispatch matrix without silently changing legacy semantics;
- added typed command execution, source/research linkage, and undeclared-risk checks;
- tightened prompt growth, judge placement, cost, confidence, and removal rules;
- added execution lift as a promotion requirement, not merely preference-score improvement.
- added Gate B2-00 with a neutral main-vs-hardening harness, per-cluster disposition, complexity/performance evidence, and an explicit `adopt_whole|adopt_curated|keep_separate|reject` decision, plus Gate B2-01 to materialize and verify the exact selected/rollback foundation before quality work.

Review posture after mutation: **candidate for exact-SHA P0/P1 review and external discussion**, not approved for implementation. Reviewers must assess the file they receive, not rely on this ledger.

## 21. Final review state

This document proposes the quality authority and delivery plan. It does not claim that the architecture already improves SuperGoal.

The first honest foundation decision is the B2 branch-value audit. The first honest proof of candidate improvement is the frozen-baseline comparison report. The first honest claim of a quality leap is the hidden-holdout plus sandbox-execution and live-veto promotion verdict. Everything before those gates is a hypothesis under test.
