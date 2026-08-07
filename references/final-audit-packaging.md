# Final audit and completion packaging

Use this when the executor must prove exact final refs, rollback safety, CI parity, and a deterministic artifact bundle before printing completion markers.

## Completion order

1. Bind final source refs and verify each local HEAD equals its pushed remote head.
2. Run fresh-install local gates on those exact refs.
3. Verify remote CI on the same head SHA. Do not accept a green fast/advisory job while the authoritative job is pending or failed.
4. Run independent read-only review of the final diff. Fix findings, then repeat affected gates and review-sensitive checks.
5. Prove rollback in an isolated worktree.
6. Run phase validation using the exact command interface written in the phase spec.
7. Finalize `STATE.md` and `final-audit.md` markers.
8. Build the non-self-referential bundle and sidecar manifest.
9. Run a machine-readable final checker, then re-read STATE/audit/manifest and verify the checksum with `sha256sum`.
10. Only then print `Goal complete: yes`, `AUDIT_COMPLETE`, and `SUPERGOAL_RUN_COMPLETE` in the same response.

If any late mutation changes source HEAD, evidence JSON, validator/checker code, STATE, or a bundled file, regenerate all evidence that binds to it and rebuild the bundle.

## Exact-ref and CI proof

Record:

- base SHA and final SHA for every repository;
- branch names and PR URLs;
- `git status --porcelain` clean result;
- `git ls-remote` equality for each pushed branch;
- CI head SHA plus every required job's status/conclusion;
- local gate exit codes, test counts, wall times, and peak RSS.

A CI-only failure is evidence, not noise. Reproduce the runner difference explicitly (timezone, platform, clean install, environment), add a regression, and rerun the full final lane on the new final SHA.

## Rollback proof and commit boundaries

Textual rollback instructions are insufficient. In a detached temporary worktree:

1. Revert only the rollout-specific commits with `--no-commit`.
2. Run clean install plus every authoritative gate.
3. Confirm baseline repairs and unrelated correctness fixes remain.
4. Remove the worktree.

If rollback removes a dependency needed by baseline tests, the commit boundary is wrong. Rewrite/split commits so baseline repair and rollout-only dependencies are independently revertible, push with `--force-with-lease`, and rerun both final gates and rollback proof.

## Validator command compatibility

Generated phase specs may require either:

```bash
bash .supergoal/scripts/validate-phase.sh 06
bash .supergoal/scripts/validate-phase.sh .supergoal/phases/phase-06.md
```

The portable wrapper must support both a numeric phase ID and a path, resolve package-local files from its own root, work from an arbitrary caller cwd, and fail clearly when the phase file is absent. Test the exact mandatory command from the phase spec; validating only the underlying Python API can hide a broken wrapper.

## Non-self-referential deterministic bundle

If `final-audit.md` contains bundle hash/size and the bundle contains `final-audit.md`, the hash is unstable. Build a deterministic archive with sorted entries, fixed timestamps, stable permissions, and explicit exclusions:

- `.supergoal/final-audit.md`;
- `.supergoal/package-manifest.json`;
- `.supergoal/bundle/**`.

The sidecar manifest uses one stable schema:

```json
{
  "goal_id": "sg-...",
  "path": ".supergoal/bundle/sg-....zip",
  "sha256": "...",
  "bytes": 123,
  "entry_count": 42,
  "deterministic_timestamp": "1980-01-01T00:00:00Z",
  "excluded": [".supergoal/final-audit.md", ".supergoal/package-manifest.json", ".supergoal/bundle/**"]
}
```

Pack the final checker itself before hashing. If checker code or any bundled evidence changes, rebuild the archive and patch audit metadata again.

## Machine-evidence pitfalls

- Do not parse presentation-formatted `read_file` output into metrics JSON without stripping line-number prefixes such as `1|`. Prefer raw file reads inside the packaging script or normalize prefixes explicitly.
- Keep manifest/checker field names identical (`excluded` vs `excludes`, `path` vs `bundle`). Validate the schema before hashing.
- A final checker should verify markers, exact refs, remote equality, clean worktrees, gate exits/counts, CI conclusions, secret/churn scans, rollback evidence, manifest checksum, entry count, and self-reference exclusions.
- Run the checker again after the final manifest/hash patch. A checker failure means completion markers are provisional and must not be reported.

## Final reporting

Report PRs and final SHAs, local and remote gates, rollback result, residual risks, bundle path/hash, and the final checker status. State explicitly whether merge or deployment occurred. Attach the bundle; attach `final-audit.md` separately when requested because it is deliberately excluded from the archive.