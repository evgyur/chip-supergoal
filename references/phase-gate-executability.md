# Phase-gate executability preflight

Use this before launching or advancing a compiled multi-phase execution package.

## Structural gate checks

For every mandatory command in every phase:

1. Parse referenced paths and verify each test/script/file exists in the execution baseline.
2. Run `--help`, collection-only, or an equivalent no-side-effect probe where possible.
3. Verify the command can run from the package's declared working directory with its declared environment.
4. Reject plans containing placeholder test paths. Do not create a meaningless compatibility test merely to satisfy a typo; either correct the immutable package before launch or add a real focused test that covers the intended invariant.

## Mid-execution command resolution

Re-resolve every phase command against the **current exact worktree** immediately before using it. Package validation proves syntax and package shape; it does not prove a referenced repo test still exists after baseline changes.

If a mandatory path is missing after launch:

1. stop that command only—do not mark the criterion passed and do not silently skip the gate;
2. search the exact worktree for the real test/script that exercises the same invariant;
3. record a `PHASE_COMMAND_CORRECTION` in mutable runtime evidence with missing path, replacement command, and coverage mapping;
4. run the replacement plus any broader aggregate gate needed to prevent a weaker substitute;
5. treat the package typo as a planner defect to fix in the next compiled package, while leaving sealed package artifacts unchanged during execution.

A missing path is not a reason to fabricate a compatibility file whose only purpose is to make the command green. The replacement must test the intended behavior, not the filename.

## Baseline-red mandatory commands

Before sealing a phase, execute each broad mandatory command against both the clean baseline and the intended candidate scope.

- A command already failing on the clean baseline is not a valid unconditional acceptance gate. Do not discover this only after `/goal` launch.
- Do not repair unrelated baseline lint/test debt merely to make a recovery or feature phase green.
- Replace the command in the contract before compilation with an executable boundary: record the exact baseline failure/count, run the gate over every candidate-changed file or affected subsystem, and keep a later aggregate gate only where the roadmap explicitly owns the baseline debt.
- The candidate-scoped command must derive its files from Git ground truth (`git diff --name-only --diff-filter=ACMRT <baseline>`) rather than a hand-maintained allowlist.
- Record both results in phase evidence: `baseline_exit/findings` and `candidate_exit/findings`. A candidate PASS does not rewrite the baseline result; it proves no new violation in the owned slice.
- After launch, if an immutable package still contains a newly discovered baseline-red command, record `PHASE_COMMAND_CORRECTION` in mutable runtime state, preserve the baseline reproduction, run the candidate-delta replacement, and treat the planner defect as a required skill/package correction.

## Exact-review ordering and hash churn

Do not dispatch the final independent reviewer immediately after the first green focused suite. First execute a no-side-effect preflight of **every later safe-lane mandatory command** that can still mutate the candidate: broad Ruff/lint scope, compileall, full/zero-skip suites, release build/smoke, privacy scan, artifact hashing, and candidate-only secret/bytecode probes.

1. Run later-phase commands before declaring a review subject, even when phase state cannot advance yet.
2. Resolve baseline-red or command-interface defects before review; every code/test/gate fix invalidates prior exact-tree verdicts.
3. Freeze the tree only after all safe-lane commands are executable and green, then compute one binary-diff SHA and artifact-tree SHA.
4. Dispatch narrow reviewers against that exact SHA. A verdict on an older SHA remains useful only for byte-identical file slices; it cannot close the exact-candidate gate.
5. After reviewer-requested mutations, rerun affected focused gates, aggregate gates, artifact build, hashes, and review. Never average verdicts from several stale hashes into `0 P0 / 0 P1`.

This ordering avoids repeated reviewer churn where privacy/lint/build defects are discovered only after an otherwise expensive review has started.

## RED/GREEN phase ordering

A phase gate must be satisfiable at the phase where it appears.

- If P01 introduces RED tests for defects implemented in P02–P04, a P02 full-suite gate will remain red because of future-phase tests.
- Prefer one of these shapes:
  - introduce each RED test in the phase that immediately implements it;
  - keep P01 characterization evidence outside the collected suite until its implementation phase;
  - or make early gates target only the completed phase's test subset while reserving the full suite for the first phase where all registered REDs are expected green.
- Never mark a phase PASS by silently excluding a test that its own acceptance criteria require.

## Shared PostgreSQL hygiene

Before accepting a full-suite database gate:

- Identify append-only ledgers and migrations whose downgrade intentionally blocks when rows exist.
- Synthetic ledger rows must live inside an explicit transaction that always rolls back, including assertion failures.
- Allow repository read methods to accept the caller's test connection when visibility of uncommitted rows is required.
- For unrelated burst/load probes, use a synthetic state wrapper rather than poisoning an immutable production ledger.
- Run the zero-skip database gate from a fresh database after ledger/fence tests.

## Evidence discipline

A passing fixture receipt proves implementation behavior, not current production state. Label it `fixture_scope=true`. Keep separate live read-only evidence for the real mismatch, retention anchor, queue depth, provider health, and frontier. Do not average fixture and live evidence into a single stronger claim.
