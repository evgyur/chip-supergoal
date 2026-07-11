#!/usr/bin/env bash
# Optional Unix delegate. Python is the sole archive policy authority.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="${SUPERGOAL_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd -P)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
[[ $# -eq 1 ]] || {
  echo "usage: package-final-artifacts.sh /absolute/external/archive.zip" >&2
  exit 2
}
exec "$PYTHON_BIN" "$ROOT/scripts/sgctl.py" archive "$ROOT" \
  --out "$1" \
  --manifest "$ROOT/out/final-artifacts-manifest.json"
