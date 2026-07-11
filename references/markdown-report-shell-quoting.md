# Markdown report shell quoting pitfall

Use this when a SuperGoal executor writes `.supergoal/reports/*.md`, `STATE.md` event lines, launch cards, or delivery receipts from a shell script.

## Problem

Markdown reports often contain backticks, command snippets, `$VARS`, paths, and phrases like `/goal`. If a shell writes the report with an unquoted heredoc such as:

```bash
cat > .supergoal/reports/phase-N.md <<EOF
Stress: future `/goal` continuation could run `safe-lane` ...
EOF
```

bash performs command substitution and expansion inside the report body. This can silently corrupt evidence, for example:

- backticked file paths become attempted commands;
- `/goal` becomes an attempted executable;
- `$VARS` expand or disappear;
- report and `STATE.md` events lose paths/markers while the phase appears to continue.

## Required pattern

Use one of these safe writers:

### Single-quoted heredoc for static content

```bash
cat > .supergoal/reports/phase-N.md <<'EOF'
# Phase N report

RPD_PHASE_REVIEW
Stress: future `/goal` continuation must not be treated as approval.
EOF
```

### Python writer for dynamic values

Prefer Python when the report needs dynamic exit codes, paths, timestamps, or command summaries:

```bash
python - <<'PY'
from pathlib import Path
from datetime import datetime, timezone

phase = 1
pytest_code = "0"
Path('.supergoal/reports/phase-1.md').write_text(f'''# Phase {phase} report

SUPERGOAL_PHASE_VERIFY
- focused pytest: exit {pytest_code}
- path: `.supergoal/evidence/phase-1/`
''')
PY
```

If the Python script itself is embedded in a shell heredoc, the outer heredoc must also be single-quoted (`<<'PY'`) unless deliberate shell interpolation is required. If interpolation is required, keep the Python report text free of shell-evaluated backticks or pass variables through environment variables/argv.

## Long worker prompts

The same quoting risk applies when an executor launches a coding worker with a long inline `-q "<prompt>"` argument. Natural prose eventually contains an apostrophe, quote, backtick, `$`, or shell metacharacter and can fail before the worker reads the repository.

For phase workers, prefer a prompt file or a Python `subprocess.run([...])` argv list. A robust fallback is a short shell-safe bootstrap prompt that instructs the worker to read full phase instructions from `PROTOCOL.md`, the phase file, and a dedicated evidence/prompt file. Record `HEAD` and `git status --short` before launch; after any non-zero exit, compare the tree before dispatching a fallback so partial mutations are never overwritten blindly. Only one worker may mutate a worktree at a time; parallel workers must be read-only or isolated in separate worktrees.

## Verification

After writing reports/state or launching a phase worker:

1. Re-read the exact generated files.
2. Grep for missing placeholders or empty backtick locations.
3. Run `git diff --check`.
4. Save the final report readback under `.supergoal/evidence/phase-N/` if the phase had a report corruption/fix event.

## TDD / RED evidence ordering

When a phase uses TDD, create `.supergoal/evidence/phase-N/` before the RED run and pipe the actual failing command output there. If the RED was observed in the terminal before the evidence directory existed, label any later saved file as a transcript/readback, not as a fresh machine-captured RED log. Do not overwrite a true RED log with the later green rerun.

When capturing an expected-failing RED command through `tee`, disable fail-fast around that command and append the exit marker before returning control to the phase script. Pattern:

```bash
set +e
.venv/bin/python -m pytest -q tests/test_x.py::test_new_regression 2>&1 | tee .supergoal/evidence/phase-N/red-before-implementation.log
status=${PIPESTATUS[0]}
set -e
echo "RED_EXIT=$status" | tee -a .supergoal/evidence/phase-N/red-before-implementation.log
# The phase script may continue only if status is non-zero as expected.
[ "$status" -ne 0 ] || { echo "expected RED but test passed"; exit 1; }
```

Avoid `set -e` plus a raw failing pytest pipeline: the script can exit before appending `RED_EXIT`, which leaves evidence ambiguous and forces manual repair.

## Hermes terminal logging guard pitfall

When writing SuperGoal evidence from shell, avoid Bash process substitution such as `exec > >(tee -a "$LOG") 2>&1` or similarly clever redirection. Hermes terminal safety can classify this as backgrounding and reject the command before it runs. The durable fix is to keep the shell simple:

1. write a small Python or shell helper file with `write_file`;
2. copy/run that helper on the target host if needed;
3. have the helper write both the machine-readable JSON and the `.log` evidence file directly;
4. print only a compact summary to stdout.

This preserves evidence without fighting the terminal guard and is cleaner for approval-gate preflights.

## SuperGoal phase rule

A phase is not done if its report/state marker text was corrupted by shell expansion. Repair the report, rerun the relevant checks, and only then print `SUPERGOAL_PHASE_DONE`.
