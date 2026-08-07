# Deliverable and producer closure for executable SuperGoal plans

Use this gate when a plan contains generated code, scripts, fixtures, reports, live evaluations, or production activation.

## Core invariant

A command may consume a path only when that path:

1. already exists in the planner baseline; or
2. is declared as a deliverable in the same or an earlier phase.

Treat every consume-before-produce edge as P0. Check scripts, tests, fixtures, manifests, reports, approval receipts, candidate SHAs, and deployment inputs, not only source files.

## Rendered package closure

`CONTRACT.json` is not enough if `/goal` reads only rendered Markdown.

- Render each phase's deliverables into both `ROADMAP.md` and `phases/phase-XX.md`.
- Make `LAUNCH_GOAL.md` require reading `CONTRACT.json` in addition to protocol, roadmap, state, and loop design.
- Strict validation must prove that rendered phase files contain deliverable IDs and paths.
- The complete archive must remain manifest-exact after extraction.

## Semantic prelaunch audit

Before delivery, machine-check:

- shell syntax for every command;
- unique work, deliverable, criterion, and command IDs;
- one verifier command per criterion with no orphan command;
- baseline-or-producer closure for every referenced script/test/fixture/report;
- no phase consumes a report or manifest produced later;
- approval files are trusted external inputs, never package deliverables;
- each live or production command requires an exact, scoped, expiring, one-shot approval receipt;
- product source deliverables exist, not only reports and planning prose.

Schema validation without this semantic audit is insufficient.

## Immutable-candidate order

Correct order:

1. local implementation and tests;
2. offline evaluation;
3. freeze exact commit/config/prompt/grader hashes;
4. build candidate manifest and private review branch;
5. request approval bound to that manifest;
6. run billable live evaluation against that exact candidate;
7. request a separate production approval;
8. activate bounded canary with rollback manifest.

Running a live benchmark before candidate freeze makes the evidence non-reproducible and is P0.

For pre-production live evaluation, prefer an isolated loopback candidate process from the frozen worktree. Record PID, port, health, commit SHA, config hash, and teardown receipt. Do not invent a route name that does not correspond to a verifiable process.

## Dirty-tree and worktree pitfall

A Git worktree does not inherit ignored `.venv` directories. Commands such as `candidate/.venv/bin/python` are invalid unless the phase explicitly creates that environment. Either:

- use a known dependency environment by absolute path while ensuring the candidate `src` is first on `sys.path`; or
- create and verify a dedicated environment inside the candidate worktree.

Capture existing dirty state before planning, isolate execution in a sibling worktree, and never absorb unrelated changes into the candidate.

## Effect boundaries

Keep these phases separate:

- offline replay and grading;
- immutable candidate freeze;
- billable live evaluation;
- production activation.

A failed live iteration needs a fresh one-shot approval receipt. Do not reuse a consumed approval merely because the spend cap is unchanged.

## Review checklist

- [ ] Every command input has a baseline or same/earlier producer.
- [ ] Deliverables are visible in rendered execution docs.
- [ ] Live evaluation is bound to a frozen candidate.
- [ ] Approval authenticity has a negative synthetic-receipt test.
- [ ] Candidate process teardown is proved.
- [ ] Current production/default route remains unchanged until its own approval gate.
