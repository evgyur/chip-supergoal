#!/usr/bin/env bash
# validate-phase.sh — compatibility wrapper around sgctl semantic phase validation.
# Required phase contract preserved by sgctl: SUPERGOAL_PHASE_START, Work,
# Acceptance criteria, Mandatory commands, Evidence required, RPD required.
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "usage: validate-phase.sh <path-to-phase-spec.md>" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if python3 "$ROOT/scripts/sgctl.py" validate-phase-markdown "$1" >/tmp/sg-validate-phase.$$ 2>/tmp/sg-validate-phase-err.$$; then
  lines=$(wc -l <"$1" | tr -d ' ')
  echo "✓ $1: semantic phase ok ($lines lines)"
  rm -f /tmp/sg-validate-phase.$$ /tmp/sg-validate-phase-err.$$
  exit 0
fi
cat /tmp/sg-validate-phase-err.$$ >&2 || true
rm -f /tmp/sg-validate-phase.$$ /tmp/sg-validate-phase-err.$$
exit 1
