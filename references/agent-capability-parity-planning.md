# Agent capability-parity planning

Use this reference when a SuperGoal asks to make one bot, profile, or team agent “as capable as” another.

## Core invariant

Do not interpret parity as copying a prompt, model name, memory, or skill directory. Define parity as **verified task outcomes**:

1. recover the right context;
2. select authoritative sources and appropriate tools/skills;
3. execute only effects allowed for that actor and chat context;
4. verify the effect;
5. report a concise result with evidence or an honest blocker.

## Recon sequence

1. **Verify identity and runtime live.** Use service/process state and platform identity (`getMe` or equivalent). Bot display names and legacy directories are not sufficient.
2. **Locate the canonical profile and running tree.** Record git SHA, dirty/untracked state, config/SOUL hashes, model route, enabled toolsets, skills, narrow operation helpers, and gateway policy.
3. **Separate live runtime from legacy/helper systems.** A weak historical bot implementation may no longer be the component answering users.
4. **Audit real outcomes.** Build an episode inventory covering refusals, stale facts, context blindness, tool loops, false completion, excessive correction rounds, and successful controls.
5. **Map rescue work.** Identify tasks repeatedly handed to the stronger agent; these are direct capability requirements.

## Architecture rule: intelligence parity ≠ authority parity

A shared/team bot can match a private operator agent in reasoning and artifact quality without receiving identical privileges.

Use an enforceable matrix:

- **guest:** read-only reasoning and public research;
- **member:** research plus sandboxed artifact creation;
- **admin/operator:** isolated worktree/beta engineering and narrow deterministic operations;
- **high-risk effects:** production, payments, grants, mass/public sends, DNS, credentials and billing require scope-bound approval.

Prompt prose is not authorization. Enforce the matrix at tool dispatch, quick-command and operation-broker boundaries, with negative tests.

## Evaluation ladder

1. Create a redacted real-task corpus with message/event IDs and three outcomes: success, honest policy/technical blocker, failure.
2. Run offline replay.
3. Run shadow mode with sends and mutations disabled.
4. Use blinded pairwise review only for subjective quality; deterministic tests remain the judge for actions and policy.
5. Run an explicitly approved, actor-limited canary.
6. Expand only after policy, task-outcome, false-completion and rollback gates pass.

Recommended initial gates:

- policy correctness ≥ 90%;
- successful task or valid blocker ≥ 85%;
- zero unauthorized effects;
- zero secret/private-data leaks;
- zero completion claims without verifier-backed evidence.

## Completion contract

For action tasks, bind “done/fixed/sent/created” language to a result object containing requested effect, actor, policy decision, tool/action, target, verifier, evidence reference, outcome and rollback point. Ordinary conversational answers do not need this ceremony.

## SuperGoal phase shape

A durable parity roadmap usually needs:

1. baseline lock and known-red ledger;
2. real-task evaluator;
3. actor-aware capability broker;
4. context/source-of-truth router;
5. runtime/model/tool-call reliability;
6. research and artifact execution;
7. domain engineering/operations lanes;
8. curated skill routing and quality rubrics;
9. evidence/observability;
10. replay, shadow and approved canary;
11. rollout and rollback handoff;
12. final privacy/security/regression audit.

Derive the actual phase count from dependencies; do not force this shape when the system is smaller.

## Pitfalls

- Rebuilding a legacy bot before checking whether the live bot already runs on the target agent framework.
- Treating more skills or a stronger model as proof of parity.
- Giving a shared bot raw shell access to remove visible refusals.
- Measuring tool-call volume instead of verified progress.
- Calling policy refusals model failures; valid blockers must be labelled separately.
- Hand-editing compiler-sealed SuperGoal output. Put semantics in `CONTRACT.json`, recompile, then validate the strict package.
