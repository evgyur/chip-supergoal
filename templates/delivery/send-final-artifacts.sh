#!/usr/bin/env bash
# Optional Unix compatibility wrapper. Python remains the receipt authority.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="${SUPERGOAL_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd -P)}"
TARGET="${SUPERGOAL_DELIVERY_TARGET:?set SUPERGOAL_DELIVERY_TARGET}"
ARCHIVE="${1:?pass the absolute external canonical archive path}"
FORCE="${SUPERGOAL_FORCE_RESEND:-0}"
PYTHON_BIN="${PYTHON:-python3}"
SGCTL="$ROOT/scripts/sgctl.py"

[[ "$FORCE" == "0" || "$FORCE" == "1" ]] || {
  echo "SUPERGOAL_FORCE_RESEND must be 0 or 1" >&2
  exit 2
}
[[ -s "$ARCHIVE" ]] || { echo "missing archive: $ARCHIVE" >&2; exit 2; }
set +e
SHOW_OUTPUT="$("$PYTHON_BIN" "$SGCTL" delivery-reservation-show "$ROOT" \
  --kind final-artifacts 2>/dev/null)"
show_status=$?
set -e
if [[ "$show_status" -eq 0 ]]; then
  CHECK_OUTPUT="$SHOW_OUTPUT"
  if grep -q '"status": "record_required"' <<<"$CHECK_OUTPUT"; then
    RECORD=("$PYTHON_BIN" "$SGCTL" delivery-final-record "$ROOT" \
      --target "$TARGET" --archive "$ARCHIVE" \
      --authorization-json "$CHECK_OUTPUT")
    if [[ "$FORCE" == "1" ]]; then RECORD+=(--force); fi
    "${RECORD[@]}"
    exit 0
  fi
else
  [[ -n "${SUPERGOAL_TRANSPORT_SEND_FILE_CMD:-}" ]] || {
    echo "no real SUPERGOAL_TRANSPORT_SEND_FILE_CMD configured; refusing to reserve or send delivery" >&2
    exit 3
  }
  CHECK=("$PYTHON_BIN" "$SGCTL" delivery-final-check "$ROOT" --target "$TARGET" --archive "$ARCHIVE")
  if [[ "$FORCE" == "1" ]]; then CHECK+=(--force); fi
  set +e
  CHECK_OUTPUT="$("${CHECK[@]}")"
  status=$?
  set -e
  case "$status" in
    0)
      echo "final archive already sent for target+hash"
      exit 0
      ;;
    10) ;;
    *) exit "$status" ;;
  esac
fi
[[ -n "$CHECK_OUTPUT" ]] || {
  echo "delivery check returned an empty authorization" >&2
  exit 3
}

[[ -n "${SUPERGOAL_TRANSPORT_SEND_FILE_CMD:-}" ]] || {
  echo "no real SUPERGOAL_TRANSPORT_SEND_FILE_CMD configured; refusing to send delivery" >&2
  exit 3
}
SEND=("$PYTHON_BIN" "$SGCTL" delivery-final-send "$ROOT" --target "$TARGET" \
  --authorization-json "$CHECK_OUTPUT")
if [[ "$FORCE" == "1" ]]; then SEND+=(--force); fi
"${SEND[@]}" >/dev/null

RECORD=("$PYTHON_BIN" "$SGCTL" delivery-final-record "$ROOT" \
  --target "$TARGET" --archive "$ARCHIVE" \
  --authorization-json "$CHECK_OUTPUT")
if [[ "$FORCE" == "1" ]]; then RECORD+=(--force); fi
"${RECORD[@]}"
