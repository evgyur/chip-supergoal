#!/usr/bin/env bash
# validate-phase.sh — compatibility wrapper around sgctl semantic phase validation.
# Required phase contract preserved by sgctl: SUPERGOAL_PHASE_START, Work,
# Acceptance criteria, Mandatory commands, Evidence required, RPD required.
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "usage: validate-phase.sh <phase-number|path-to-phase-spec.md>" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE_SPEC="$1"
if [[ "$PHASE_SPEC" =~ ^[0-9]+$ ]]; then
  printf -v PHASE_NUMBER '%02d' "$((10#$PHASE_SPEC))"
  PHASE_SPEC="$ROOT/phases/phase-$PHASE_NUMBER.md"
elif [[ "$PHASE_SPEC" != /* ]]; then
  PHASE_SPEC="$(cd "$(dirname "$PHASE_SPEC")" 2>/dev/null && pwd)/$(basename "$PHASE_SPEC")"
fi
if [[ ! -f "$PHASE_SPEC" ]]; then
  echo "phase spec not found: $PHASE_SPEC" >&2
  exit 2
fi
if python3 "$ROOT/scripts/sgctl.py" validate-phase-markdown "$PHASE_SPEC" >/tmp/sg-validate-phase.$$ 2>/tmp/sg-validate-phase-err.$$; then
  lines=$(wc -l < "$PHASE_SPEC" | tr -d ' ')
  echo "✓ $PHASE_SPEC: semantic phase ok ($lines lines)"
  rm -f /tmp/sg-validate-phase.$$ /tmp/sg-validate-phase-err.$$
  exit 0
fi
cat /tmp/sg-validate-phase-err.$$ >&2 || true
rm -f /tmp/sg-validate-phase.$$ /tmp/sg-validate-phase-err.$$
exit 1
