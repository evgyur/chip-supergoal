#!/usr/bin/env bash
# Compatibility wrapper: transport files, but delegate receipt authority to package-local sgctl.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="${SUPERGOAL_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd -P)}"
TARGET="${SUPERGOAL_DELIVERY_TARGET:?set SUPERGOAL_DELIVERY_TARGET}"
FORCE="${SUPERGOAL_FORCE_RESEND:-0}"
PYTHON_BIN="${PYTHON:-python3}"
SGCTL="$ROOT/scripts/sgctl.py"

[[ "$FORCE" == "0" || "$FORCE" == "1" ]] || {
  echo "SUPERGOAL_FORCE_RESEND must be 0 or 1" >&2
  exit 2
}
set +e
SHOW_OUTPUT="$("$PYTHON_BIN" "$SGCTL" delivery-reservation-show "$ROOT" \
  --kind review-md-files 2>/dev/null)"
show_status=$?
set -e
if [[ "$show_status" -eq 0 ]]; then
  CHECK_OUTPUT="$SHOW_OUTPUT"
else
  [[ -n "${SUPERGOAL_TRANSPORT_SEND_FILE_CMD:-}" ]] || {
    echo "no real SUPERGOAL_TRANSPORT_SEND_FILE_CMD configured; refusing to reserve or send delivery" >&2
    exit 3
  }
  CHECK=("$PYTHON_BIN" "$SGCTL" delivery-review-check "$ROOT" --target "$TARGET")
  if [[ "$FORCE" == "1" ]]; then CHECK+=(--force); fi
  set +e
  CHECK_OUTPUT="$("${CHECK[@]}")"
  status=$?
  set -e
  case "$status" in
    0)
      echo "review files already sent for target+hash"
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
if ! grep -q '"status": "record_required"' <<<"$CHECK_OUTPUT"; then
  [[ -n "${SUPERGOAL_TRANSPORT_SEND_FILE_CMD:-}" ]] || {
    echo "no real SUPERGOAL_TRANSPORT_SEND_FILE_CMD configured; refusing to send delivery" >&2
    exit 3
  }
  SEND=("$PYTHON_BIN" "$SGCTL" delivery-review-send "$ROOT" --target "$TARGET" \
    --authorization-json "$CHECK_OUTPUT")
  if [[ "$FORCE" == "1" ]]; then SEND+=(--force); fi
  "${SEND[@]}" >/dev/null
fi

RECORD=("$PYTHON_BIN" "$SGCTL" delivery-review-record "$ROOT" --target "$TARGET" \
  --authorization-json "$CHECK_OUTPUT")
if [[ "$FORCE" == "1" ]]; then RECORD+=(--force); fi
"${RECORD[@]}"
