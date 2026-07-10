# SuperGoal cross-file consistency and review hardening

Use when a SuperGoal package changes phase count, risk caps, launch constraints, or receives Shaw/XHIGH/Deep review patches.

## Lesson

Per-file semantic validators can pass while the package is still inconsistent. In the `chip-hlcopy` live-test package, individual phase files validated even though several still said `Phase: N of 10` after the roadmap moved to 11 phases. Risk caps also survived in non-executable review text until a grep exposed them.

## Required extra scan after phase/risk edits

After any package mutation that changes phase count, caps, approvals, or market/action constraints, run a cross-file scan in addition to `validate-phase.sh`:

```bash
cd <package>/.supergoal
export PYTHONPATH=<installed-chip-supergoal>/lib
bash scripts/validate-loop-design.sh --instantiated LOOP_DESIGN.md
for f in phases/phase-*.md; do bash scripts/validate-phase.sh "$f"; done
python3 - <<'PY'
from pathlib import Path
import re
root = Path('.')
texts = '\n'.join(p.read_text() for p in root.rglob('*.md'))
phase_files = sorted((root/'phases').glob('phase-*.md'))
phase_totals = []
for p in phase_files:
    m = re.search(r'^Phase: (\d+) of (\d+) ', p.read_text(), re.M)
    phase_totals.append((p.name, m.group(1), m.group(2)) if m else (p.name, None, None))
launch = []
for p in root.rglob('*.md'):
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if line.startswith('SUPERGOAL_GOAL_BODY:'):
            launch.append((str(p), n))
print('phase_count=', len(phase_files))
print('phase_totals=', phase_totals)
print('launch_markers=', launch)
assert len(launch) == 1
assert all(t == str(len(phase_files)) for _, _, t in phase_totals)
PY
```

## Risk-string scan

For live/money/trading plans, add a stale-pattern scan for values you just changed. Examples:

```bash
rg '\$5|<= \$10|Phase: \d+ of 10|max-order-usd 10|expiresAfter|vaultAddress|builder_fee' .supergoal
```

Do not treat every hit as failure: review artifacts may mention stale values as fixed findings. Executable launch/roadmap/phase specs must not carry stale unsafe values.

## Review patch discipline

- Shaw/XHIGH review findings should mutate `ROADMAP.md`, `LOOP_DESIGN.md`, `LAUNCH_GOAL.md`, and the affected `phases/phase-*.md`, not just create a review memo.
- `/deep` reports are hypotheses until applied and verified. Extract concrete P0/P1 lines, patch the plan, rerun validators, and scan for the exact terms that should now exist.
- After adding/removing phases, update all of: roadmap phase map, phase headings, phase-file `Phase: N of TOTAL`, loop budget, launch text if it names counts, and state total.

## Mid-run execution rebase discipline

A continuation may discover that `STATE.md` was manually rebased into a new execution map while `ROADMAP.md` and `phases/phase-N.md` still describe the original numbering. Do not silently let one file win and keep printing phase markers.

Before closing the next phase:

1. build an explicit old→new crosswalk and prove every original finding/deliverable still has a destination;
2. update the ROADMAP phase map, affected phase specs, STATE rows/current phase, and finding ledger together;
3. preserve superseded detail as source requirements or a clear rebase addendum — never waive it by renumbering;
4. validate the phase file **before implementation**, then again before `SUPERGOAL_PHASE_DONE`;
5. re-read every rewritten phase file immediately and verify real line count/content. A successful write call or byte count is not semantic proof;
6. use only the allowed `RPD focus` enum from the phase contract (`security`, `integration`, `ux`, `migration`, `data-loss`, `gateway`, `payments`, `none`). Free-form focus text is invalid.

The phase-close order should be: final tests/evidence → RPD review and required mutations → finding-ledger update → phase validator/cross-file scan → marker → STATE advance. If a review worker is still running, do not emit the irreversible phase marker until its blocker findings are incorporated or explicitly dispositioned.
