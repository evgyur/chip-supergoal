# SuperGoal Artifact Boundaries

This is the canonical contract for files generated and delivered by `chip-supergoal`. If another active reference disagrees, this file wins and the other reference must be patched.

## Startup pack v4

Every Chip-facing planner dispatch uses **startup_pack_v4**. Telegram receives exactly three separate native documents, in this order:

1. `THINKING.md`
2. `ROADMAP.md`
3. `LAUNCH_GOAL.md` **last**

No other package artifact is sent by default. `RESEARCH.md`, `LOOP_DESIGN.md`, `STATE.md`, `PROTOCOL.md`, `CONTRACT.json`, `MANIFEST.json`, phase specs, scripts, libraries, specs, templates, runtime state, reports, and complete archives remain in the disk package. Send one of them only when Chip explicitly asks for that specific artifact.

`LAUNCH_GOAL.md` is the sole replyable launch surface. Its Telegram caption tells Chip to reply `/goal` to that file. No completion prose follows it.

## Boundary table

| Artifact | Generated | Default Telegram delivery | Receipt / proof | Notes |
|---|---:|---:|---|---|
| `THINKING.md` | yes | yes, first | startup receipt | Constraints, risks, assumptions, context. |
| `ROADMAP.md` | yes | yes, second | startup receipt | Phase map and acceptance contract. |
| `LAUNCH_GOAL.md` | yes | yes, third and last | startup receipt + single-marker scan | Sole real `SUPERGOAL_GOAL_BODY:` surface. |
| `RESEARCH.md` | conditional | no | package validation | Disk-only unless explicitly requested. |
| `LOOP_DESIGN.md` | yes | no | loop validator | Disk-only. |
| `STATE.md` / `PROTOCOL.md` | yes | no | package validation | Executor internals stay in package. |
| `CONTRACT.json` / `MANIFEST.json` | yes | no | strict validation | Machine artifacts stay in package. |
| `phases/phase-*.md` | yes | no | phase validation | Phase specs stay in package. |
| complete `tar.gz` | optional | no | package receipt | Portable archive is not a default chat attachment. |
| final artifact bundle | conditional | no at planner dispatch | final receipt when explicitly requested | Separate executor-stage delivery.

## Startup receipt

The planner writes `.supergoal/out/review-md-files-delivery-receipt.json` with:

- `kind: "startup-files"`
- `pack_version: "startup_pack_v4"`
- `ok: true`, `sent: true`
- exact target chat/thread
- exact ordered `files`: `["THINKING.md", "ROADMAP.md", "LAUNCH_GOAL.md"]`
- exactly three SHA-256 hashes
- exactly three real Telegram `message_ids`
- exact three-entry `file_message_ids` mapping
- `launch_message_id` equal to the ID mapped from `LAUNCH_GOAL.md`

A receipt from any earlier pack version, any extra/missing file, wrong order, link/path-only handoff, bare `MEDIA:` path, blank document, or guessed ID cannot satisfy dispatch.

## Hard invariants

- Default Telegram delivery is exactly three files, never a full package dump.
- `LAUNCH_GOAL.md` is the only launch surface and is sent last.
- Internal package completeness and strict validation remain mandatory even though internals are not sent.
- Planning delivery failure blocks `READY_TO_DISPATCH`.
- Planner delivery receipts prove dispatch, not product completion.
