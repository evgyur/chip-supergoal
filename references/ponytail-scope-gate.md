# Ponytail scope gate

Use this gate for every new SuperGoal before `LOOP_DESIGN.md` or `ROADMAP.md`. It prevents a planning system from becoming larger than the mission.

Canonical upstream and update SSOT: [`DietrichGebert/ponytail`](https://github.com/DietrichGebert/ponytail). When the enclosing repository provides it as a Git submodule, read `skills/ponytail/SKILL.md` and `skills/ponytail-review/SKILL.md` from that submodule and advance the gitlink for updates; do not fork or freeze-copy upstream rules into SuperGoal.

`chip-supergoal` owns only the planning adapter below. Upstream owns the Ponytail ladder and bloat-review behavior.

Source behavior: `ponytail` full mode — understand first, reuse first, shortest safe path. The exact Telegram correction behind this gate was: build the working safe MVP first; defer custom PKI, extra supervisors, independent release authorities, multi-unit ceremonies, and defenses against hypothetical fully compromised hosts until a real operating requirement appears.

## Position in the workflow

```text
INTAKE → RECON → PONYTAIL_SCOPE_GATE → LOOP_DESIGN → ROADMAP
                                          ↓
                              RPD_PLAN_REVIEW + PONYTAIL_FINAL_CHECK
```

Ponytail is **not another agent, reviewer, marker family, or review round**. The pre-plan pass is done by the planner. The post-plan pass is folded into the existing `RPD_PLAN_REVIEW` seat.

## Pre-plan gate

After recon and before loop design, write a compact scope verdict in the planning notes:

```text
PONYTAIL_SCOPE_GATE
Need: direct-work | supergoal
Outcome: <one falsifiable result>
Owner boundary: <one implementation surface>
Reuse: <existing helper/native feature/dependency>
Minimum shape: <phase/file/helper/reviewer budget>
Must keep: <security, privacy, rollback, explicit user constraints>
Explicitly omitted: <tempting but unneeded machinery>
Upgrade only when: <observable trigger>
```

Apply the pre-code ladder from the `ponytail` skill. Stop at the first rung that works: do nothing, reuse existing code, stdlib, platform-native behavior, installed dependency, one-line fix, then minimum custom code.

### Default decision

Do not create a SuperGoal when the task is a tiny edit, one bounded direct fix, one factual answer, or safely executable now. Use the direct workflow instead.

For a narrow SuperGoal, start with:

- one implementation boundary;
- three phases at most: understand/build, verify/review, migrate/canary;
- one source writer;
- one planning-review seat;
- one evidence location;
- one migration/rollback path;
- zero new orchestration layers.

Exceed a default only when the objective or a real trust boundary requires it. Record the reason in one line; do not build a justification subsystem.

## Never simplify away

Ponytail may remove ceremony, not controls that prevent real harm. Keep the smallest sufficient form of:

- authorization and trust-boundary validation;
- payment, secrets, privacy, legal and routing controls;
- rollback and data-loss protection;
- exact target/origin binding;
- tests proving the requested behavior;
- real readback for production or public effects.

A safety control is justified by a concrete reachable failure path, not by a hypothetical fully compromised host unless that attacker model is explicitly in scope.

## Final check inside RPD_PLAN_REVIEW

After the first complete draft, compare it with `PONYTAIL_SCOPE_GATE`:

1. Did the plan grow beyond the minimum shape?
2. For each added phase, helper, reviewer, receipt, manifest, service, repository, schema, or approval gate: is it necessary for the stated outcome or a real trust boundary?
3. Can an existing primitive replace it?
4. Can any file, command, phase, or abstraction be deleted without weakening acceptance?
5. Did verification become a second product or control plane?
6. Does the plan solve the user-visible problem before hardening hypothetical future scale?

Every unjustified addition is deleted before dispatch. A kept addition needs only three compact fields: `necessity`, `simpler alternative rejected`, `upgrade/removal trigger`.

Output one line inside the existing RPD plan review:

```text
Ponytail final check: <holds | shrunk: ... | direct-work instead | blocked>
```

Do not dispatch a second model merely to run Ponytail. Do not create a `PONYTAIL_REVIEW` protocol family. Do not rerun indefinitely: one shrink pass, then the existing planner stop-loss applies.

## Done criteria

- The direct-work vs SuperGoal decision is explicit.
- The smallest owner boundary and phase budget are explicit.
- Deferred machinery has observable upgrade triggers.
- The post-plan review proves the draft did not silently regrow.
- Security and rollback depth still match the real risk.
