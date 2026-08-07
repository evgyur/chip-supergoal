# Compiler conformance and semantic closure

Use this when a SuperGoal package touches private data, production files, schedulers, messaging, migration, or rollback-sensitive state.

## Why this gate exists

A package can pass its bundled structural validator while still being unsafe or non-executable. The usual causes are compiler/template drift, split runtime authority, effectful commands replayed during final audit, paths resolved from the wrong root, weak approval authority, or an incomplete crash-recovery path.

Treat `validate-package --strict` as necessary structural evidence, never as semantic proof.

## 1. Verify the actual compiler, not the surrounding documentation

Before compiling a real mission, probe the exact `sgctl.py` that will be sealed into the package.

It must expose the v3 runtime/evidence operations used by the protocol, including:

- `state-show`, `state-transition`, `state-recover`
- `record-evidence`
- `audit`, `finalize`, `validate-terminal`
- strict package, phase, and loop validators

Compile a disposable probe contract and inspect the emitted package:

- `runtime/STATE.json` exists and is the sole runtime authority.
- `STATE.md` is projection-only.
- `CONTRACT.json` is execution-intent authority.
- `ROADMAP.md` and every phase view render work items, deliverables, criteria, commands, risks, and RPD policy losslessly.
- `PROTOCOL.md` performs evidence-based audit; it does not replay the union of phase commands.
- effectful activation/recovery commands are forbidden from final-audit replay.

If the installed skill prose and compiler output disagree, stop. Do not dispatch the package and do not hand-edit generated views. Select a verified v3 compiler source, record its locator/version in `source_set`, compile afresh, and run strict validation again.

## 2. Bind package root and implementation roots explicitly

Standard `/goal` executes from the sealed package root. A mission may build code in a parent workspace, but every mandatory command and deliverable must resolve unambiguously.

For multi-root missions, declare absolute typed roots for:

- sealed package
- implementation workspace
- candidate tree
- mission tools
- evidence and reports
- private staging and canonical private storage
- live install targets

Reject relative `tools/`, `candidate/`, `evidence/`, `reports/`, or `work/` paths when they would resolve differently from the package cwd.

## 3. Run an independent semantic closure loop

After structural validation, have an independent Principal/Security reviewer read the exact sealed package. The reviewer must treat validator-green as structural only and trace:

`command -> artifact -> independent verifier -> blocking criterion -> final audit`

At minimum, review:

- package/workspace path binding
- declared product artifacts and the tests that exercise them
- criterion-to-command semantic binding: never attach commands to criteria by list index; map each criterion to the command that actually proves its statement, then machine-check that every blocking criterion references an existing command
- command assertion fidelity: a test-suite command cannot prove that a source-lock receipt exists unless it actually validates that receipt; one command may prove several criteria only when its executable assertions cover every one
- approval authenticity and time-of-check/time-of-use ordering
- current-state drift guards immediately before effects
- dirty-tree ancestry and unrelated-dirty preservation
- exact scheduler update semantics, including zero create/remove actions
- at-most-once messaging/canary behavior
- process-death, host-restart, resume, and rollback behavior
- final-audit non-replay and deliverable authority
- raw-private-data egress and delegation boundaries

Iterate contract -> compile -> validate -> independent review until the reviewer returns `PASS` with no open P0/P1. Keep earlier negative reviews as evidence of what changed.

If the only post-PASS change is review metadata, compare the reviewed and final contracts after removing `contract_revision` and review metadata. The remaining execution contracts must be identical before carrying the PASS forward.

## 4. Production/private activation pattern

Use two stages:

1. **Build/evaluate/manifest:** no live mutation. Produce exact before/base/after hashes, inverse operations, rollback drill, private-data boundary, and unsigned approval request.
2. **Activation:** require fresh external approval bound to the exact manifest hash, target, actor, reply relation, and expiry.

For activation:

- A workspace approval JSON is only a pointer/projection, never authority.
- Re-fetch and revalidate external approval inside the activator immediately before effects.
- Re-read controlled `before_hash` values and unrelated dirty-state digests before lock/approval consumption.
- Acquire an atomic one-shot lock and persist an external consumption receipt before live effects.
- Record append-only transaction stages outside the ordinary workspace.
- Declare and test every crash boundary.
- On phase entry/resume, reconcile any incomplete transaction before normal verification or a new activation attempt.
- Recovery must deterministically no-op completed stages, resume only safe incomplete stages, or restore exact prestate.
- A phase cannot complete until the transaction is terminal: `verified` or `rolled_back`.

Final audit uses only retained evidence plus fresh read-only postconditions. It must never resend, reapprove, re-edit cron, reapply files, or rerun a canary.

## 5. Independence rules

Do not let one broad helper become a second orchestrator.

Prefer three narrow surfaces:

- an evidence/recon CLI with no live mutation or completion authority
- a manifest-only transactional activator
- an independent read-only postcondition verifier that does not import activator/writer code

Every safety test module must be a declared deliverable and invoked by a mandatory command. A promised test file that no command executes is not evidence.

## Common failure modes

- Trusting skill docs instead of probing the actual compiler.
- Structural validator green treated as launch approval.
- Split state between legacy Markdown and `runtime/STATE.json`.
- Final audit replays effectful phase commands.
- Commands run from package root but target relative paths in a parent workspace.
- Manifest author validates its own output with no independent verifier.
- Approval is checked only before activation, not inside it.
- Crash after partial mutation leaves a lock that blocks both resume and rollback.
- Scheduler points at a collector artifact that no phase creates or smoke-tests.
- Dirty live files are replaced from a clean or stale candidate baseline.

## Review completion checklist

- [ ] Exact compiler conformance probe passed.
- [ ] Strict package, loop, and every phase validation passed.
- [ ] Source and compiled `CONTRACT.json` both pass quality lint after profile/default resolution.
- [ ] Every blocking criterion is bound to an existing command whose executable assertions actually prove that criterion; no index-based verifier mapping remains.
- [ ] All mandatory command strings pass shell syntax validation.
- [ ] Absolute root/path contract is executable from package cwd.
- [ ] Every product/test artifact is declared and exercised.
- [ ] Independent semantic reviewer returned PASS with no P0/P1.
- [ ] Live approval is external, exact, fresh, and revalidated in-transaction.
- [ ] Crash/restart recovery is executable and mandatory.
- [ ] Final audit is read-only and forbids effectful replay.
- [ ] Review-metadata-only closure preserves the reviewed execution contract exactly.
