# Phase boundary state + characterization pattern

Use this when executing a SuperGoal phase that maps existing recovery/control-plane behavior before implementing runtime changes.

## Pattern

1. Resolve the package’s state contract before editing. Read `PROTOCOL.md`, immutable seed `STATE.md`, and the declared mutable runtime state. In manifested packages, the mutable file may be `out/RUNTIME_STATE.md` or `runtime/STATE.json`; never assume `.supergoal/STATE.md` is writable.
2. Treat characterization-only phases as state-map phases, not stealth implementation phases.
3. Record the dirty baseline before editing and name pre-existing local diffs separately from phase-created files.
4. Add passing characterization tests for current behavior.
5. For an implementation phase, use a real RED → GREEN sequence: run the focused test before creating the missing module/behavior, preserve the failing result in the phase evidence, implement the smallest complete behavior, then rerun the exact test.
6. Use strict `xfail` only when the phase contract explicitly defers implementation. Do not turn an active acceptance criterion into an xfail merely to make the suite green.
7. Run focused tests immediately. If database-backed tests would otherwise skip and a local PostgreSQL administrator is available, create an isolated temporary database/role, run the exact integration tests against it, and remove both with a cleanup trap. Never point characterization tests at the live trading database.
8. Before PASS, run every mandatory phase command exactly as written plus any relevant package build/smoke check. A broad suite with infrastructure skips does not replace the isolated integration proof. For final safety characterization, run both shapes when useful: the ordinary developer suite and an infrastructure-enabled suite against a disposable database. Use a DSN accepted by every client exercised by the suite (plain `postgresql://...` works for raw psycopg and is normalized by the repository layer), and use an isolated database name that satisfies any built-in drill allowlist.
9. Write concise evidence under the package-declared evidence root with canonical state, lifecycle paths, exact gap/fix, insertion points, commands, outcomes, and live-mutation status. Generate or refresh source-registry hashes only after the phase's last code/evidence mutation; later patches make an earlier registry stale.
10. At the phase boundary, update only the declared mutable runtime state in the same turn: advance `Current phase`, append completion/evidence events, update timestamps/delivery state, and leave manifested `STATE.md` and `MANIFEST.json` untouched unless the protocol explicitly defines a compiler regeneration step. If an external tool/budget stop lands after evidence is complete but before this state write, the next continuation must reconcile evidence to runtime state first rather than rerun the completed phase.
11. Continue into the next phase in the same GoalManager run unless the protocol declares a real blocker, approval gate, budget stop, or forced-yield condition. Do not emit a courtesy turn yield merely because one numbered phase passed.

## Pitfalls

- Mutating a manifested seed `STATE.md` can invalidate package integrity and destroy the planner/executor boundary.
- Leaving runtime state on a completed phase makes continuation wrappers repeat work.
- A skipped PostgreSQL suite is not execution evidence when an isolated ephemeral database can be created safely.
- Passing a static test while omitting release/install wiring creates a consumer that exists in source but not in the deployable artifact.
- `SUPERGOAL_TURN_YIELD` is a blocker/forced-yield marker, not a normal phase delimiter.

## Example result shape

```text
SUPERGOAL_PHASE_VERIFY
pass — focused RED captured, implementation GREEN
pass — isolated PostgreSQL integration: 6 passed, 0 skipped
pass — package build/smoke passed
pass — evidence written under <evidence-root>/phase-N/
pass — mutable runtime state advanced to phase N+1

SUPERGOAL_PHASE_DONE
Next state: phase N+1; execution continues
```
