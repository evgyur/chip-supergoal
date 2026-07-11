#!/usr/bin/env bash
# Unix shell gates around the cross-platform Python test authority.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "SHELL_GATE_PASS name=$1"
}

mode="${1:-}"
if [[ $# -gt 1 ]]; then
  fail "usage: scripts/test.sh [--shell-only]"
fi
case "$mode" in
"" | --shell-only) ;;
*) fail "usage: scripts/test.sh [--shell-only]" ;;
esac

shell_sources=(scripts/*.sh templates/delivery/*.sh)
bash -n "${shell_sources[@]}"
pass "shell-syntax"

shellcheck "${shell_sources[@]}"
pass "shellcheck"

shfmt -d -i 2 "${shell_sources[@]}"
pass "shfmt"

# Compatibility wrappers must preserve the native Python validators' exit
# semantics, not merely parse as valid shell.
bash scripts/validate-phase.sh tests/fixtures/v2-valid/phase-valid.md >/dev/null
if bash scripts/validate-phase.sh \
  tests/fixtures/v2-invalid/phase-99-of-1-rpd-mismatch.md >/dev/null 2>&1; then
  fail "validate-phase wrapper accepted invalid phase"
fi
bash scripts/validate-loop-design.sh --instantiated \
  tests/fixtures/v2-valid/loop-design-valid.md >/dev/null
if bash scripts/validate-loop-design.sh --instantiated \
  tests/fixtures/v2-invalid/loop-one-word.md >/dev/null 2>&1; then
  fail "validate-loop-design wrapper accepted invalid design"
fi
pass "validator-wrappers"

TMP="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

# repo-state.sh is intentionally a Unix compatibility surface. Exercise its
# baseline, untracked, deletion, glob, and unchanged-result contracts here.
REPO="$TMP/repo"
mkdir "$REPO"
(
  cd "$REPO"
  git init -q
  git config user.email test@example.invalid
  git config user.name Tester
  printf 'old\n' >existing.txt
  git add existing.txt
  git commit -qm baseline
  baseline="$(git rev-parse HEAD)"

  printf 'new\n' >new.txt
  "$ROOT/scripts/repo-state.sh" deliverable "$baseline" new.txt |
    grep -q 'present' || fail "untracked deliverable was not present"

  rm existing.txt
  if "$ROOT/scripts/repo-state.sh" deliverable "$baseline" existing.txt \
    >"$TMP/deleted.out" 2>&1; then
    fail "deleted deliverable passed"
  fi
  grep -q 'deleted vs baseline' "$TMP/deleted.out" ||
    fail "deleted deliverable did not explain deletion"

  git checkout -- existing.txt
  mkdir src
  printf 'old\n' >src/old.txt
  git add src/old.txt
  git commit -qm add-src
  baseline="$(git rev-parse HEAD)"
  rm src/old.txt
  printf 'new\n' >src/new.txt
  "$ROOT/scripts/repo-state.sh" deliverable "$baseline" 'src/*.txt' |
    grep -q 'present' || fail "glob replacement was not present"

  git add -A
  git commit -qm reset
  baseline="$(git rev-parse HEAD)"
  set +e
  "$ROOT/scripts/repo-state.sh" deliverable "$baseline" existing.txt \
    >"$TMP/unchanged.out" 2>&1
  code=$?
  set -e
  [[ "$code" -eq 3 ]] || fail "unchanged deliverable exit was $code, expected 3"
  grep -q 'unchanged' "$TMP/unchanged.out" ||
    fail "unchanged deliverable lacked diagnostic"

  set +e
  "$ROOT/scripts/repo-state.sh" added-lines bogus \
    >"$TMP/bogus.out" 2>"$TMP/bogus.err"
  code=$?
  set -e
  [[ "$code" -eq 2 ]] || fail "invalid baseline exit was $code, expected 2"
  grep -q 'invalid baseline' "$TMP/bogus.err" ||
    fail "invalid baseline did not fail closed"
)
pass "repo-state-runtime"

env -u USER -u SHELL bash scripts/detect-env.sh >"$TMP/detect-env.out"
grep -q 'User: redacted' "$TMP/detect-env.out" ||
  fail "detect-env did not redact the user"
if grep -Eq '/(home|Users|tmp|opt|var|private|mnt|Volumes)/' \
  "$TMP/detect-env.out"; then
  fail "detect-env leaked an absolute path"
fi
pass "detect-env-privacy"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git check-ignore -q .shaw/state.json || fail ".shaw/ is not ignored"
  git check-ignore -q .env.local || fail ".env.* is not ignored"
fi
pass "gitignore-runtime-secrets"

cleanup
trap - EXIT

if [[ "$mode" == "--shell-only" ]]; then
  echo "SHELL_TEST_SUMMARY total=7 passed=7 failed=0"
  exit 0
fi

# scripts/test.py owns the cross-platform privacy/reference suite, unit tests,
# user stories, probes, and git diff --check gate.
python3 scripts/test.py --skip-shell
