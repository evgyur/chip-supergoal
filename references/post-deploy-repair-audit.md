# Post-deploy repair audit for production SuperGoal runs

Use this when a production SuperGoal has already deployed and the user reports a live gap, or when final audit follows a deploy phase.

## Trigger

- User says a public route does not open after deploy.
- User says a visible feature is missing even though local tests passed.
- Deploy phase included intentionally excluded untracked files or runtime env changes.
- Final audit is about to print `AUDIT_COMPLETE` after a production deploy.

## Required workflow

1. Treat the report as a production split-brain signal, not as a UX complaint.
2. Verify the public route through the real domain, not localhost or build output only.
3. Map three states before fixing:
   - git/source state: committed file exists and `HEAD == origin/<branch>`
   - deployed release state: public `/release.json` SHA matches the intended commit
   - runtime state: service env/config flags visible to the running app are set in both current release and shared persistent env when applicable
4. If a route exists locally but returns 404 in production, check whether it is untracked or excluded from the deploy commit before looking for router bugs.
5. If UI buttons/features are missing, inspect the injected public env in the live HTML and the runtime env on the host. A test that stubs env is not production proof.
6. Fix the canonical source first when a source file is missing, commit/push, deploy through the canonical deploy script, then verify public route markers.
7. If runtime env was changed manually to repair prod, persist it in the shared env/config used by future releases, not only the current release directory.
8. Record the post-deploy repair as bound evidence, transition authoritative state through the audit-remediation path, then rerun final audit. Do not hand-edit `STATE.md` or print `AUDIT_COMPLETE` from pre-repair evidence.

## Evidence to collect

- `git status --short --branch`, `git rev-parse HEAD`, and upstream match.
- Public `/release.json` release id + git SHA.
- Public `curl -L` route status and final URL for reported routes.
- Text/HTML markers proving the user-visible feature is present.
- Runtime service status and redacted env-flag presence.
- Report addendum path.

## Anti-patterns

- Saying “deployed” because the local build includes the route.
- Treating missing OAuth/social buttons as only a React render issue before checking public env flags.
- Leaving a live env repair only in the current release directory so the next deploy regresses it.
- Marking the SuperGoal complete before incorporating the user-reported live gap into the final audit.
