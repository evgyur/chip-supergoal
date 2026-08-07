# Repeated blocked `/goal` continuations

Use for approval gates **and** contract-declared external blockers such as missing immutable attestations, credentials, controller access, or required receipts.

## Symptom

A SuperGoal phase reaches a terminal blocked state, but the visible `/goal` loop keeps posting the same blocker card because the goal condition mentions `SUPERGOAL_RUN_COMPLETE` and the judge keeps returning CONTINUE. A common stale reason is “missing terminal marker” even though runtime authority correctly forbids that marker while blocked.

This is not more phase work. It is a GoalManager/control-plane bug or stale goal state.

## Correct behavior

When package runtime authority is terminally blocked — by approval **or** by a contract-declared external requirement:

- treat it as terminal blocked state for the `/goal` loop;
- do not repeat the same blocker card on every continuation;
- do not burn the turn budget trying to reach `SUPERGOAL_RUN_COMPLETE`;
- never print completion markers merely to satisfy a stale judge reason such as “missing standalone terminal marker”;
- mark the exact visible/compression-tip goal state as `blocked` with `last_verdict: done`;
- clear waiting fields and queued synthetic continuations after terminal `done/blocked` decisions;
- keep authoritative package runtime state at the blocked phase until the missing input arrives.

For an external-evidence blocker, ask once for the smallest concrete input (for example immutable receipt paths or controller access). Do not relabel it `BLOCKED_BY_APPROVAL`, and do not imply that user approval can satisfy a verifier that requires real evidence.

Chip's preference is strict here: internal GoalManager continuations must never appear as user-authored chat spam. If the loop repeats, stop explaining the gate and fix the control plane.

## Compression migration gotcha

Context compression can migrate `goal:<old_session_id>` into a new tip session. If you patch only the old row, the new tip may still be `active` and auto-continue.

Before claiming the loop is fixed:

1. Find the current visible/compression-tip session id.
2. Inspect `state_meta` for `goal:<tip_session_id>`.
3. If the SuperGoal is blocked, set the tip goal state to:
   - `status: blocked`
   - `last_verdict: done`
   - `last_reason: supergoal stopped with BLOCKED_BY_APPROVAL` or the concrete blocker
   - `paused_reason`: short human-readable blocker
4. Leave parent/compressed sessions cleared or migrated; do not let stale parent goals continue.

## User-facing response

If Chip asks “why did you stop?” or “what is needed?”:

- explain the concrete blocker once;
- if the blocker is approval, show the minimum exact approval phrase only if needed;
- if the blocker is credentials, say where to provision them and explicitly say not to paste secrets into Telegram;
- do not defend the protocol at length.

## Resolve the current visible goal row

Goal text alone is not enough: the same SuperGoal may have an older active row in a DM and a newer continuation row in a group topic. Join `state_meta` goal keys to `sessions.id`, then match the current Telegram `session_key` (`agent:main:telegram:<chat-type>:<chat-id>[:<thread-id>]`). Use the exact current-topic goal key; do not mutate every row containing a similar goal fragment.

For a live SQLite database, create the rollback copy with `sqlite3.Connection.backup()` rather than a blind file copy, so WAL-backed state is captured consistently. Update inside `BEGIN IMMEDIATE`, require the old status to be `active` or already `blocked`, clear all waiting fields, and re-query by both exact goal key and current `session_key`.

## Minimal local repair recipe

When the repeated continuation is caused by stale GoalManager state rather than missing phase work, repair the control-plane row directly and verify the newest tip row, not only the older/compressed parent row.

Safe shape:

1. Back up `~/.hermes/state.db` before mutation.
2. Query recent rows:
   ```bash
   python3 - <<'PY'
   import json, os, sqlite3
   con=sqlite3.connect(os.path.expanduser('~/.hermes/state.db'))
   con.row_factory=sqlite3.Row
   for r in con.execute("select rowid,key,value from state_meta where key like 'goal:%' order by rowid desc limit 20"):
       v=json.loads(r['value'])
       print(r['rowid'], r['key'], v.get('status'), v.get('last_verdict'), (v.get('goal') or '')[:120])
   PY
   ```
3. Match the current visible `sessions.session_key` first, then confirm the goal/package fragment. Do not select by recency or goal text alone.
4. For the exact active current-tip row, set:
   - `status = "blocked"`
   - `last_verdict = "done"`
   - `last_reason = "supergoal stopped at contract blocker <criterion/code>: <concrete blocker>"`
   - `paused_reason = "<criterion/code> blocked: <short missing input>"`
   - clear every waiting field (`waiting_on_pid`, `waiting_on_session`, reason/timestamps).
5. Re-query by both exact goal key and exact current `session_key`; confirm `status=blocked`, `last_verdict=done`, and all waiting fields cleared.
6. Reply once with the appropriate blocked yield marker, `Goal complete: no`, and the exact missing input. Use `BLOCKED_BY_APPROVAL` only for a real approval gate; use a generic blocked yield for external evidence. Do not keep repeating the card after the DB state is blocked.

This is a control-plane repair, not progress on the SuperGoal itself. Do not change authoritative package runtime state unless the missing approval/evidence arrives. If the package is already correctly blocked, preserve its revision and blocker verbatim.

## Restart proof

If the fix changes Gateway/GoalManager code, schedule a detached gateway restart after the current response is delivered. Verify fresh PID and current goal tip state after restart before claiming the fix is live.
