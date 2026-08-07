# Release-candidate zero-skip and integrity gates

Use this reference when a SuperGoal phase must produce an exact, reviewable release candidate without deploying it.

## 1. Mandatory-command reality gate

Before marking a phase started, execute every mandatory command exactly as written from the declared repo/cwd/user.

If a required verification script does not exist, that is not an environment hiccup and not permission to skip the criterion. Choose one:

1. implement the missing reusable gate with a RED → GREEN test;
2. mutate the phase contract if the command was invalid or unnecessary;
3. block the phase with the missing executable named explicitly.

Do not replace an absent zero-skip/integrity gate with a nearby test suite and claim equivalent evidence.

## 2. Disposable PostgreSQL zero-skip runner

A release gate that claims PostgreSQL compatibility should:

- be executable in the exact form embedded in the phase (`./runner.sh` requires the executable bit; `bash runner.sh` is a different contract);
- start the required major version in a disposable local container;
- use a random container name, database credentials, and host port;
- treat generic container health / `pg_isready` as insufficient during first initialization: PostgreSQL may accept connections from a temporary init server before the requested database exists. Poll an authenticated `SELECT 1` against the exact target database, then verify the server major version before pytest;
- export the project's ordinary PostgreSQL DSN form, letting application code normalize driver syntax;
- run the full collected suite with JUnit output;
- parse JUnit and fail unless `tests > 0`, `skipped = 0`, `failures = 0`, and `errors = 0`;
- retain a redacted summary/JUnit artifact while removing the container through an `EXIT` trap;
- emit explicit no-live-action flags.

Test the runner itself: shell syntax, help path, disposable cleanup marker, JUnit enforcement markers, and evidence-directory hygiene.

## 3. Exact-candidate invalidation rule

Critical evidence binds to one immutable commit. Any later commit—even a test-only, smoke-only, or `.gitignore` change—invalidates exact-candidate proof.

After the final code-affecting commit:

1. prove the worktree is clean;
2. rerun the zero-skip suite;
3. rebuild the release with `repo_sha` equal to the current short HEAD and `dirty=false`;
4. rerun smoke and installer dry-run;
5. regenerate the evidence receipt;
6. push privately and compare `git ls-remote` to the full local HEAD.

Never reuse a green run from the immediately preceding commit as exact release evidence.

## 4. Evidence paths without dirtying the candidate

Release/JUnit evidence may live under a repo-local ignored directory such as `.supergoal-artifacts/`, while canonical receipts live in the SuperGoal `out/phase-N/` tree.

Add the evidence directory to `.gitignore` and test it with `git check-ignore`. A phase that requires a clean candidate must not create visible untracked artifacts as a side effect of its own mandatory commands.

## 5. Bytecode and integrity boundary

For a deployable release artifact, do not merely exclude `.pyc`, `.pyo`, or `__pycache__` from the content digest. Reject their presence before smoke/install integrity validation with one stable error marker, for example `release_executable_bytecode_forbidden`.

This is distinct from a generated SuperGoal runtime package whose manifest-drift policy may intentionally ignore transient interpreter caches.

Required tamper probes on disposable copies:

- remove the approved manifest directory → smoke rejects;
- remove the recovery/operator executable → smoke rejects;
- inject `.pyc` under a runtime package → smoke and installer both reject with the stable marker.

## 6. Immutability across verification

Compute a full-tree hash before smoke and installer dry-run, then compute it again afterward. Require byte-for-byte equality. The manifest's internal artifact digest alone does not prove that verification commands did not mutate the release.

The receipt should bind:

- full candidate SHA and release ID;
- release `repo_sha`, `dirty`, and artifact digest;
- before/after full-tree hashes;
- smoke and installer exit codes;
- each tamper-probe exit code and expected marker;
- zero-skip summary;
- live-action flags, all false.

## 7. Secret-scan honesty

Run a candidate-range repository scanner and a full release-artifact scanner. Do not silently relabel scanner hits as clean.

For false positives/placeholders:

- classify them deterministically by rule and path class;
- retain only redacted/path-hashed metadata in public evidence;
- distinguish documented placeholders (`REPLACE_ME`, `<database-password>`, `unused`) and vendor/CSS identifiers from real credentials;
- keep `real findings = 0` as a separate assertion.

A scanner with findings is not green until classification is explicit and reproducible.

## 8. Review and progression

Independent reject-first review checks the exact candidate, release, zero-skip artifact, tamper probes, secret classification, clean tree, and remote SHA binding.

Provisional work on a downstream phase may collect safe local evidence, but formal progression stays blocked until all dependency review receipts pass. No local release artifact authorizes deployment, service changes, signing, orders, fund movement, or risk widening.
