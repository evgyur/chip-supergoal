#!/usr/bin/env bash
# Native Telegram document uploader for SuperGoal startup packs via Hermes CLI.
set -euo pipefail

TARGET="${SUPERGOAL_SEND_TARGET:?missing SUPERGOAL_SEND_TARGET}"
FILE="${SUPERGOAL_SEND_FILE:?missing SUPERGOAL_SEND_FILE}"
CAPTION="${SUPERGOAL_SEND_CAPTION:-[SuperGoal startup pack] ${SUPERGOAL_SEND_LABEL:-$(basename "$FILE")}}"
HERMES_BIN="${SUPERGOAL_HERMES_BIN:-}"

[[ -s "$FILE" ]] || { echo "missing or empty attachment: $FILE" >&2; exit 2; }
[[ "$TARGET" == telegram:* ]] || { echo "explicit telegram:chat_id[:thread_id] target required" >&2; exit 2; }

if [[ -z "$HERMES_BIN" ]]; then
  if command -v hermes >/dev/null 2>&1; then
    HERMES_BIN="$(command -v hermes)"
  elif [[ -x /opt/hermes-agent/venv/bin/hermes ]]; then
    HERMES_BIN=/opt/hermes-agent/venv/bin/hermes
  else
    echo "Hermes CLI not found" >&2
    exit 3
  fi
fi

TARGET_ID="${TARGET#telegram:}"
LIST_JSON="$($HERMES_BIN send --list telegram --json)"
python3 - "$TARGET_ID" "$LIST_JSON" <<'PY'
import json, sys
target_id, raw = sys.argv[1:]
data = json.loads(raw)
ids = {str(x.get('id')) for x in data.get('platforms', {}).get('telegram', [])}
if target_id not in ids:
    raise SystemExit(f'exact Telegram target not found in hermes send list: {target_id}')
PY

BODY="$(printf '%s\n\nMEDIA:%s' "$CAPTION" "$FILE")"
exec "$HERMES_BIN" send --to "$TARGET" --json "$BODY"
