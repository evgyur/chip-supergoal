# Repeated approval-blocked `/goal` continuations

Session-derived pitfall from a Pear/Privy/Hyperliquid SuperGoal.

## Symptom

A SuperGoal phase reaches `BLOCKED_BY_APPROVAL`, but the visible `/goal` loop keeps posting the same approval card because the goal condition mentions `SUPERGOAL_RUN_COMPLETE` and the judge keeps returning CONTINUE.

This is not more phase work. It is a GoalManager/control-plane bug or stale goal state.

## Correct behavior

When a SuperGoal response/state clearly says approval is missing — either the exact `BLOCKED_BY_APPROVAL` marker or a human blocker card like `blocked: нужен explicit approval`, `blocked by approval gate`, or `Blocked: yes` + `Need user input: explicit approval`:

- treat it as terminal blocked state for the `/goal` loop;
- do not repeat the same approval card on every continuation;
- do not burn the turn budget trying to reach `SUPERGOAL_RUN_COMPLETE`;
- mark the visible/compression-tip goal state as `blocked` or pause it with a blocker reason;
- clear queued synthetic goal continuations after terminal `done/blocked` decisions;
- drop stale internal goal-continuation events before agent execution when the session goal is no longer active;
- keep the SuperGoal `.supergoal/STATE.md` at blocked/current phase until explicit approval or credentials arrive.

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
3. Match by the exact SuperGoal package path or a unique goal fragment, not by recency alone.
4. For each active matching row, set:
   - `status = "blocked"`
   - `last_verdict = "done"`
   - `last_reason = "supergoal stopped with BLOCKED_BY_APPROVAL: <concrete blocker>"`
   - `paused_reason = "BLOCKED_BY_APPROVAL: <short human-readable blocker>"`
   - clear waiting fields if present.
5. Re-query the newest rows and confirm every matching tip row is `status=blocked` and `last_verdict=done`.
6. Reply once with `SUPERGOAL_TURN_YIELD — BLOCKED_BY_APPROVAL`, `Goal complete: no`, and the exact missing approval/input. Do not keep repeating the same approval card after the DB state is blocked.

This is a control-plane repair, not progress on the SuperGoal itself. Do not change the `.supergoal/STATE.md` from blocked/safe-lane state unless the user gives the missing approval or credential.

## Restart proof

If the fix changes Gateway/GoalManager code, schedule a detached gateway restart after the current response is delivered. Verify fresh PID and current goal tip state after restart before claiming the fix is live.
