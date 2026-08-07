# Gateway restart + live proof after SuperGoal patching

Use this when a SuperGoal run changes Hermes gateway/GoalManager code and the live Telegram gateway must restart before a button/reply `/goal` proof is valid.

For restart/drain fixes that must resume active `/goal` sessions or reconcile missed Chip Telegram messages, also read `references/gateway-goal-startup-recovery.md` before planning. That reference captures the core lesson: recovery belongs in gateway/GoalManager state-machine code, with startup hooks only as watchdog/reporting, and `telegram-chip` is the read-only Chip chat-history source.

## Why

Running `hermes gateway run --replace` or restarting the service inside the live Telegram turn can kill the same assistant response. The safe pattern is: deliver the current answer first, schedule a detached restart, then send a compact proof message after the gateway is back.

## Pattern

1. Identify the active install and service path before touching anything:
   - active process: `ps -eo pid,user,lstart,cmd | grep 'hermes_cli.main gateway run'`
   - service status: `hermes gateway status` or `systemctl status hermes-gateway --no-pager`
   - worktree diff: `git status --short --branch && git diff --stat`

2. If code patches are dirty but intentional, run focused tests before restart.

3. Create a small detached probe script under `~/.hermes/scripts/` that:
   - records old gateway PID
   - restarts `hermes-gateway`
   - waits for a fresh active MainPID
   - probes health endpoint if configured
   - verifies the relevant GoalManager invariant (`load_goal(tip).status`, `migrate_goal_to_session` import, visible session key)
   - sends a short Telegram proof message to the origin topic using the existing gateway bot token

4. Schedule it after the final response, not inline:

```bash
unit="hermes-gateway-restart-proof-$(date +%Y%m%d%H%M%S)"
sudo systemd-run \
  --unit="$unit" \
  --description="Delayed Hermes gateway restart + Telegram proof" \
  --on-active=20s \
  --collect \
  <runtime-dir> <home-dir>/.hermes/scripts/<probe>.py
```

5. Final reply should state only:
   - scheduled unit/timer
   - what the probe will verify
   - that proof will arrive as a separate message

## Proof bar

A green proof must include at least:

```text
old pid: <pid>
new pid: <pid>
active: active
GoalManager tip: <session id>
goal status: active|paused|blocked
migration fn loaded: true
health: true
```

For Telegram SuperGoal, a log line or bot send response is not enough. The live proof is visible topic session state: `group:<chat_id>:<thread_id>` has a GoalManager state and the goal lives on the compression tip.

## Active-turn drain and post-restart repair

A detached unit can still spend its stop timeout waiting for the active Telegram turn to finish. `deactivating` during that drain is not evidence that the patch failed, and canceling the systemd job does not reverse a gateway process that already entered graceful shutdown.

- Finish the current response quickly after scheduling the detached unit; do not keep the turn alive with unrelated audit work while the service waits to drain.
- Let the detached unit own the full `restart -> wait for active -> verify new MainPID -> product probe` sequence. Do not issue a second inline restart.
- If a restart job was canceled after graceful shutdown began, queue a detached `systemctl start` recovery before ending the turn; otherwise the gateway can finish draining and remain down.
- Product proof belongs after the new PID is active. For Telegram markup/button repairs, reapply or fetch the markup after restart and store a receipt with bot identity, message id, and button count.
- Telegram `editMessageReplyMarkup` returns HTTP 400 `message is not modified` when the desired markup is already present. Treat only that exact description as idempotent success; keep every other 400 fail-closed and cover this branch with a regression test.

## Pitfalls

- Do not use `hermes gateway run --replace` from inside the live gateway turn.
- Do not call the restart proof valid if the PID did not change.
- Do not claim a user-visible control works from unit tests alone; require a post-restart product receipt or fetch-back.
- Do not expose bot tokens or `.env` values in the proof.
- Do not confuse sibling user gateway processes owned by other users with the active `hermes` service process.
