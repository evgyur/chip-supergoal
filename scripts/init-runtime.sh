#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SEED="$ROOT/runtime-seed"
OUT="$ROOT/out"
RUNTIME="$OUT/runtime"
LOCK="$OUT/.runtime-init.lock"
REQUIRED=(PLAN.md TODO.md MEMORY.md STATUS.md RUN_LOG.md CHECKS.md REVIEW.md)

[[ -d "$ROOT" && ! -L "$ROOT" ]] || { echo "invalid package root: $ROOT" >&2; exit 2; }
[[ -d "$SEED" && ! -L "$SEED" ]] || { echo "missing runtime seed: $SEED" >&2; exit 2; }
mkdir -p "$OUT"

if [[ -d "$RUNTIME" ]]; then
  for name in "${REQUIRED[@]}"; do
    [[ -f "$RUNTIME/$name" && ! -L "$RUNTIME/$name" ]] || { echo "runtime incomplete: $RUNTIME/$name" >&2; exit 3; }
  done
  echo "runtime already initialized: $RUNTIME"
  exit 0
fi

if ! mkdir "$LOCK" 2>/dev/null; then
  echo "runtime initialization lock held: $LOCK" >&2
  exit 4
fi

TMP="$OUT/.runtime-init.$$"
cleanup() {
  rm -rf -- "$TMP"
  rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
umask 077
mkdir "$TMP"

for name in "${REQUIRED[@]}"; do
  source="$SEED/$name"
  [[ -f "$source" && ! -L "$source" ]] || { echo "missing seed file: $source" >&2; exit 2; }
  cp -- "$source" "$TMP/$name"
done

if [[ -e "$RUNTIME" ]]; then
  echo "runtime appeared during initialization: $RUNTIME" >&2
  exit 4
fi
mv -- "$TMP" "$RUNTIME"
rmdir "$LOCK"
trap - EXIT INT TERM
echo "runtime initialized: $RUNTIME"
