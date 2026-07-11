# Old-server decommission drain after production migration

Use this reference from `chip-supergoal` phases that drain an old/source production host after a migration. It complements the root old-server decommission rule: backup/restore-readiness first, then workload classification, then provider-safe OS drain, then explicit delete approval.

## Hard boundary

A drain phase may stop/disable old host workloads, but must not perform provider-side destructive or billable mutations without explicit Chip approval:

- no server delete;
- no paid snapshot;
- no reboot;
- no provider billing/tariff/resource changes;
- no DNS/floating-IP changes;
- no data volume/env/database deletion.

Use `docker compose stop`, not `down`, when stopping old database stacks before delete approval.

## Preconditions before drain

1. Restic Doctor readiness is proven for the **new active host**:
   - fresh logical dump after phase start;
   - restic backup completed with exit 0;
   - restic check clean enough for the profile;
   - no unexplained locks;
   - scratch restore-smoke proves critical tables/counts;
   - restore-smoke artifact is included in the latest restic snapshot.
2. Old workload classification exists:
   - all listeners mapped to process/service;
   - all Human20-related systemd units/timers classified;
   - docker projects classified;
   - crons searched;
   - old CRM/MCP exceptions decided.
3. New production smoke is green.
4. Any historical count discrepancy is carried as a delete-approval watch item, not hidden.

## Safe drain order

1. **Pre-drain proof**
   - DNS points public traffic to new host; no old AAAA split-brain.
   - New host app/API/MCP/Supabase/nginx services active/enabled.
   - New host backup/health/prune/payment reconciliation timers active/enabled.
   - Public smoke green.

2. **Stop flapping/stale side services first**
   - If old CRM MCP is stale and canonical CRM is on another host, retire old CRM MCP, do not migrate it.
   - If `systemctl mask` fails because the unit is a real file under `/etc/systemd/system`, do not delete/move the unit during drain. `disable --now` plus a no-restart journal check satisfies the drain goal.

3. **Stop duplicate/writer timers before app/Supabase/nginx**
   - Stop payment/reconcile timers first to avoid split-brain writes.
   - Stop old backup/health/prune timers only after new equivalents are proven active.

4. **Stop old app/API/MCP**
   - Disable old app services.
   - Smoke new public production immediately after the batch.

5. **Stop old DB/compose stack preserving state**
   - Disable old DB stack unit.
   - `docker compose stop` the stack; verify no old containers are running.
   - Do not remove volumes/configs.

6. **Stop old nginx edge last**
   - Only after previous batches and new public smoke are green.
   - Direct old-IP/old-IPv6 host override should become connection refused/closed; public production must stay green.

7. **Keep audit/delete-approval access**
   - Keep SSH open.
   - Provider monitoring agents can remain named exceptions until provider deletion.

## Verification to record

- exact units/timers stopped and their final `is-active`/`is-enabled` state;
- old listeners after drain;
- public smoke matrix after every batch;
- old direct-IP/IPv6 host-override smoke before and after nginx shutdown;
- new host services/timers final state;
- journal check showing no restart loop after disable;
- rollback commands for old-host service re-enable only, explicitly excluding DNS/floating/provider rollback unless separately approved.

## Delete approval gate

After the drain phase, run a separate provider-approval phase before any final decommission audit. This phase is **GET-only** against the provider and should end in `READY_FOR_DELETE_APPROVAL` when Chip has not yet approved deletion.

Record an approval package with:

- exact provider target: server id, name, hostname, region/AZ, OS, public IPs, disk id/size/used, provider backup count, auto-backup state;
- current active target: new server id/name/IPs and floating-IP ownership;
- final DNS/public smoke matrix proving production no longer depends on the old host;
- final old-host drained state: units/timers inactive+disabled, old containers stopped, remaining listeners only named audit/provider exceptions;
- current-new backup readiness: latest logical dump, checksum result, latest restic snapshot id, no locks, `restic check` result, restore-smoke artifact;
- all prior blockers closed or explicitly named;
- snapshot/backup recommendation with a clear cost note: provider disk backup/snapshot is optional for convenience, may be billable, and is not a substitute for the already-proven restic/restore chain;
- exact provider action options, but with bearer/token placeholders redacted: retain drained state, delete without snapshot, or snapshot/backup then delete after completion.

State handling:

- Mark the approval phase done.
- Set `STATE.md` status to `READY_FOR_DELETE_APPROVAL` and current phase to final audit blocked/pending explicit Chip provider choice.
- Do **not** print `AUDIT_COMPLETE` or `SUPERGOAL_RUN_COMPLETE` while only provider approval remains.
- Do not run `finalize` or claim successful `python scripts/sgctl.py validate-terminal`; approval-blocked work cannot have an authoritative terminal record.
- If Chip later chooses retain/delete/snapshot-then-delete, the final audit phase can execute only that approved provider path and then re-run DNS, public smoke, backup inspectability, and inventory/docs cleanup.

### Retained/off approval path

When Chip approves “snapshot then power off/retain, do not delete,” treat that as a valid Phase 8 completion path, not a blocker:

1. Make a full offsite backup before provider shutdown. For Restic/Storage Box paths, prefer a cold full-server snapshot from the drained old host that includes `/` with `--one-file-system`, excluding only pseudo/volatile/cache mounts (`/dev`, `/proc`, `/sys`, `/run`, `/tmp`, restic cache, etc.). Do not reuse a narrower daily app backup if it excludes database volumes and the user asked for “Supabase целиком / весь сервер”.
2. Tag the snapshot with the approved retention horizon, e.g. `retain-until-YYYY-MM-DD`, plus old-host/full-scope tags. Include a manifest file in the snapshot stating server id/name, host, IP, scope, retention date, and purpose.
3. Verify before shutdown: snapshot id visible, manifest visible via `restic ls`, `restic check` passes with a valid subset argument, and active-new production remains green.
4. Only then execute the approved non-delete provider action (`shutdown`/poweroff). Verify provider GET shows the old server retained in `off` state, not removed.
5. After shutdown, re-check DNS, public smoke, active-new backup inspectability, and HEL1/offsite backup inspectability. If the old host is unreachable after poweroff, record that as expected.
6. Update inventory/ops notes to say retained/off, not deleted, and record the snapshot id plus “do not prune before” date. Schedule a reminder for the retention review if available; never schedule automatic deletion/prune without explicit approval.

## Rollback wording

After old app/Supabase/nginx are stopped, say plainly that warm rollback is reduced/closed. The recovery path is verified backups/restic plus preserved old disk state until explicit delete approval. After provider deletion, old-host service rollback disappears; recovery depends on current-new backups/restic/mirrors or an optional provider disk backup if Chip approved one first.
