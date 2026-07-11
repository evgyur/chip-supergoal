#!/usr/bin/env bash
# Compatibility wrapper: final delivery remains blocked until sgctl verifies Task 6 authority.
set -euo pipefail
ROOT="${SUPERGOAL_ROOT:-$(pwd)/.supergoal}"
OUT="$ROOT/out"
TARGET="${SUPERGOAL_DELIVERY_TARGET:?set SUPERGOAL_DELIVERY_TARGET}"
ARCHIVE="${1:-$OUT/final-artifacts.zip}"
PYTHON_BIN="${PYTHON:-python3}"
SGCTL="$ROOT/scripts/sgctl.py"

[[ -s "$ARCHIVE" ]] || { echo "missing archive: $ARCHIVE" >&2; exit 2; }
"$PYTHON_BIN" "$SGCTL" delivery-final-check "$ROOT" --target "$TARGET" --archive "$ARCHIVE" >/dev/null

[[ -n "${SUPERGOAL_TRANSPORT_SEND_FILE_CMD:-}" ]] || {
  echo "no real SUPERGOAL_TRANSPORT_SEND_FILE_CMD configured; refusing to mint a fake delivery receipt" >&2
  exit 3
}
MESSAGE_ID="$(SUPERGOAL_SEND_TARGET="$TARGET" SUPERGOAL_SEND_FILE="$ARCHIVE" bash -lc "$SUPERGOAL_TRANSPORT_SEND_FILE_CMD")"
[[ -n "$MESSAGE_ID" ]] || { echo "transport returned empty message id" >&2; exit 4; }

"$PYTHON_BIN" "$SGCTL" delivery-final-record "$ROOT" \
  --target "$TARGET" --archive "$ARCHIVE" --message-id "$MESSAGE_ID"
