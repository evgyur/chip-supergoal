# chip-supergoal reference index

`spec/reference-catalog.json` is the status authority. Generated exhaustive
status and trigger projections live in `INDEX.generated.md` and
`dispatch.generated.md`; this file is the short human routing index.

## Canonical references

- `artifact-boundaries.md` — review-pack ownership, stages, delivery, and receipts.
- `artifact-schemas.md` — generated artifact schemas and authority boundaries.
- `completed-standing-goal-and-workdir-hygiene.md` — validated completed-package handling.
- `core-planning-contract.md` — Stage 0–7 planner workflow.
- `cross-file-consistency-review-hardening.md` — native phase-count and launch-surface consistency gate.
- `dispatch-map.md` — active routing table and superseded incident clusters.
- `execution-state-machine.md` — authoritative executor state machine and recovery precedence.
- `follow-on-supergoal-after-completion.md` — immutable completed package and sibling follow-on flow.
- `loop-design-gate.md` — pre-launch execution-harness design.
- `planner-executor-state-hygiene.md` — plan-only boundary and honest initial state.
- `production-safety.md` — production, auth, payments, and destructive-action boundaries.
- `rpd-review-gates.md` — embedded RPD/Senior Gate.
- `skill-maintenance.md` — skill edit, validation, and repository delivery rules.
- `telegram-launch-and-delivery.md` — launch surfaces and receipt-backed delivery.
- `upstream-goal-compatibility.md` — standard Hermes `/goal` and compatibility footer contract.

## Specialist references

Specialist references are active only for their catalog triggers; they do not
override canonical authority. Use `INDEX.generated.md` for the exhaustive list
and `dispatch-map.md` for curated routing. Incident, `private_profile_only`, and
archive references retain forensic value but are not default policy.

- Frequently routed specialist: `dev-history-hardening.md` — preserve and
  reconcile development-history evidence without replacing current runtime
  authority.

If any reference conflicts with the current package runtime, the sealed
contract, `runtime/STATE.json`, recomputed audit, and successful
`python scripts/sgctl.py validate-terminal` against
`reports/terminal-record.txt` win.
