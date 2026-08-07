# Selective handoff ports across divergent Git histories

Use when a reviewed handoff branch contains useful security/reliability commits but its parent includes live-drift replay, rejected product changes, or a different repository snapshot.

## Core rule

Do not cherry-pick a commit merely because its own `--stat` looks narrow. Three-way replay against a divergent parent can stage unrelated deletions or resurrect live-only files.

## Safe sequence

1. Freeze the canonical base SHA and create an isolated candidate branch/worktree.
2. Inspect both:
   - `git diff <commit>^ <commit> --stat`
   - `git diff --name-status <canonical-base>..<handoff-tip>`
3. For each accepted slice, prefer file-scoped patches:
   - `git diff <commit>^ <commit> -- path/to/file | git apply --3way`
4. After **every** apply or conflict resolution, before staging/continuing:
   - `git status --short`
   - inspect all `D`, `UD`, `DU`, `UU`, and unexpected paths
   - `git diff --stat HEAD`
   - search for conflict markers
   - compile touched files
5. Never run `git cherry-pick --continue` until the staged fileset exactly matches the accepted scope. A resolved conflict is not proof that unrelated index changes are absent.
6. If a replay stages broad deletions, abort/reset immediately to the last verified commit. Do not repair the mass deletion in place.
7. Preserve canonical behavior when the handoff patch contains both security changes and live-only product behavior. Take the sanitization/atomicity/fail-closed hunk; reject unrelated handlers, routes, files, and UX.
8. Port tests selectively too. Tests copied from a live-drift branch must not require files or functions absent from canonical main. Keep the security invariant, adapt the fixture inventory to canonical surfaces, and document excluded live-only fixtures.

## Verification

- Candidate scope verifier includes tracked and untracked files.
- Baseline-aware comparator proves no new deterministic failures when canonical main is already red.
- Added security tests cover the invariant directly: redaction, atomic writes, fail-closed reads, lease ambiguity, and compatibility overlap.
- `git diff --check <base>`, compile, focused tests, and full/baseline differential all pass before commit.

## Pitfalls

- `git cherry-pick --continue` can commit hundreds of unrelated deletions if the index is not inspected.
- `git diff --stat <commit>^ <commit>` describes the source commit, not the final three-way index.
- Copying the handoff's final test file wholesale can import assumptions from rejected live drift.
- A full-suite red baseline should produce a failure-aware gate, not unrelated test rewrites or cosmetic churn.
