# Architect+ lite gate

Use this gate for substantial, architecture-affecting, agent-native, security-sensitive, or production-facing chip-supergoal plans.

Do not use it for tiny one-step tasks. If skipped, record a narrow reason in `THINKING.md` or `ROADMAP.md`.

## Required fields

### Source-of-truth boundary

State:
- canonical owner of each important state/data object;
- derived/cache/view state;
- forbidden duplicate truth sources;
- migration or rollback seam if the boundary changes.

### Permission matrix

Cover at least:
- human user;
- admin/operator;
- service/backend worker;
- AI/agent automation;
- external integration/webhook where relevant.

For each role, specify read/write/execute/approve boundaries.

### Failure-mode matrix

Name concrete failure modes and behavior:
- continue;
- degraded;
- fail-closed;
- human-gate.

Include rollback or stop condition when the failure can corrupt data, leak privacy, or break production routing.

### Verification strategy

Tie risky behavior to evidence:
- commands/tests/typecheck/lint/build;
- API smoke/probe;
- log/journal check;
- browser/visual screenshot when UI matters;
- migration dry-run or rollback proof;
- negative fixtures for permission/security boundaries.

## Mutation rule

Architect+ lite must change the plan or criteria. If it finds an authority boundary, permission rule, or failure mode, it should become a phase, acceptance criterion, mandatory command, or explicit non-goal/risk.
