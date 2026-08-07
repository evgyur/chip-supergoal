# Planner preflight vs post-phase commands

Use when Stage 6.5 evaluates a newly compiled package whose phases create scripts, schemas, or other commands that do not exist yet.

## Separate three statuses

Do not collapse these into one artificial green check:

1. **Package preflight**: contract/package/loop/phase validators, shell syntax, package-local runtime, archive extraction, GoalManager markers, source access.
2. **Repository baseline**: existing tests and verifiers that can run before implementation.
3. **Post-phase acceptance**: commands that intentionally invoke deliverables created by that phase.

A post-phase command may be syntax-checked and traced before launch, but it must not be reported as executed or passing before its producer deliverable exists.

## Known baseline red

If an existing baseline command is red:

- reproduce the exact failure and preserve output/hash;
- decide whether it is unrelated pre-existing red, an explicit Phase 1 repair input, or a real launch blocker;
- never encode the expected failure as `ok=true` merely to obtain `PREFLIGHT_GREEN`;
- report split status such as `package_preflight=green`, `repository_baseline=known_red`, `post_phase_commands=planned`;
- emit overall `PREFLIGHT_RED` when the launch contract cannot safely begin from that red state;
- only allow launch from a known-red baseline when Phase 1 explicitly owns the repair, no risky mutation depends on the broken invariant, rollback/intake evidence is preserved, and the launch summary states the gap plainly.

## Future command trace

For every command whose executable is created inside the same phase, require before sealing:

- producing work item and deliverable path;
- acceptance criterion referencing that command;
- exact cwd and package/workspace root;
- command syntax validation;
- planned test or fixture proving its ABI after implementation;
- no claim that the command ran during planner preflight.

Existing commands and safe probes must run now. Future implementation commands are verified later by their phase and final audit.

## Research artifact pitfall

The v3 compiler renders `RESEARCH.md` whenever `compatibility.research_gate` is a non-empty mapping, even when `required=false`. If research did not run and no research artifact should exist, omit the `research_gate` field entirely. Do not create a `not_required` gate object just to document that research was skipped.
