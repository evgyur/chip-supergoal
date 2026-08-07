# Runtime preflight for executable SuperGoal contracts

Use this reference when a generated package contains remote shell commands, isolated worktrees, private snapshots, mutable state, or paired evaluators. It records executor-side checks that must be proven **before dispatch**, not discovered phase-by-phase.

## Exact-command preflight

For every mandatory command, test the exact tuple:

- host and SSH identity;
- effective user after `sudo -u`;
- cwd and path permissions, including every parent directory;
- executable path and ignored runtime dependencies;
- expected exit code and expected stdout shape;
- whether the command still works after it creates a `0700` directory or root-owned artifact.

Do not validate a privileged setup command and assume its following unprivileged `test`, `stat`, `git`, or Python step can traverse the resulting paths. If evidence includes a root-owned `0600` file, keep permissions strict and run only the hash/stat verifier through a narrowly scoped privileged read; never weaken the live artifact merely to satisfy a verifier.

## Worktree runtime dependencies

A git worktree contains tracked files, not ignored runtime state. Before emitting commands such as `venv/bin/python` from a candidate worktree, prove one of these explicit contracts:

1. provision an isolated candidate venv;
2. use an absolute, read-only shared runtime path and forbid dependency mutation;
3. create a documented ignored symlink and add a non-directory ignore rule (`/venv`, not only `/venv/`, because a symlink does not match the trailing-slash directory rule).

Also ignore raw execution evidence explicitly, for example `/.supergoal-evidence/`, while selectively unignoring any reviewed redacted fixture that must be versioned.

## Sealed package mutation during execution

When runtime evidence proves a generated command wrong:

1. patch the source contract, not only rendered markdown;
2. increment the contract revision;
3. compile into a fresh package root;
4. run strict validation before swap;
5. preserve mutable `STATE.md` and `out/` receipts deliberately;
6. record that earlier delivery receipts describe the pre-mutation review pack and that phase receipts are authoritative for execution mutations.

Never use broad string replacement for command repairs. It can create duplicate verbs, self-rewrite paths, or alter unrelated phase text.

`STATE.md` and evidence receipts are mutable execution artifacts. The package manifest/validator must either exclude them from immutable fingerprints or define a sanctioned mutable-files policy; otherwise ordinary phase progress creates false package drift.

## Source refresh and pinned hashes

If execution refreshes a canonical corpus, export, schema, or dependency lock:

- write atomically and retain a private rollback copy;
- recompute row/count/date-range facts;
- replace every pinned source hash in the source contract;
- recompile and validate before running downstream criteria;
- keep raw private data same-host and emit only redacted ID/hash receipts.

A final audit must use the refreshed hash, not the planning-time hash.

## Script importability under multiple loaders

Evaluation CLIs are often executed both as files (`python evals/run.py`) and through test loaders (`importlib.util.spec_from_file_location`). The second path can leave `__package__` empty and omit the repository root from `sys.path`, so sibling imports that pass in direct CLI smoke tests can still break full discovery.

When a developer-only runner imports harness modules:

1. derive the repository root from `Path(__file__).resolve()` before harness imports;
2. add that root to `sys.path` only when absent, then import through one canonical package path;
3. test direct CLI execution, normal module import, and any existing `spec_from_file_location` loader;
4. rerun full test discovery after adding imports to a dynamically loaded script — focused new tests alone do not cover the loader contract.

Do not solve this by moving evaluator/provider dependencies into the public runtime package. Keep the loader fix inside the developer-only evaluation boundary.

## Paired evaluator integrity

For agent/bot parity datasets:

- sample the same request episodes for both systems;
- balance one-sided direct-response examples across systems instead of selecting whichever bot has more replies;
- keep no-answer episodes and manually review a stratified subset;
- resolve reply chains back through bot replies to the human root request;
- preserve known incident message IDs separately from response IDs when an incident is a human complaint or follow-up;
- store message IDs, text hashes, labels, atomic predicates, and evidence requirements — never raw private payloads in the repository fixture;
- scan false policy matches and forwarded/non-request messages manually before freezing blocker controls.

Report conservative baseline methodology with the score. A numerically precise but sampling-biased baseline is not valid evidence.

## Concurrent live drift

A long execution may overlap legitimate edits outside its candidate scope. If a baseline aggregate drifts:

1. identify changed paths/hashes without exposing contents;
2. prove whether the current phase touched them;
3. preserve unrelated work and record it as concurrent external drift;
4. continue verifying the protected live-code paths independently;
5. never roll back unrelated concurrent changes merely to restore an aggregate tree hash.
