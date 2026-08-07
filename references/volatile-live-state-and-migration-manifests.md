# Volatile live state and reversible migration manifests

Use this pattern when a SuperGoal compares mutable scheduler/config state with a candidate migration plan, especially Hermes cron registries and systemd timers.

## Stable snapshot rule

Live registries often mix definitions with volatile runtime fields such as last-run timestamps, counters, durations, and delivery state. Hashing the whole file makes a correct verifier fail whenever the scheduler advances.

1. Define an explicit stable projection: identity, name, enabled state, schedule, script/command, workdir, and other authority-bearing fields.
2. Sort by stable identity and hash canonical JSON for that projection.
3. Keep the raw-file hash as forensic evidence, but do not use it as the sole migration gate.
4. Fail when the stable projection changes; report volatile drift separately.

Never weaken the comparison to “ignore all changes.” Only known runtime-only fields may be excluded.

## Complete migration manifest

Represent every item from the audited scope, including objects removed since the baseline:

- current objects carry `presentCurrent=true`;
- removed one-shots or retired timers remain as historical tombstones;
- each object has action, execution order, reason, rollback condition, and rollback steps;
- writer retirement is sequenced after replacement consumer/alert proof;
- retained jobs are explicitly read-only and have a sunset or review phase.

A proposal may pass structural verification while remaining `liveReady=false`. That is the honest state before approval-bound pauses, rewrites, enable/disable operations, or service restarts.

## Authority proof

Maintain a separate one-writer matrix by domain. For each domain record:

- canonical writer;
- canonical state store;
- legacy writers and required retirement action;
- scheduler behavior (`enqueue only`, never direct domain writes);
- retained read-only projections.

Verify candidate authority independently from current live readiness. Do not claim live single-writer state from a candidate-only policy.

## Alert and report cutover

Before retiring a watchdog, prove a real synthetic receipt through the replacement path (for example loopback Alertmanager HTTP request → bounded Haraldr inbox record), not just static config presence. Reports must read the canonical v2 store and omit private identifiers/payloads unless explicitly required.

## Evidence shape

- authority matrix and verifier output;
- migration manifest and stable-projection verification;
- current/live drift list;
- synthetic alert receipt test;
- read-only report projection sample;
- explicit list of live mutations (usually `zero` before approval);
- `liveReady` and exact reason.
