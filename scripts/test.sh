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
  scripts/repo-state.sh \
  templates/PROTOCOL.md \
  templates/ROADMAP.md \
  templates/RESEARCH.md \
  references/rpd-review-gates.md; do
  [[ -f "$required" ]] || fail "missing required asset: $required"
done
pass "install layout contains required assets"

# Public-safety scan over tracked files. The lowercase repo/command identifier
# `chip-supergoal` is allowed; capitalized personal/operator labels are not.
python3 - <<'PY'
import pathlib, subprocess, sys
terms = [
    'Ev'+'geny', 'Human'+'20', '157'+'.', '72'+'.',
    '/home/'+'hermes', ''.join(map(chr,[103,104,111,95])), ''.join(map(chr,[115,107,45])), '-----'+'BEGIN', 'auth'+'.json',
    ''.join(map(chr,[79,112,101,110,67,108,97,119])), ''.join(map(chr,[67,108,97,119])), ''.join(map(chr,[67,104,105,112])),
]

try:
    files = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'], text=True, stderr=subprocess.DEVNULL).splitlines()
except Exception:
    files = [str(p) for p in pathlib.Path('.').rglob('*') if p.is_file() and not any(part in {'.git', '.shaw', '.supergoal'} for part in p.parts)]
violations=[]
for file in files:
    text=pathlib.Path(file).read_text(errors='ignore')
    for lineno,line in enumerate(text.splitlines(),1):
        if any(t in line for t in terms) or __import__('re').search(r'-100[0-9]{6,}', line):
            violations.append(f'{file}:{lineno}:{line}')
if violations:
    print('\n'.join(violations), file=sys.stderr)
    sys.exit(1)
PY
pass "privacy scan"

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

grep -q 'Hermes mode' README.md || fail "README missing Hermes mode"
grep -q 'Codex mode' README.md || fail "README missing Codex mode"
grep -q 'CODEX_GOAL_OBJECTIVE' SKILL.md || fail "SKILL missing Codex fallback objective"
grep -q 'built-in goal mechanism' SKILL.md || fail "SKILL missing Codex built-in goal handoff"
grep -q 'load/use the `shaw` skill' templates/PROTOCOL.md || fail "PROTOCOL missing Codex Shaw rule"
grep -q 'Codex mode' references/goal-format.md || fail "goal-format missing Codex mode"
pass "mode docs and Codex Shaw contract"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --check
  pass "git diff --check"
else
  pass "git diff --check (skipped outside git)"
fi
