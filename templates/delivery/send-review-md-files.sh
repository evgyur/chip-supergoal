#!/usr/bin/env bash
# Compatibility wrapper: transport files, but delegate receipt authority to package-local sgctl.
set -euo pipefail
ROOT="${SUPERGOAL_ROOT:-$(pwd)/.supergoal}"
TARGET="${SUPERGOAL_DELIVERY_TARGET:?set SUPERGOAL_DELIVERY_TARGET}"
FORCE="${SUPERGOAL_FORCE_RESEND:-0}"
PYTHON_BIN="${PYTHON:-python3}"
SGCTL="$ROOT/scripts/sgctl.py"

if [[ "$FORCE" != "1" ]]; then
  set +e
  "$PYTHON_BIN" "$SGCTL" delivery-review-check "$ROOT" --target "$TARGET" >/dev/null
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

FILES=("$ROOT/LAUNCH_GOAL.md" "$ROOT/LOOP_DESIGN.md")
if [[ -s "$ROOT/RESEARCH.md" ]]; then FILES+=("$ROOT/RESEARCH.md"); fi
FILES+=("$ROOT/ROADMAP.md" "$ROOT/THINKING.md")
for file in "${FILES[@]}"; do
  [[ -s "$file" ]] || { echo "missing review file: $file" >&2; exit 2; }
done

TRANSPORT_SEND_FILE() {
  local file="$1"
  [[ -n "${SUPERGOAL_TRANSPORT_SEND_FILE_CMD:-}" ]] || {
    echo "no real SUPERGOAL_TRANSPORT_SEND_FILE_CMD configured; refusing to mint a fake delivery receipt" >&2
    exit 3
  }
  SUPERGOAL_SEND_TARGET="$TARGET" SUPERGOAL_SEND_FILE="$file" bash -lc "$SUPERGOAL_TRANSPORT_SEND_FILE_CMD"
}

MESSAGE_IDS=()
for file in "${FILES[@]}"; do
  message_id="$(TRANSPORT_SEND_FILE "$file")"
  [[ -n "$message_id" ]] || { echo "transport returned empty message id for $file" >&2; exit 4; }
  MESSAGE_IDS+=("$message_id")
done

RECORD=("$PYTHON_BIN" "$SGCTL" delivery-review-record "$ROOT" --target "$TARGET")
if [[ "$FORCE" == "1" ]]; then RECORD+=(--force); fi
for message_id in "${MESSAGE_IDS[@]}"; do RECORD+=(--message-id "$message_id"); done
"${RECORD[@]}"
