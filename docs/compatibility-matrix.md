# Compatibility matrix — chip-supergoal v3 workstream

| Skill version | Contract/protocol | Hermetic probe | Live GoalManager probe | Notes |
|---|---|---|---|---|
| 3.0.0-alpha.4 | 3.0 / 3.0 | required on Ubuntu 24.04 and native Windows: `python scripts/test.py` | reserved/unavailable; never release evidence | Package-local Python is authoritative; Unix wrappers are compatibility entrypoints. |

## Platform contract

| Plane | Native Windows | Ubuntu | Authority |
|---|---|---|---|
| Compile, validate, state, audit, terminal | supported | supported | packaged Python runtime |
| Deterministic archive and crash recovery | supported | supported | packaged Python runtime; destination is external |
| Delivery reservation and byte-stable transport | supported | supported | packaged Python runtime |
| Bash wrappers and shell style gates | not required | supported | compatibility only |

Runtime support requires CPython 3.11.9 or newer. CI pins and verifies CPython
3.11.9 and 3.13.14 on both operating systems.

Older generated packages must be recompiled; copying only new wrappers into an
old package does not upgrade its runtime authority. The privacy scan covers all
tracked files, including force-tracked runtime paths, plus untracked working-tree
files outside runtime/private state directories. It does not scan unrelated user
directories. The reserved live hook does not replace hermetic E2E coverage.

## Observable contract covered

- `SUPERGOAL_PHASE_DONE` alone means continue.
- `AUDIT_COMPLETE` alone means continue.
- `SUPERGOAL_RUN_COMPLETE` alone means continue.
- The legacy marker trio alone means continue; it is a host compatibility footer, not runtime authority.
- Successful `python scripts/sgctl.py validate-terminal` against the current sealed package, state, audit, inventory, and exact terminal record authorizes done.
- `BLOCKED_BY_APPROVAL` means blocked/paused.
- Forced yield preserves exact next step.

## Live probe status

No genuine external Hermes GoalManager adapter ships in this repository.
`tests.integration.test_live_goalmanager` is an always-skipped reservation for a
future adapter, not a canary, and must not be counted as release evidence. A real
probe must perform an external GoalManager round trip and validate observable
terminal markers before this matrix may call it supported.
