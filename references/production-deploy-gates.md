# Production deploy gates for Supergoal runs

Use this reference when a Supergoal phase deploys production code, especially when the repo has submodules, generated/untracked product files, or runtime services outside the main web app.

## Core lesson

A deploy phase is not just “run the deploy script after tests pass.” It must prove that the exact code intended for production is committed, reachable from the deploy ref, deployed, and running in every runtime that participates in the user-visible flow.

## Required pre-deploy gates

1. **Main repo status**
   - Capture `git status --short --branch` and `git rev-parse HEAD`.
   - Stage and commit required product files, including new tests/support modules.
   - Keep operational artifacts out of the production commit unless the plan explicitly says they ship.

2. **Submodule status and gitlink gate**
   - If a submodule has product changes, inspect it separately with `git -C <submodule> status --short --branch`.
   - Commit and push the submodule changes first.
   - Then update, stage, commit, and push the parent repo gitlink.
   - Do not deploy the parent until the deploy ref points at the new submodule commit.

3. **Canonical deploy path**
   - Deploy only from the committed production ref named in the phase spec.
   - Avoid runtime-only patches; they create split-brain between git, deploy scripts, and live services.

4. **Runtime symmetry gate**
   - Identify every runtime that must run the new behavior: web app, API, workers, bots, cron, helper services, containers, systemd units.
   - Verify source/ref, env symmetry, restart path, and active process/container for each one.
   - Restart or prove already-running updated code. “Web deployed” is not enough when a bot or worker produces/consumes the flow.

5. **Packaged-runtime and immutable-artifact gate**
   - Exercise tools from the built release layout, not only from the source checkout. Packaged imports may live under `backend/`, and runtime DSNs/drivers may differ from test defaults even when source tests pass.
   - Prevent smoke tests from mutating the candidate with bytecode/cache files: set `PYTHONDONTWRITEBYTECODE=1` or smoke a disposable copy.
   - Verify the release artifact digest before and after every packaged smoke. A smoke that creates `__pycache__`, `.pyc`, generated state, or root-owned files has invalidated the immutable candidate; rebuild rather than deleting around the drift.
   - Run the installer's own artifact-verification/dry-run path both before and after smoke when available.
   - Every rollout helper/template referenced after approval must either be inside the hashed artifact or separately hash-bound to the same clean Git SHA. Do not let an approval manifest point at an unbound workspace file excluded by the release builder.

6. **Exact service-identity and secret-contract gate**
   - Validate protected files under the exact systemd `User`, `Group`, `SupplementaryGroups`, sandbox, and application parser—not merely as root or the interactive operator.
   - OS readability is insufficient. Some applications intentionally reject group-readable secret files; verify the application's own loader/permission contract. Prefer owner-only `0600` when a service user must read a bearer/private token and the parser forbids any group/other mode bits.
   - Use a transient systemd unit or equivalent exact-identity probe before enabling the long-lived service. Print only PASS/metadata, never the secret.

7. **Live smoke and restart-stability gate**
   - Verify release identity, health/services, key routes, and logs.
   - `systemctl is-active` immediately after start can be a false green while a service is entering a restart loop. Add a dwell window, assert `NRestarts` stays stable, inspect the latest unit state, and hit the real endpoint.
   - For internal endpoints, smoke both unauthorized and authorized behavior, then clean smoke data. For adapters/consumers, require a synthetic receipt/readback, not only an open port.
   - For multi-hop flows, prove the real chain end-to-end or block with the exact external dependency that prevents it.
   - Keep the canary observer fail-closed after initial deploy. If a stop rule fires, execute and verify rollback first; retry only after reproducing and proving the root-cause fix under the exact runtime identity.

## Phase-spec additions

For production phases, add acceptance criteria like:

- Main repo changes are committed and pushed to the production deploy ref before deploy.
- Any changed submodule is committed/pushed and the parent gitlink points at the new submodule commit before deploy.
- Required untracked product files are staged/committed; local logs and `.supergoal/.../logs` artifacts are intentionally excluded or explicitly committed.
- Runtime services/containers that participate in the flow are verified on the deployed code and restarted when needed.
- Packaged-runtime smoke runs with bytecode/cache writes disabled, and the approved artifact digest is identical before and after smoke.
- Secret/config preflight runs under the exact service identity and the application's own permission parser.
- Live smoke covers release SHA, stable restart count after a dwell window, service health, route health, unauthorized/authorized internal endpoint behavior, cleanup, and at least one real end-to-end receipt.
- Canary stop rules are executable: a failed service/receipt triggers verified rollback to the recorded baseline before any retry.

## Pitfalls

- Dirty submodule + parent deploy = old bot/worker code in production, even if web deploy succeeds.
- New untracked tests/support files can pass locally but vanish from the production commit.
- Restarting only the web service leaves helper bots/workers on old code.
- Source-checkout smoke can miss packaged-layout imports, dependency-driver selection, and files excluded by the release builder.
- Running Python from the candidate without `PYTHONDONTWRITEBYTECODE=1` can silently add root-owned `__pycache__` files and invalidate the approved artifact digest.
- `systemctl is-active` sampled during `Restart=on-failure` can report active between crashes. Require dwell + `NRestarts` + endpoint/receipt proof.
- A token can be readable at the Unix level yet rejected by the application because mode `0640` is considered too broad; exercise the real secret loader under the exact service identity.
- A successful deploy script is not proof of behavior; verify `/release`/SHA plus the actual user flow.
