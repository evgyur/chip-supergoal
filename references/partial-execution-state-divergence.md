# Follow-on SuperGoal after partial manual execution

Use when a SuperGoal package still says `READY_TO_DISPATCH` / phase 1, but implementation work has already advanced outside that package and Chip asks to finish the real objective.

## Failure mode

The package seed and the implementation workspace can diverge:

- `STATE.md` still points at the old baseline and first phase;
- Git contains later commits and possibly a small dirty patch;
- tests/evidence prove some planned phases are already implemented;
- blindly resuming the old package would replay work, reset to stale code, or split evidence from reality.

This is a planner-state defect. Do not defend the old package or manufacture completed phase markers inside it.

## Recovery procedure

1. **Inspect reality first**
   - read implementation `HEAD`, branch, worktree status, dirty diff/stat and recent commits;
   - hash any uncommitted patch before changing it;
   - verify the strongest existing direct evidence (for example zero-skip PostgreSQL receipt and live read-only preflight);
   - compare reality with predecessor `STATE.md`, `ROADMAP.md` and baseline.

2. **Quarantine the predecessor as historical evidence**
   - do not reopen or rewrite it as if its executor had completed phases;
   - cite its contract/research/reviews only as source material;
   - create a new sibling package with a new goal ID and pending phase 1.

3. **Start from the actual implementation boundary**
   - bind the new package to the current exact commit plus the hash of any dirty patch;
   - make P01 recover, test and cleanly commit that patch;
   - remove phases already proven by current code/evidence instead of replaying them;
   - retain only remaining implementation, exact-candidate, approval, activation and audit work.

4. **Make continuation explicit**
   - a turn/tool-iteration ceiling is a yield boundary, not goal completion or a reason to drop the mission;
   - phase closeout is atomic: evidence → mandatory commands → criteria → RPD verdict → finding ledger → runtime-state advance;
   - persist the exact next command before yielding so the same `/goal` resumes without a status-only reply.

5. **Keep success semantics strict**
   - for a “working production version” goal, rollback is safe failure evidence, not acceptance;
   - a rollback must leave the activation phase blocked/failed or route it back for repair;
   - completion still requires the declared live causal proof (for trading: natural leader event → accepted follower order → exchange fill → protective stop) and 0 P0/0 P1 final audit.

6. **Keep approval expiry-last**
   - finish code, zero-skip tests, immutable release, packaged-path preflight and independent review first;
   - refresh live values and mint one bounded approval only immediately before the first live mutation.

## Required planning evidence

- actual implementation HEAD and branch;
- dirty-patch SHA-256 when applicable;
- predecessor package path and its stale state;
- direct test/live evidence hashes;
- explicit list of completed work removed from the new roadmap;
- new sibling package path and pending `STATE.md`.

## Pre-dispatch checks

- strict contract/package validation;
- every phase and loop validator passes;
- mandatory command shell syntax passes;
- deterministic compile passes;
- exactly one launch body;
- `STATE.md`: phase 1, `READY_TO_DISPATCH`, goal incomplete;
- review artifacts contain no private runtime identifiers, wallet addresses or secrets.
