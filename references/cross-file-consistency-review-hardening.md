# SuperGoal cross-file consistency and review hardening

Use when a SuperGoal package changes phase count, risk caps, launch constraints, or receives Shaw/XHIGH/Deep review patches.

## Lesson

Per-file semantic validators can pass while the package is still inconsistent. In the `chip-hlcopy` live-test package, individual phase files validated even though several still said `Phase: N of 10` after the roadmap moved to 11 phases. Risk caps also survived in non-executable review text until a grep exposed them.

## Required extra scan after phase/risk edits

After any package mutation that changes phase count, caps, approvals, or market/action constraints, first run the cross-platform Python authorities:

```text
python scripts/sgctl.py validate-loop-design LOOP_DESIGN.md --instantiated
python scripts/sgctl.py validate-phase-markdown phases/phase-NN.md
```

Run the phase command once for every phase. Then run the checked-in,
cross-platform consistency entrypoint from the package root:

```text
python scripts/check-cross-file-consistency.py .
```

During planner-side review before a fresh package has been compiled, the
installed-skill entrypoint accepts an explicit target instead:

```text
python <installed-chip-supergoal>/scripts/check-cross-file-consistency.py <package-root>
```

It uses the sealed package's no-follow Python library, requires contiguous
`phases/phase-NN.md` ordinals, checks every `Phase: N of TOTAL` header against
the discovered phase count, and requires the only launch body to be
inside root `LAUNCH_GOAL.md` (sealed `templates/` examples are excluded). It works directly in PowerShell, Command Prompt, and Unix
shells; no heredoc, `PYTHONPATH`, Bash, or WSL translation is required. Tree
enumeration, each Markdown read, and total Markdown bytes are explicitly
bounded and fail closed.

## Risk-string scan

For live/money/trading plans, add a stale-pattern scan for values you just changed. Examples:

```text
rg '\$5|<= \$10|Phase: \d+ of 10|max-order-usd 10|expiresAfter|vaultAddress|builder_fee' .supergoal
```

Do not treat every hit as failure: review artifacts may mention stale values as fixed findings. Executable launch/roadmap/phase specs must not carry stale unsafe values.

## Review patch discipline

- Before execution starts, Shaw/XHIGH findings must mutate the source contract or renderer inputs, then recompile `ROADMAP.md`, `LOOP_DESIGN.md`, `LAUNCH_GOAL.md`, phase views, state, and manifest together. Never hand-patch sealed generated views.
- `/deep` reports are hypotheses until applied and verified. Extract concrete P0/P1 lines, patch canonical source, recompile, rerun validators, and scan for the exact terms that should now exist.
- After adding/removing phases, recompile and verify all generated counts, loop budget, launch text, authoritative genesis state, and manifest in one operation.

## Mid-run execution rebase discipline

A continuation may discover that `STATE.md` or another generated view was manually rebased while the sealed contract, authoritative state, roadmap, and phases still describe the original graph. This is package drift, not a valid execution rebase.

Before closing the next phase:

1. run strict package validation and stop using the divergent projection;
2. if execution never started, patch canonical contract input and compile a fresh package;
3. if execution started, preserve the package as evidence and create an explicit audit-remediation or sibling follow-on package rather than rewriting history;
4. build an old→new crosswalk and prove every original finding/deliverable still has a destination in that new authority;
5. rerun phase validators and `check-cross-file-consistency.py` before dispatch;
6. use only the allowed `RPD focus` enum (`security`, `integration`, `ux`, `migration`, `data-loss`, `gateway`, `payments`, `none`).

The phase-close order is: final tests/evidence → RPD review → finding-ledger update → phase validator/cross-file scan → marker → authoritative state transition. If a review worker is still running, do not emit the irreversible phase marker until its blocker findings are incorporated or explicitly dispositioned.
