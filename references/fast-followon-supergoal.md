# Fast follow-on SuperGoal from a diverged execution

Use when implementation has advanced beyond the predecessor package and Chip asks for a **new SuperGoal**, especially after repeated slow/status-only continuation.

## Operator sequence

1. **Retire competing continuation first**
   - List the old continuation job before removing or pausing it; never guess a scheduler ID.
   - Check for GoalManager, delegated, terminal, cron, or CLI writers on the source checkout.
   - Keep exactly one writer. Planning may inspect the source, but must not mutate numbered implementation phases.

2. **Bind the real boundary**
   - Record implementation root, branch, exact `HEAD`, `git status`, and SHA-256 of the complete dirty binary diff.
   - Treat the predecessor package and runtime state as historical handoff evidence, not executable authority.
   - Create a sibling package with a new goal ID, phase 1 pending, and the real HEAD+patch hash in contract/source evidence.

3. **Compress only remaining work**
   - Remove already-proven discovery and completed phases instead of replaying them.
   - Prefer a short executable shape such as: engineering closure → exact candidate/approval packet → approved production activation/audit.
   - Preserve safety boundaries. Launch approval authorizes only the safe lane; production still needs its own exact expiry-last approval.

4. **Compile through the real interface**
   - Do not invent or assume a `run_supergoal.sh` wrapper. Inspect the installed skill's linked scripts and use `scripts/sgctl.py compile <contract> --out <package-root>` with the matching `PYTHONPATH=<skill-or-package>/lib`.
   - Compile into a fresh/nonexistent package root. If regeneration is required, remove only that exact generated root and recompile from the source contract.
   - Do not pass `<package-root>/CONTRACT.json` as the compiler source while also targeting `<package-root>`: the source-container guard must reject replacing an ancestor of its own input. For a sealed package regeneration, first copy the canonical contract bytes to an external temporary source, verify its hash, then compile that temp contract into the package root. Keep runtime `out/` outside the regeneration target or archive it first; never weaken the guard.
   - If the contract changed, advance `contract_revision` by exactly one. If only compiler/runtime assets changed and canonical contract bytes are identical, preserve the revision and let the sealed-package equality check authorize regeneration.

5. **Run semantic closure, not only structural validation**
   - Validate contract, package, loop, every phase, mandatory-command shell syntax, exactly one launch body, and pending `READY_TO_DISPATCH` state.
   - Search generated Markdown for predecessor SHA, obsolete phase IDs/counts, stale approval wording, and old package roots.
   - Trace every mandatory-command input to baseline, an earlier deliverable, or a same-phase materializer.
   - If a later phase invokes a script that does not exist yet, declare that script and its direct tests as an earlier phase deliverable. Likewise, declare every manifest/receipt consumed by a later phase as an explicit earlier deliverable.

6. **Deliver immediately; do not polish-loop**
   - Once contract/package/loop/phase validators are green and stale-predecessor searches are clean, freeze the planning subject. Do not spend additional turns rewording non-blocking narrative, investigating optional delivery mechanisms, or rerunning equivalent compiler mutations.
   - Dispatch `startup_pack_v4`: `THINKING.md`, `ROADMAP.md`, then `LAUNCH_GOAL.md` last. Do not attach package internals or bury the launch target in another progress report.
   - If Chip explicitly says the old continuation is stalling and asks for a new SuperGoal, optimize for the shortest validated remaining-work package. Report only package identity, validator result, retired-writer proof, production-effects count, and the launch action.

## Compiler determinism pitfall

Some compiler versions render the source object once, then validate against the canonicalized `CONTRACT.json`. Nested mapping insertion order can therefore produce immediate generated drift even after a fresh compile (observed with `loop.budget` rendered as a Python dict).

Until the compiler normalizes before its first render:

- prefer a scalar/string for human-rendered free-form fields such as `loop.budget`;
- after every compile, run `validate-package` immediately;
- when drift appears, render the canonical contract and compare expected vs actual rather than hand-editing generated Markdown;
- fix the source contract, delete only the generated package root, and recompile.

## Stop rule

A new follow-on package is ready only when it has no stale predecessor semantics, every phase is executable in order, validation is green, files are delivered, and the old writer cannot race the new executor.
