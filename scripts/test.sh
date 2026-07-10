#!/usr/bin/env bash
# Regression suite for the public chip-supergoal skill package.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

for f in scripts/*.sh; do bash -n "$f"; done
pass "shell syntax"

for required in \
  SKILL.md \
  scripts/validate-phase.sh \
  scripts/validate-loop-design.sh \
  scripts/repo-state.sh \
  templates/PROTOCOL.md \
  templates/ROADMAP.md \
  templates/RESEARCH.md \
  templates/LOOP_DESIGN.md \
  templates/LAUNCH_GOAL.md \
  references/rpd-review-gates.md \
  references/core-planning-contract.md \
  references/artifact-boundaries.md \
  references/artifact-schemas.md \
  references/loop-design-gate.md \
  references/execution-state-machine.md \
  references/INDEX.md \
  references/dispatch-map.md \
  references/dev-history-hardening.md \
  references/upstream-goal-compatibility.md \
  references/upstream-goal-reconciliation.md \
  references/rpd-to-supergoal-handoff.md \
  references/ignored-supergoal-package-hygiene.md \
  templates/delivery/send-review-md-files.sh \
  templates/delivery/package-final-artifacts.sh \
  templates/delivery/send-final-artifacts.sh \
  templates/delivery/review-md-files-delivery-receipt.schema.json \
  templates/delivery/final-artifacts-delivery-receipt.schema.json; do
  [[ -f "$required" ]] || fail "missing required asset: $required"
done
pass "install layout contains required assets"

bash scripts/validate-loop-design.sh templates/LOOP_DESIGN.md >/dev/null
pass "loop-design template validates"

loop_instantiated="$(mktemp)"
cat >"$loop_instantiated" <<'EOF'
# LOOP_DESIGN.md

## Goal
Ship a falsifiable refactor while preserving the current chip-supergoal contract and tests.

## Context sources
- User objective: refactor chip-supergoal through Shaw xhigh review.
- Repository / filesystem: <workspace-dir>/chip-supergoal.
- Canonical source: references/artifact-boundaries.md.

## Host model
- Host: Hermes /goal executor with subagents allowed only for review.

## Reviewer / judge model
- Reviewer/judge: Shaw xhigh reviewer.
- Mode: verdict plus mutation requests.
- Required evidence tier: tests and diff evidence.

## Verification gates
1. Gate: aggregate regression suite
   - check: bash scripts/test.sh
   - pass condition: exit 0
   - failure mutation: patch the failing contract before continuing

## State checkpoints
- State file: .supergoal/STATE.md.
- Event ledger: reports/phase-N.md.

## Stop conditions
- hard blocker: missing canonical source.
- no-progress: stop after 2 repeated failed attempts.
- max revisions: <= 3 per failed gate.
- max iterations: 12.
- budget exceeded: stop after 30 minutes or 2M tokens.

## Budget
- phases: 5.
- max iterations: 12.
- revise limit per failed gate: 3.
- token/time target: 2M tokens / 30 minutes.

## Boundaries
- secrets / credentials: never read or print tokens; redact env files.
- private Telegram / personal data: no egress without explicit request.
- production / public channels: approval required.

## Failure recovery
- validation failure: retry after patch.
- test failure: fix or rollback current slice.
- delivery failure: fail closed with handoff.

## Human approvals
- planning review: required before launch.
- dangerous action approvals: required for secrets, payments, destructive data, DNS, prod.

## ASCII preview
```text
PLAN -> TEST -> REVIEW -> FIX <=3 -> AUDIT -> DONE
```
EOF
bash scripts/validate-loop-design.sh --instantiated "$loop_instantiated" >/dev/null
rm -f "$loop_instantiated"
pass "validate-loop-design instantiated fixture validates"

loop_weak="$(mktemp)"
cat >"$loop_weak" <<'EOF'
# LOOP_DESIGN.md

## Goal
Do the work.

## Context sources
- Repo.

## Host model
- Host.

## Reviewer / judge model
- Judge.

## Verification gates
- Looks good.

## State checkpoints
- State file.

## Stop conditions
- Stop when done.

## Budget
- Enough.

## Boundaries
- Be careful.

## Failure recovery
- Try again.

## Human approvals
- Ask if needed.

## ASCII preview
```text
A -> B
```
EOF
if bash scripts/validate-loop-design.sh --instantiated "$loop_weak" >/dev/null 2>&1; then
  fail "validate-loop-design accepted weak instantiated loop"
fi
rm -f "$loop_weak"
pass "validate-loop-design rejects weak instantiated loop"

loop_missing="$(mktemp)"
cat >"$loop_missing" <<'EOF'
# LOOP_DESIGN.md

## Goal
- Build something real.
EOF
if bash scripts/validate-loop-design.sh "$loop_missing" >/dev/null 2>&1; then
  fail "validate-loop-design accepted missing sections"
fi
rm -f "$loop_missing"
pass "validate-loop-design rejects missing sections"

loop_launch="$(mktemp)"
cp templates/LOOP_DESIGN.md "$loop_launch"
printf '\nSUPERGOAL_GOAL_BODY: invalid\n' >> "$loop_launch"
if bash scripts/validate-loop-design.sh "$loop_launch" >/dev/null 2>&1; then
  fail "validate-loop-design accepted launch body"
fi
rm -f "$loop_launch"
pass "validate-loop-design rejects launch body"

# Private-boundary scan. This installed skill is a private Chip operator
# overlay, so proper names in references are allowed. Raw credentials,
# private keys, JWT-like values, and unredacted token assignments are not.
python3 - <<'PY'
import pathlib, re, sys
files = [p for p in pathlib.Path('.').rglob('*') if p.is_file() and not any(part in {'.git', '.shaw', '.supergoal', '__pycache__'} for part in p.parts) and p.suffix != '.pyc']
patterns = [
    ('private_key_block', re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----')),
    ('github_token', re.compile(r'gh[pousr]_[A-Za-z0-9_]{20,}')),
    ('openai_style_token', re.compile(r'(?<![A-Za-z0-9])sk-[A-Za-z0-9]{32,}')),
    ('jwt', re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')),
    ('env_secret_assignment', re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*=\s*[\"']?[A-Za-z0-9_./+=-]{24,}[\"']?")),
]
violations=[]
for path in files:
    text = path.read_text(errors='ignore')
    for lineno, line in enumerate(text.splitlines(), 1):
        # Placeholder examples are allowed when visibly non-secret.
        if '<' in line and '>' in line:
            continue
        for name, pat in patterns:
            if pat.search(line):
                violations.append(f'{path}:{lineno}:{name}:{line[:160]}')
if violations:
    print('\n'.join(violations), file=sys.stderr)
    sys.exit(1)
PY
pass "private-boundary scan"

python3 -m unittest discover -s tests
pass "phase-01 regression fixtures (expected failures documented)"

python3 - <<'PY'
from pathlib import Path
root = Path('.')
active_files = [p for p in list(root.glob('SKILL.md')) + list((root/'references').glob('*.md')) + list((root/'templates').rglob('*.md')) + list((root/'scripts').glob('*.py'))]
active_files = [p for p in active_files if 'legacy-monolith' not in p.name and p.as_posix() not in {'scripts/test.sh', 'scripts/probe-reference-taxonomy.py'}]
banned = [
    'exactly three native',
    'three native `.md` files',
    'one numbered phase per turn',
    'stop with SUPERGOAL_TURN_YIELD',
    'do not chain phases',
    'execute only current phase',
]
hits=[]
for p in active_files:
    text=p.read_text(errors='ignore')
    for phrase in banned:
        if phrase in text:
            hits.append(f'{p}:{phrase}')
assert not hits, hits
artifact = Path('references/artifact-boundaries.md').read_text(errors='ignore')
for required in ['review_pack_v2', 'LOOP_DESIGN.md', 'pack_version: "review_pack_v2"', 'Planning delivery failure blocks `READY_TO_DISPATCH`']:
    assert required in artifact, required
print('PASS: artifact boundary and stale-phrase contract')
PY

python3 - <<'PY'
from pathlib import Path
import re, yaml
text = Path('SKILL.md').read_text()
fm = re.match(r'^---\n(.*?)\n---\n', text, re.S)
assert fm, 'missing frontmatter'
data = yaml.safe_load(fm.group(1))
assert data['name'] == 'chip-supergoal'
assert len(data['description']) <= 1024
assert len(text.encode()) < 40000, len(text.encode())
required = [
  'Principal+ contract', 'Generated artifacts', 'Reference dispatch',
  'RPD / Senior Gate', 'Loop Design Gate', 'Output Contract'
]
missing = [x for x in required if x not in text]
assert not missing, missing
print('PASS: root architecture contract')
PY

python3 - <<'PY'
from pathlib import Path
actual = []
for p in Path('.').rglob('*.md'):
    if '.git' in p.parts:
        continue
    for n,line in enumerate(p.read_text(errors='ignore').splitlines(),1):
        if line.startswith('SUPERGOAL_GOAL_BODY:'):
            actual.append(f'{p}:{n}')
assert len(actual) == 1 and actual[0].startswith('templates/LAUNCH_GOAL.md:'), actual
launch = Path('templates/LAUNCH_GOAL.md').read_text(errors='ignore')
assert '{{SUPERGOAL_ROOT}}/LOOP_DESIGN.md' in launch, 'launch goal must tell executor to read LOOP_DESIGN.md'
assert not any(line.startswith('SUPERGOAL_GOAL_BODY:') for line in Path('templates/LOOP_DESIGN.md').read_text(errors='ignore').splitlines()), 'LOOP_DESIGN must not be a launch surface'
print('PASS: launch body canonical placement')
PY

python3 - <<'PY'
from pathlib import Path
bundle = '\n'.join(Path(p).read_text(errors='ignore') for p in [
    'SKILL.md', 'templates/PROTOCOL.md', 'templates/LAUNCH_GOAL.md', 'templates/phase-goal.txt', 'references/rpd-review-gates.md'
])
required = [
  'SUPERGOAL_GOAL_BODY:', 'SUPERGOAL_PHASE_START', 'SUPERGOAL_STATUS',
  'SUPERGOAL_PHASE_VERIFY', 'RPD_PLAN_REVIEW', 'RPD_PHASE_REVIEW',
  'RPD_FINAL_REVIEW', 'MEMORY_SAVED', 'SUPERGOAL_PHASE_DONE',
  'SUPERGOAL_TURN_YIELD', 'PREFLIGHT_GREEN', 'PREFLIGHT_RED',
  'AUDIT_START', 'AUDIT_VERIFY', 'AUDIT_GAPS', 'AUDIT_COMPLETE',
  'AUDIT_HANDOFF', 'SUPERGOAL_RUN_COMPLETE', 'FAILURE_PROBE',
  'FAILURE_ESCALATE', 'FAILURE_HANDOFF', 'SUPERGOAL_REVIEW_FILES_BLOCKED',
  'SUPERGOAL_FILES_SENT', 'BLOCKED_BY_APPROVAL', 'READY_FOR_DELETE_APPROVAL',
  'READY_TO_DISPATCH'
]
missing = [x for x in required if x not in bundle]
assert not missing, missing
print('PASS: marker contract')
PY

python3 - <<'PY'
from pathlib import Path
protocol = Path('templates/PROTOCOL.md').read_text(errors='ignore')
assert '.supergoal/scripts/repo-state.sh' in protocol
assert '.supergoal/LOOP_DESIGN.md' in protocol
assert '.supergoal/repo-state.sh' not in protocol
for forbidden in ('references/', 'SKILL.md'):
    assert forbidden not in protocol, f'generated protocol references missing external package path: {forbidden}'
print('PASS: generated protocol is self-contained')
PY

python3 - <<'PY'
from pathlib import Path
repo_state = Path('references/repo-state-comparison.md').read_text(errors='ignore')
assert '.supergoal/scripts/repo-state.sh' in repo_state
assert '.supergoal/repo-state.sh' not in repo_state
assert 'invalid baseline' in repo_state and 'exit 2' in repo_state
assert 'unchanged — existed before baseline' in repo_state and 'exit 3' in repo_state
assert 'still reads `present`' not in repo_state
assert 'ignored-or-non-git existence fallback' not in repo_state
assert 'exists on disk only in non-git fallback mode' in repo_state
preserve = Path('references/supergoal-hermes-update-preservation.md').read_text(errors='ignore')
for required in (
    'hermes_cli/goal_policies.py',
    'gateway/goal_launch.py',
    'thin compatibility shims',
    'skip exactly one post-turn judge pass',
    'Queued slash-command fallback is intentionally not used',
):
    assert required in preserve, required
print('PASS: preservation docs match upstream-shaped rail')
PY

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git check-ignore -q .shaw/state.json || fail ".shaw/ is not ignored"
  git check-ignore -q .env.local || fail ".env.* is not ignored"
  pass "gitignore protects runtime/secrets"
else
  pass "gitignore protects runtime/secrets (skipped outside git)"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

valid="$TMP/phase-valid.md"
cat >"$valid" <<'EOF'
SUPERGOAL_PHASE_START
Phase: 1 of 1 — Build core
Task: Build the core behavior
Mandatory commands: npm test
Acceptance criteria: 3
Evidence required: test output
Depends on phases: none
RPD required: yes
RPD focus: security

## Work
- Implement the core behavior.

## Acceptance criteria
- Core path works.
- Error path is covered.
- Security-sensitive branch is verified.

## Mandatory commands
- npm test

## Evidence required
- Test output with exit code.
EOF
bash scripts/validate-phase.sh "$valid" >/dev/null
pass "validate-phase positive fixture"

invalid_empty="$TMP/phase-empty.md"
cat >"$invalid_empty" <<'EOF'
SUPERGOAL_PHASE_START
Phase: 1 of 1 — Broken
Task: Broken
Mandatory commands: npm test
Acceptance criteria: 0
Evidence required: TBD
Depends on phases: none
RPD required: yes
RPD focus: security

## Work

## Acceptance criteria

## Mandatory commands

## Evidence required
EOF
if bash scripts/validate-phase.sh "$invalid_empty" >/dev/null 2>&1; then
  fail "validate-phase accepted empty sections"
fi
pass "validate-phase rejects empty sections"

invalid_prefix="$TMP/phase-prefix.md"
cat >"$invalid_prefix" <<'EOF'
SUPERGOAL_PHASE_START
Phase: 1 of 1 — Broken
Task: Broken
Mandatory commands: npm test
Acceptance criteria: 1
Evidence required: output
Depends on phases: none
RPD required: no
RPD focus: none

## Workaround
- Not the work section.

## Acceptance criteria-ish
- Not exact.

## Mandatory commands please
- npm test

## Evidence required
- output
EOF
if bash scripts/validate-phase.sh "$invalid_prefix" >/dev/null 2>&1; then
  fail "validate-phase accepted prefix headings"
fi
pass "validate-phase anchors exact headings"

invalid_rpd="$TMP/phase-no-rpd.md"
sed '/^RPD required:/d;/^RPD focus:/d' "$valid" >"$invalid_rpd"
if bash scripts/validate-phase.sh "$invalid_rpd" >/dev/null 2>&1; then
  fail "validate-phase accepted missing RPD metadata"
fi
pass "validate-phase requires RPD metadata"

placeholder="$TMP/phase-placeholder.md"
cat >"$placeholder" <<'EOF'
SUPERGOAL_PHASE_START
Phase: 1 of 1 — Placeholder
Task: Placeholder
Mandatory commands: TBD
Acceptance criteria: 1
Evidence required: TBD
Depends on phases: none
RPD required: no
RPD focus: none

## Work
- TBD

## Acceptance criteria
- none

## Mandatory commands
- {{COMMAND}}

## Evidence required
- ...
EOF
if bash scripts/validate-phase.sh "$placeholder" >/dev/null 2>&1; then
  fail "validate-phase accepted placeholder bullets"
fi
pass "validate-phase rejects placeholder bullets"

template_filled="$TMP/phase-template-filled.md"
sed \
  -e 's/{{N}}/1/g' \
  -e 's/{{TOTAL}}/1/g' \
  -e 's/{{PHASE_NAME}}/Template/g' \
  -e 's/{{ONE_LINE_TASK}}/Fill template/g' \
  -e 's/{{TAGS}}/test/g' \
  -e 's/{{COMMANDS_CSV}}/npm test/g' \
  -e 's/{{CRIT_COUNT}}/3/g' \
  -e 's/{{EVIDENCE_CSV}}/test output/g' \
  -e 's/{{DEPS}}/none/g' \
  -e 's/{{RPD_REQUIRED}}/no/g' \
  -e 's/{{RPD_FOCUS}}/none/g' \
  -e 's/{{WHY_ONE_SENTENCE}}/Because it is needed./g' \
  -e 's/{{WORK_BULLET_1}}/Do the first concrete step./g' \
  -e 's/{{WORK_BULLET_2}}/Do the second concrete step./g' \
  -e 's/{{CRITERION_1}}/Criterion one passes./g' \
  -e 's/{{CRITERION_2}}/Criterion two passes./g' \
  -e 's/{{COMMAND_1}}/npm test/g' \
  -e 's/{{COMMAND_2}}/npm run lint/g' \
  -e 's/{{EVIDENCE_1}}/Test output./g' \
  -e 's/{{EVIDENCE_2}}/Lint output./g' \
  -e 's/{{ANY_PHASE_SPECIFIC_GUIDANCE}}/No extra guidance./g' \
  -e 's/- \.\.\./- Criterion three passes./g' \
  templates/phase-goal.txt > "$template_filled"
bash scripts/validate-phase.sh "$template_filled" >/dev/null
pass "phase template validates after fill"

grep -q 'SUPERGOAL_TURN_YIELD' templates/PROTOCOL.md || fail "protocol missing forced-yield marker"
grep -q 'do not stop at numbered phase boundaries' templates/PROTOCOL.md || fail "protocol missing continuous-execution rule"
grep -q 'Weak blockers are forbidden' templates/PROTOCOL.md || fail "protocol missing weak-blocker guard"
if grep -q 'run at most one numbered phase per assistant turn' templates/PROTOCOL.md; then
  fail "protocol still contains obsolete one-phase-per-turn rule"
fi
pass "protocol continues through phase boundaries"

python3 scripts/probe-dev-history-contracts.py
pass "dev-history hardening contracts"

python3 scripts/test-user-stories.py
pass "user-story contract coverage"

python3 scripts/probe-reference-taxonomy.py
pass "reference taxonomy contracts"

python3 scripts/probe-upstream-goal-compat.py
pass "upstream goal compatibility contracts"

REPO="$TMP/repo"
mkdir "$REPO"
(
  cd "$REPO"
  git init -q
  git config user.email test@example.invalid
  git config user.name Tester
  printf 'old\n' > existing.txt
  git add existing.txt
  git commit -qm baseline
  BASE="$(git rev-parse HEAD)"

  printf 'new\n' > new.txt
  "$ROOT/scripts/repo-state.sh" deliverable "$BASE" new.txt | grep -q 'present' || fail "untracked deliverable not present"

  rm existing.txt
  if "$ROOT/scripts/repo-state.sh" deliverable "$BASE" existing.txt >/tmp/deleted.out 2>&1; then
    cat /tmp/deleted.out >&2
    fail "deleted deliverable passed"
  fi
  grep -q 'deleted vs baseline' /tmp/deleted.out || fail "deleted deliverable did not explain deletion"

  git checkout -- existing.txt
  mkdir -p src
  printf 'old\n' > src/old.txt
  git add src/old.txt
  git commit -qm add-src
  BASE2="$(git rev-parse HEAD)"
  rm src/old.txt
  printf 'new\n' > src/new.txt
  "$ROOT/scripts/repo-state.sh" deliverable "$BASE2" 'src/*.txt' | grep -q 'present' || fail "glob deliverable with new file falsely failed"
  git add -A && git commit -qm glob-reset >/dev/null
  BASE="$(git rev-parse HEAD)"
  set +e
  "$ROOT/scripts/repo-state.sh" deliverable "$BASE" existing.txt >/tmp/unchanged.out 2>&1
  code=$?
  set -e
  if [[ "$code" -eq 0 ]]; then
    cat /tmp/unchanged.out >&2
    fail "unchanged pre-existing deliverable passed"
  fi
  [[ "$code" -eq 3 ]] || fail "unchanged pre-existing exit was $code, expected 3"

  printf 'console.log(1)\n' > debug.js
  if "$ROOT/scripts/repo-state.sh" added-lines bogus >/tmp/bogus.out 2>/tmp/bogus.err; then
    fail "invalid baseline added-lines passed"
  fi
  grep -q 'invalid baseline' /tmp/bogus.err || fail "invalid baseline did not fail closed"
)
pass "repo-state regressions"

env -u USER -u SHELL bash scripts/detect-env.sh >/tmp/detect-env.out
grep -q 'User: redacted' /tmp/detect-env.out || fail "detect-env leaked or missed redacted user"
if grep -Eq '/(home|Users|tmp|opt|var|private|mnt|Volumes)/' /tmp/detect-env.out; then
  cat /tmp/detect-env.out >&2
  fail "detect-env leaked absolute path"
fi
pass "detect-env minimal env"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --check
  pass "git diff --check"
else
  pass "git diff --check (skipped outside git)"
fi
