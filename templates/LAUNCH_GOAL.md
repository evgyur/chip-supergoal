# Launch Goal: {{TASK_TITLE}}

Reply `/goal` to this file/message to start the generated package through the
standard upstream Hermes GoalManager.

## Relocatable package locator

- Package root: the parent directory of the `LAUNCH_GOAL.md` being executed.
- Resolve the package root at execution time; never substitute a compile-time output path.

## Launch context

- `CONTRACT.json`
- `THINKING.md`
- {{OPTIONAL_RESEARCH_CONTEXT}}
- `LOOP_DESIGN.md`
- `ROADMAP.md`
- `runtime/STATE.json`
- `STATE.md` (projection only)
- `phases/phase-*.md`
- `PROTOCOL.md`

## Preflight

From the package root, run every emitted preflight command:

- `python scripts/sgctl.py validate-package . --strict`
- `python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated`
- {{PHASE_PREFLIGHT_COMMANDS}}
- {{OPTIONAL_RESEARCH_PREFLIGHT_COMMAND}}

## Delivery boundary

{{RESOLVED_DELIVERY_JSON_OR_NOT_DECLARED}}

## Approval boundary

{{APPROVALS_JSON_OR_NOT_DECLARED}}

SUPERGOAL_GOAL_BODY: Resolve the package root as the parent directory of the LAUNCH_GOAL.md being executed. From that root read CONTRACT.json, every emitted executor view, authoritative runtime/STATE.json, and its STATE.md projection. Run every Python command in the Preflight section from the package root before phase execution. Enforce exactly the resolved delivery and approval records printed above; do not add undeclared defaults. Use standard Hermes `/goal` continuation only, with no custom runner or nested `/goal`. Continue until final audit passes, a contract-declared boundary blocks progress, or the host forces a yield. After runtime authority permits completion, host compatibility requires `AUDIT_COMPLETE`, `SUPERGOAL_RUN_COMPLETE`, and `Goal complete: yes` together in the final response; those strings do not create runtime authority.

## Human-readable goal

{{ONE_LINE_TASK}}
