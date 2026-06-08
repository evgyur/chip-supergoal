#!/usr/bin/env bash
# detect-env.sh — public-safe environment recon for greenfield runs.
# Writes markdown to stdout without local paths, user names, emails, or remotes.

set -uo pipefail

echo "# Environment context (greenfield)"
echo
echo "_Generated $(date '+%Y-%m-%d %H:%M:%S')_"
echo

echo "## Project directory"
echo "- Project root: detected"
echo "- Contents: $(ls -A1 2>/dev/null | wc -l | tr -d ' ') entries"
ls -A1 2>/dev/null | head -10 | sed 's/^/  - /'
echo

echo "## System"
echo "- OS: $(uname -srm)"
echo "- Shell: detected"
echo "- User: redacted"
echo

echo "## Toolchains available"
for tool in node npm pnpm yarn bun deno python python3 uv poetry pip go cargo rustc swift xcrun docker make git gh; do
  if command -v "$tool" >/dev/null 2>&1; then
    version=$("$tool" --version 2>/dev/null | head -1)
    version=$(printf '%s' "$version" | sed -E 's#/(home|Users|tmp|opt|var|private|mnt|Volumes)/[^ )]+#<path>#g')
    echo "- \`$tool\` — $version"
  fi
done
echo

echo "## Git"
if git config --global user.name >/dev/null 2>&1 || git config --global user.email >/dev/null 2>&1; then
  echo "- Identity: configured"
else
  echo "- Identity: unset"
fi
echo

if command -v gh >/dev/null 2>&1; then
  echo "## GitHub CLI"
  if gh auth status >/dev/null 2>&1; then
    echo "- Authenticated"
  else
    echo "- Not authenticated"
  fi
fi
echo

echo "_End environment context._"
