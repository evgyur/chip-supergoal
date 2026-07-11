# Repository-state comparison — the one strategy

`scripts/repo-state.sh` is an optional Unix-only compatibility helper. It is
read-only supporting evidence, not terminal or audit authority. Native Windows
uses the same Git comparison model through Git plus PowerShell/Python file tools;
package completion is decided only by the Python evidence/audit/terminal plane.

Planning-side deliverable review and per-phase cleanliness ask the same question:
*what changed in this repository since the run started?* This reference defines
that comparison model. Package audit and terminal authority independently
validate bound evidence and sealed runtime state.

## The trap: `git diff <baseline>..HEAD`

A two-dot range compares two **commits**. An autonomous Supergoal run frequently leaves its
work **uncommitted** — staged, unstaged, or brand-new untracked files. Against an uncommitted
run, `git diff <baseline>..HEAD` is **empty**:

- the deliverable check would report shipped files as "missing"; and
- the cleanliness greps would report "0 debug prints / 0 TODOs / 0 dead imports" no matter what
  was actually written.

The baseline (`Baseline ref:` in `.supergoal/STATE.md`) is captured at Stage 7 dispatch, before
any phase runs. By completion the working tree — not just `HEAD` — holds the result. So the
comparison must be **baseline → working tree**, not **baseline → HEAD**.

## The strategy: complete working-tree state vs baseline

| What | How | Captures |
|------|-----|----------|
| Tracked changes | `git diff <baseline>` (single revision — **no** `..HEAD`) | committed, staged, unstaged, **and** deleted tracked files |
| Untracked files | `git ls-files --others --exclude-standard` | brand-new deliverables never `git add`-ed |
| Invalid/unavailable baseline | fail closed inside git; filesystem existence only outside git | bogus SHA becomes an audit gap; non-git workspaces degrade honestly |

`git diff <baseline>` (a single revision argument) diffs the **working tree** against the
baseline commit, so it already folds in staged + unstaged changes *and* any commits made after
the baseline. Untracked files are diff-invisible, so they are detected **separately** and on
purpose. When the baseline cannot be resolved to a commit inside a git repository, the helper fails closed with `invalid baseline` so audit does not certify ungrounded work. Only non-git workspaces degrade to existence-only checks, and the audit should surface that reduced coverage honestly.

**Ignored files are intentionally out of scope of untracked detection.** `--exclude-standard`
honours `.gitignore`, so a `.gitignore`'d file is *not* reported as an untracked deliverable and
its body is *not* fed to the cleanliness greps via `added-lines`. This is deliberate — ignored
paths are usually ephemeral build output or logs, not shipping artifacts. Two consequences worth
knowing: (a) an ignored deliverable inside a git repo is not proof of work from this run; if it
exists unchanged relative to the baseline, the helper returns `unchanged — existed before baseline`
with exit 3 unless the roadmap marks it pre-existing/verification-only; (b) debug output that lives *only* in an ignored
file escapes the cleanliness count — if a phase legitimately ships such output and wants it
inspected, declare a `Cleanliness override:` in the phase spec rather than relying on the greps.

## Optional Unix implementation: `scripts/repo-state.sh`

On Unix, the helper encapsulates the table above and never mutates the repo or
index. It may be copied under `scripts/` as a convenience. The executor must not
require it when running natively on Windows.

```text
bash .supergoal/scripts/repo-state.sh deliverable   <baseline> <path>
    -> "present — <evidence>" (exit 0) | "missing"/"deleted" (exit 1) |
       "invalid baseline" (exit 2) | "unchanged — existed before baseline" (exit 3)
       present evidence distinguishes: changed vs baseline / untracked new file /
       exists on disk only in non-git fallback mode

bash .supergoal/scripts/repo-state.sh changed-files <baseline>
    -> newline-delimited paths changed since baseline (tracked + untracked + deleted)

bash .supergoal/scripts/repo-state.sh added-lines   <baseline>
    -> every added/new line since baseline: tracked-diff '+' lines plus the full body
       of each untracked file. Pipe to grep for cleanliness counts.
```

Quote path arguments — deliverable paths may contain spaces.

### Native Windows path

Run `git diff <baseline>` and
`git ls-files --others --exclude-standard` directly from PowerShell, inventory
declared deliverable paths with PowerShell or Python, and bind the observations
through `python scripts/sgctl.py record-evidence --input <evidence.json>`. Never
substitute `git diff <baseline>..HEAD`, which omits working-tree state.

### Audit deliverable check

For each declared deliverable path/glob, collect platform-native evidence. The
following command is an optional Unix convenience:

```text
bash .supergoal/scripts/repo-state.sh deliverable "$(baseline)" "<path>"
```

`missing`/`deleted` (exit 1), `invalid baseline` (exit 2), or `unchanged pre-existing` (exit 3) remains an evidence failure unless the contract explicitly marks the deliverable pre-existing/verification-only. The bound Python audit, not this helper, decides completion.

### Per-phase cleanliness check

```text
added_file="$(mktemp)"
bash .supergoal/scripts/repo-state.sh added-lines "$(baseline)" > "$added_file"
grep -cE 'console\.log|console\.error' "$added_file"   # JS/TS debug prints
grep -cE '\b(TODO|FIXME|XXX)\b' "$added_file"         # session TODO/FIXME added
# dead imports: inspect added import lines for usage in their file
```

Because `added-lines` includes untracked file bodies, debug prints in a freshly-created,
never-committed file are caught too — the case the old `..HEAD` grep missed entirely.

## Backward compatibility

The transcript markers (`SUPERGOAL_PHASE_VERIFY` cleanliness section, `AUDIT_VERIFY`
`Deliverables:` block, `AUDIT_GAP`, `AUDIT_COMPLETE`) and the 3-strike semantics are unchanged.
Only the *source of truth* moved from a commit range to the complete working tree, and untracked
detection was added. A deliverable that merely exists unchanged is no longer proof that this run
shipped it: the helper returns `unchanged — existed before baseline` with exit 3, and final audit
must treat that as a gap unless the roadmap explicitly marks the deliverable as pre-existing /
verification-only.

## Line endings (cross-platform)

`repo-state.sh` and every other `*.sh` are forced to LF via `.gitattributes`
for Unix compatibility consumers. Native Windows does not invoke them; the LF
rule prevents `core.autocrlf` from breaking their shebang when a checkout is
shared with WSL or another Unix host.
