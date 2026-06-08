#!/usr/bin/env bash
# validate-phase.sh — verify a phase spec has the required structure.
#
# Usage: validate-phase.sh <path-to-phase-spec.md>
#
# Exits 0 if the file has the required markers, metadata, exact sections, and
# non-placeholder section content. Exits 1 with specific errors otherwise.

set -uo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: validate-phase.sh <path-to-phase-spec.md>" >&2
  exit 2
fi

f="$1"
if [[ ! -f "$f" ]]; then
  echo "validate-phase.sh: file not found: $f" >&2
  exit 2
fi

errors=0
warnings=0

err() { echo "❌ $f: $*" >&2; errors=$((errors + 1)); }
warn() { echo "⚠️  $f: $*" >&2; warnings=$((warnings + 1)); }

require_line() {
  local pattern="$1" label="$2"
  grep -Eq "$pattern" "$f" || err "missing $label"
}

section_bounds() {
  local heading="$1"
  awk -v h="$heading" '
    BEGIN { start=0; end=0 }
    $0 ~ "^##[[:space:]]+" h "[[:space:]]*$" { start=NR; next }
    start && $0 ~ /^##[[:space:]]+/ { end=NR-1; print start ":" end; exit }
    END { if (start && !end) print start ":" NR }
  ' "$f" | head -1
}

require_section_content() {
  local heading="$1" min_items="$2"
  local bounds start end count
  bounds="$(section_bounds "$heading")"
  if [[ -z "$bounds" ]]; then
    err "missing exact section: ## $heading"
    return
  fi
  start="${bounds%%:*}"
  end="${bounds##*:}"
  count="$(awk -v s="$((start + 1))" -v e="$end" '
    NR >= s && NR <= e {
      line=$0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line == "") next
      if (line ~ /^\[Agent will print/) next
      normalized=line
      sub(/^[-*][[:space:]]+/, "", normalized)
      sub(/^[0-9]+\.[[:space:]]+/, "", normalized)
      sub(/^[[:space:]]+/, "", normalized)
      sub(/[[:space:]]+$/, "", normalized)
      lower=tolower(normalized)
      if (normalized ~ /^<.*>$/ || normalized ~ /^\{\{.*\}\}$/) next
      if (lower ~ /^(todo|todo:.*|tbd|none|n\/a|\.\.\.|placeholder|replace me)$/) next
      if (line ~ /^[-*][[:space:]]+/ || line ~ /^[0-9]+\.[[:space:]]+/ || line !~ /^#/) count++
    }
    END { print count + 0 }
  ' "$f")"
  if [[ "$count" -lt "$min_items" ]]; then
    err "section ## $heading has $count substantive item(s), expected at least $min_items"
  fi
}

# Required marker and metadata.
require_line '^SUPERGOAL_PHASE_START([[:space:]]*)$' 'phase-start marker (SUPERGOAL_PHASE_START)'
require_line '^Phase:[[:space:]]+.+$' 'Phase metadata'
require_line '^Task:[[:space:]]+.+$' 'Task metadata'
require_line '^Mandatory commands:[[:space:]]+.+$' 'Mandatory commands metadata'
require_line '^Acceptance criteria:[[:space:]]+.+$' 'Acceptance criteria metadata'
require_line '^Evidence required:[[:space:]]+.+$' 'Evidence required metadata'
require_line '^Depends on phases:[[:space:]]+.+$' 'Depends on phases metadata'
require_line '^RPD required:[[:space:]]+(yes|no)[[:space:]]*$' 'RPD required metadata (yes|no)'
require_line '^RPD focus:[[:space:]]+(security|integration|ux|migration|data-loss|gateway|payments|none)[[:space:]]*$' 'RPD focus metadata enum'

# Required exact sections and minimum useful content.
require_section_content "Work" 1
require_section_content "Acceptance criteria" 1
require_section_content "Mandatory commands" 1
require_section_content "Evidence required" 1

# Advisory quality bar: specs with fewer than 3 criteria are often too weak, but
# not every tiny phase needs 3+ criteria, so keep this as warning only.
crits="$(awk '
  /^##[[:space:]]+Acceptance criteria[[:space:]]*$/ { in_sec=1; next }
  in_sec && /^##[[:space:]]+/ { in_sec=0 }
  in_sec && /^[[:space:]]*[-*][[:space:]]+/ { c++ }
  END { print c + 0 }
' "$f")"
if [[ "$crits" -lt 3 ]]; then
  warn "only $crits acceptance bullet(s) — criteria may be thin"
fi

if (( errors > 0 )); then
  echo "✗ $f: $errors structural error(s), $warnings warning(s)" >&2
  exit 1
fi

lines=$(wc -l < "$f" | tr -d ' ')
echo "✓ $f: structure ok ($lines lines, $crits acceptance bullets, $warnings warnings)"
exit 0
