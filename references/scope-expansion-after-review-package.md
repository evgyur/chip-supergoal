# Scope expansion after a reviewed SuperGoal package

Use when Chip adds sources, systems, privacy requirements or live effects after a SuperGoal package has already been compiled or delivered.

## Rule

Treat the follow-up as a contract revision, not as prose appended to `ROADMAP.md`. The old package fingerprint, approval manifest and delivery archive are stale until the complete contract is regenerated and revalidated.

## Procedure

1. Preserve the original request unchanged and add a dated request addendum as a new source.
2. Run read-only preflight for the new source/system. Record identities, health, authority, sensitivity and capability shape without reading unnecessary private bodies or printing secrets.
3. Increment `contract_revision`.
4. Update every affected semantic plane:
   - goal objective and done condition;
   - source set and hashes;
   - decisions and assumptions;
   - architecture/source of truth;
   - data/egress/retention policy;
   - risks and mitigations;
   - approval scope and bound manifests;
   - phase work, deliverables, criteria, commands and evidence;
   - canary, rollback, final audit and delivery.
5. If the new source has different authority, define precedence and contradiction behavior. Never silently merge conflicting claims.
6. If the source crosses privacy boundaries, define consent, attribution, revocation, minimum fields and blocked behavior before build phases.
7. Bind every new activation manifest into the final approval receipt. A command that activates the source must accept and verify that manifest; prose-only binding is insufficient.
8. Recompute hashes for every modified local source.
9. Compile into a fresh output root. Do not hand-edit sealed generated files or compile over runtime/delivery residue.
10. Re-run strict contract/package, loop-design, research-gate, phase rendering and mandatory-command tokenization checks.
11. Run a semantic closure pass:
    - every criterion has an executable verifier or explicit review evidence;
    - future files are produced before their commands consume them;
    - live URLs/hosts are unambiguous;
    - activation commands bind every declared manifest;
    - approval text, commands and receipts name the same hashes and targets.
12. Rebuild the review bundle, run archive integrity/secret/private-corpus scans and issue a new fingerprint/hash.

## Privacy-sensitive source expansion

For shared chat + operational DB/API + private DMs:

- use the operational system as authority for status/owner/deadline;
- use shared chat as contextual evidence with provenance;
- never bulk-export private DMs into the new agent;
- move only author-approved summaries through a governed candidate/promotion boundary;
- default to aggregation and require explicit author permission for named attribution;
- canary missing consent as `blocked_by_consent` rather than bypassing it;
- keep v1 connectors read-only unless the request explicitly includes source mutations.

## Approval impact

Safe planning and preflight do not require a new production approval. Any prior production approval becomes invalid if target, manifest set, source capability, privacy scope or live effect changes. Present one revised exact manifest after all safe checks finish.

## Completion evidence

Report:

- contract revision;
- new sources and authority classes;
- strict validator results;
- semantic closure result;
- new package fingerprint and archive hash;
- whether live activation remains pending.
