# Executable contract interface and live-path revision discipline

Use for compiled SuperGoals whose mandatory commands invoke evolving local scripts or bind production/install/package paths.

## Why structural validation is insufficient

A contract can pass schema/package validation while its exact command is impossible because:

- the script CLI requires different flags;
- a receipt schema changed (`head` vs `baseline`, snake_case vs camelCase);
- the contract points to a predecessor package;
- the install root is plausible but not the live root;
- the verifier proves an older semantic model instead of the phase criterion.

Independent review that compares only revision diffs can miss this. Review must cover the **contract-to-executable ABI** and live read-only path facts.

## Pre-seal command ABI gate

For every mandatory command, before launch or before entering its phase:

1. Resolve the exact script from the exact candidate/release that will execute it.
2. Inspect its current `--help`/parser and input schemas.
3. Run the exact command in its allowed safe mode against representative artifacts. Shell syntax or a similar substitute command is not evidence.
4. Verify every named output is produced at the contract path and matches the downstream consumer schema.
5. Trace every input/output edge across phases: receipt producer → seal → approval binding → live runner → final auditor.
6. Fail closed on unknown flags, missing outputs, permissive aliases that weaken assertions, or receipts not bound to candidate HEAD.
7. Compile the package and assert that every declared deliverable is visible in both `ROADMAP.md` and the corresponding `phases/phase-*.md`; a deliverable that exists only in `CONTRACT.json` is invisible to the executor and therefore not closed.
8. Assert that `LAUNCH_GOAL.md` explicitly tells the executor to read `CONTRACT.json` in addition to protocol, roadmap, loop, state, and phase files.

Compatibility aliases are acceptable only when they preserve the stronger contract semantics. Do not make an impossible command “green” by silently ignoring required flags or relabeling unrelated tests.

## Git source-lock gate

Before delivering a package whose phases bind an exact Git baseline:

1. Prove the object exists as a commit with `git cat-file -e "$BASE^{commit}"`.
2. Prove its intended lineage with `git merge-base --is-ancestor "$BASE" <canonical-ref>` when ancestry is part of the contract.
3. Prove durability. Prefer a commit reachable from the canonical remote branch/tag. If the baseline exists only in a transient local object database, first push a private immutable ref or create another declared durable source artifact; do not seal an orphan SHA that garbage collection or another checkout cannot recover.
4. Re-read `origin` after fetch and bind the exact remote SHA, protected dirty-tree status hash, and binary diff hash into the source receipt. A SHA copied from a stale terminal capture or planner self-report is not evidence.
5. Run the exact P01 source-lock preflight before review delivery. Package/schema validation cannot prove that a Git object still exists.

If launch later proves the sealed baseline unavailable:

1. Stop before creating the candidate worktree or changing product files.
2. Try bounded recovery from the local object database, reflogs, unreachable-object scan, canonical remote refs, and exact-SHA fetch. Record the commands and redacted outcome.
3. Never substitute the current HEAD inside the already launched package. That invalidates source identity, commands, approval bindings, rollback manifests, and final audit semantics.
4. Mark the old runtime `BLOCKED` with the source-lock evidence.
5. Create a fresh sibling package with a new goal ID, package/worktree/branch identities, incremented contract revision, current durable canonical SHA, and a source-revision incident record.
6. Re-run strict contract/package/loop/phase validation, mandatory-command shell/producer closure, archive verification, and review delivery. Require Chip to launch the revised `LAUNCH_GOAL.md`; do not start a nested `/goal` or silently transfer the old standing goal.

Treat this as a P0 contract-to-executable defect, not an ordinary phase retry. The implementation objective may be unchanged, but the execution authority has changed.

## Live path gate

Before sealing any production-adjacent phase, obtain read-only live facts:

- real install root and `current` symlink target;
- immutable release root;
- active package root and exact `CONTRACT.json` path;
- implementation checkout root;
- service/process cwd or executable path where relevant.

Generate commands from named path variables, then audit all command strings for stale predecessor roots. A mismatch in production install root, mutable package root, manifest path, or final-audit contract path is P0/P1 depending on reachability; do not compensate inside the implementation while leaving the signed contract wrong.

## Revision after launch

If a control-plane/live path defect is found after package state has advanced:

1. Stop before seal/live mutation.
2. Create a new contract revision and a fresh compiled sibling package.
3. Limit and hash the revision diff.
4. Run independent semantic review of both the diff and executable/path compatibility.
5. Restart the new package through the legal state ladder; do not mutate the old package in place.
6. Keep old evidence as historical only. Record fresh evidence under the current contract revision.

## Candidate amendment invalidation

Any `commit --amend` changes candidate identity. Therefore all HEAD-bound artifacts become stale:

- zero-skip/JUnit receipts;
- failure-matrix receipts;
- dirty-patch accounting;
- remote branch proof;
- staged release/release ID/artifact hash;
- manifest, rollback package, independent review, approval, and final audit.

After the **last** amendment, rerun the exact candidate gates, rebuild/reseal, re-push/read back remote SHA, and regenerate evidence. Earlier green output can guide debugging but cannot close the revised candidate.

## Review checklist

- [ ] Exact mandatory commands execute with current CLIs.
- [ ] Receipt producer and consumer schemas agree.
- [ ] No stale package/install/contract root remains in any phase.
- [ ] Candidate HEAD is identical across test, remote, staged release, review, manifest, rollback, and approval inputs.
- [ ] Production mutation still waits behind the declared fresh approval.
- [ ] Final audit is read-only and verifies expected release/artifact identity without replaying activation.
