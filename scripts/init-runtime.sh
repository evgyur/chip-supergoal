#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
exec python3 "$ROOT/scripts/runtime-init.py" "$ROOT"
