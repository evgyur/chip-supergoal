#!/usr/bin/env bash
# repo-state.sh — evaluate the COMPLETE working-tree state relative to a baseline commit.
#
# Usage:
#   repo-state.sh deliverable   <baseline> <path>
#       -> present (0) | missing/deleted (1) | invalid baseline (2) | unchanged pre-existing (3)
#   repo-state.sh changed-files <baseline>
#       -> newline-delimited paths changed since baseline (tracked + untracked + deleted)
#   repo-state.sh added-lines   <baseline>
#       -> every added/new line since baseline: tracked-diff '+' lines plus untracked file bodies

set -uo pipefail

in_git_repo() { git rev-parse --is-inside-work-tree >/dev/null 2>&1; }

baseline_ok() {
  local b="${1:-}"
  [ -n "$b" ] || return 1
  [ "$b" = "no-git" ] && return 1
  git rev-parse --verify --quiet "${b}^{commit}" >/dev/null 2>&1
}

invalid_baseline() {
  local baseline="${1:-}"
  echo "repo-state.sh: invalid baseline: ${baseline:-<empty>}" >&2
  return 2
}

name_status_for_path() {
  local baseline="$1" path="$2"
  git diff --name-status "$baseline" -- "$path" 2>/dev/null || true
}

cmd_deliverable() {
  local baseline="$1" path="$2"

  if in_git_repo; then
    baseline_ok "$baseline" || invalid_baseline "$baseline" || return $?

    local ns
    ns="$(name_status_for_path "$baseline" "$path")"

    # Tracked change vs baseline: committed, staged, unstaged, renamed, or copied.
    # A glob/directory deliverable can have both deleted old files and added/modified
    # new files; treat it as present if any matching non-deletion change exists.
    if printf '%s\n' "$ns" | awk 'NF && $1 !~ /^D/ { found=1 } END { exit found ? 0 : 1 }'; then
      local stat
      stat="$(git diff --stat "$baseline" -- "$path" 2>/dev/null || true)"
      printf 'present — changed vs baseline (%s)\n' \
        "$(printf '%s' "$stat" | tail -1 | sed 's/^[[:space:]]*//')"
      return 0
    fi

    # Brand-new untracked deliverable (diff-invisible). Git pathspec matching does
    # not reliably cover shell-style globs for untracked files, so also check
    # compgen for glob paths and test each candidate against git's untracked list.
    local untracked glob_match
    untracked="$(git ls-files --others --exclude-standard -- "$path" 2>/dev/null | head -1 || true)"
    glob_match="$(compgen -G "$path" 2>/dev/null | head -1 || true)"
    if [ -n "$untracked" ]; then
      printf 'present — untracked new file (%s)\n' "$untracked"
      return 0
    fi
    if [ -n "$glob_match" ]; then
      while IFS= read -r candidate; do
        [ -n "$candidate" ] || continue
        if [ -n "$(git ls-files --others --exclude-standard -- "$candidate" 2>/dev/null | head -1 || true)" ]; then
          printf 'present — untracked glob file (%s)\n' "$candidate"
          return 0
        fi
      done < <(compgen -G "$path" 2>/dev/null || true)
      if [ -n "$ns" ]; then
        printf 'present — glob has current file (%s)\n' "$glob_match"
        return 0
      fi
    fi

    # If the only matching diff entries are deletions, the deliverable is missing.
    if printf '%s\n' "$ns" | awk 'NF && $1 ~ /^D/ { found=1 } END { exit found ? 0 : 1 }'; then
      printf 'missing — deleted vs baseline\n'
      return 1
    fi

    # Existing but unchanged files are not proof of delivery unless the roadmap
    # explicitly says the deliverable was pre-existing / verification-only.
    if [ -e "$path" ] || compgen -G "$path" >/dev/null 2>&1 || [ -n "$(git ls-files -- "$path" 2>/dev/null | head -1 || true)" ]; then
      printf 'unchanged — existed before baseline\n'
      return 3
    fi

    printf 'missing\n'
    return 1
  fi

  # Non-git fallback is existence-only. A git repo with an invalid baseline fails
  # closed above; this branch is for explicit non-repo/no-git workspaces.
  if [ -e "$path" ] || compgen -G "$path" >/dev/null 2>&1; then
    printf 'present — exists on disk (no git baseline)\n'
    return 0
  fi
  printf 'missing\n'
  return 1
}

cmd_changed_files() {
  local baseline="$1"
  if in_git_repo; then
    baseline_ok "$baseline" || invalid_baseline "$baseline" || return $?
    {
      git diff --name-only "$baseline" 2>/dev/null || true
      git ls-files --others --exclude-standard 2>/dev/null || true
    } | LC_ALL=C sort -u | sed '/^$/d'
    return 0
  fi
  return 0
}

cmd_added_lines() {
  local baseline="$1"
  if in_git_repo; then
    baseline_ok "$baseline" || invalid_baseline "$baseline" || return $?
    git diff "$baseline" 2>/dev/null | grep '^+' | grep -v '^+++' | sed 's/^+//' || true
    git ls-files --others --exclude-standard -z 2>/dev/null | while IFS= read -r -d '' f; do
      [ -f "$f" ] && LC_ALL=C grep -Iq . "$f" 2>/dev/null && sed 's/^//' -- "$f"
    done
    return 0
  fi
  return 0
}

sub="${1:-}"
shift 2>/dev/null || true
case "$sub" in
  deliverable)
    [ "$#" -ge 2 ] || { echo "usage: repo-state.sh deliverable <baseline> <path>" >&2; exit 2; }
    cmd_deliverable "$1" "$2"
    ;;
  changed-files)
    [ "$#" -ge 1 ] || { echo "usage: repo-state.sh changed-files <baseline>" >&2; exit 2; }
    cmd_changed_files "$1"
    ;;
  added-lines)
    [ "$#" -ge 1 ] || { echo "usage: repo-state.sh added-lines <baseline>" >&2; exit 2; }
    cmd_added_lines "$1"
    ;;
  ""|-h|--help|help)
    cat >&2 <<'EOF'
repo-state.sh — evaluate complete working-tree state vs a baseline commit.

  repo-state.sh deliverable   <baseline> <path>   present|missing|unchanged, exit 0|1|3
  repo-state.sh changed-files <baseline>          paths changed since baseline
  repo-state.sh added-lines   <baseline>          added/new lines since baseline

In a git repo, an invalid baseline fails closed with exit 2. Outside git, the
script degrades to filesystem checks for deliverables and empty changed/added output.
EOF
    exit 2
    ;;
  *)
    echo "repo-state.sh: unknown subcommand '$sub' (try deliverable|changed-files|added-lines)" >&2
    exit 2
    ;;
esac
