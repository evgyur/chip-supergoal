#!/usr/bin/env bash
# Send exactly the three Chip-facing SuperGoal startup documents.
set -euo pipefail
ROOT="${SUPERGOAL_ROOT:-$(pwd)/.supergoal}"
OUT="$ROOT/out"
mkdir -p "$OUT"
chmod 700 "$OUT"
SEALED_TARGET="$(python3 - <<'PY' "$ROOT/CONTRACT.json"
import json, sys
contract = json.load(open(sys.argv[1], encoding='utf-8'))
delivery = contract.get('delivery', {})
files = delivery.get('files')
assert files == ['THINKING.md', 'ROADMAP.md', 'LAUNCH_GOAL.md'], 'contract startup inventory/order mismatch'
target = delivery.get('telegram_thread')
assert isinstance(target, str) and target.startswith('telegram:') and target.count(':') == 2, 'missing exact sealed Telegram chat+thread target'
print(target)
PY
)"
REQUESTED_TARGET="${SUPERGOAL_DELIVERY_TARGET:-$SEALED_TARGET}"
[[ "$REQUESTED_TARGET" == "$SEALED_TARGET" ]] || { echo "delivery target differs from sealed CONTRACT target" >&2; exit 2; }
TARGET="$SEALED_TARGET"
FORCE="${SUPERGOAL_FORCE_RESEND:-0}"
RUN_ID="${SUPERGOAL_DELIVERY_RUN_ID:-primary}"
[[ "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid SUPERGOAL_DELIVERY_RUN_ID" >&2; exit 2; }

# LAUNCH_GOAL.md is deliberately last: Chip replies /goal to the newest standalone document.
FILES=(
  "$ROOT/THINKING.md"
  "$ROOT/ROADMAP.md"
  "$ROOT/LAUNCH_GOAL.md"
)
for f in "${FILES[@]}"; do [[ -s "$f" ]] || { echo "missing canonical startup file: $f" >&2; exit 2; }; done

mapfile -t FILE_LABELS < <(python3 - <<'PY' "$ROOT" "${FILES[@]}"
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
for raw in sys.argv[2:]:
    path = Path(raw).resolve()
    try:
        print(path.relative_to(root).as_posix())
    except ValueError:
        print(path.name)
PY
)
[[ "${#FILE_LABELS[@]}" -eq 3 ]] || { echo "startup inventory must contain exactly three files" >&2; exit 2; }
[[ "${FILE_LABELS[*]}" == "THINKING.md ROADMAP.md LAUNCH_GOAL.md" ]] || { echo "startup inventory/order must be THINKING.md, ROADMAP.md, LAUNCH_GOAL.md" >&2; exit 2; }

if [[ "$RUN_ID" == "primary" ]]; then
  RECEIPT="$OUT/review-md-files-delivery-receipt.json"
  TRANSPORT_RECEIPT="$OUT/review-md-files-transport-receipt.json"
else
  RECEIPT="$OUT/review-md-files-delivery-receipt-$RUN_ID.json"
  TRANSPORT_RECEIPT="$OUT/review-md-files-transport-receipt-$RUN_ID.json"
fi
HASHES="$(python3 - <<'PY' "$ROOT" "${FILES[@]}"
from pathlib import Path
import hashlib, json, sys
root = Path(sys.argv[1]).resolve()
out = {}
for raw in sys.argv[2:]:
    path = Path(raw).resolve()
    try:
        label = path.relative_to(root).as_posix()
    except ValueError:
        label = path.name
    out[label] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(out, sort_keys=True))
PY
)"
LABELS_JSON="$(python3 - <<'PY' "${FILE_LABELS[@]}"
import json, sys
print(json.dumps(sys.argv[1:]))
PY
)"

if [[ -f "$RECEIPT" && "$FORCE" != "1" ]] && python3 - <<'PY' "$RECEIPT" "$TARGET" "$HASHES" "$LABELS_JSON"
import json, sys
path, target, hashes, labels = sys.argv[1:]
try:
    r = json.load(open(path, encoding='utf-8'))
    h = json.loads(hashes)
    ordered = json.loads(labels)
    req = {'ok','sent','readback_verified','kind','pack_version','target','files','hashes','message_ids','file_message_ids','readback_items','sender'}
    assert not (req - set(r)), 'missing fields'
    assert r['ok'] is True and r['sent'] is True and r['readback_verified'] is True
    assert r['kind'] == 'startup-files' and r['pack_version'] == 'startup_pack_v4'
    assert r['target'] == target and r['hashes'] == h
    assert r['files'] == ordered and ordered[-1] == 'LAUNCH_GOAL.md'
    assert isinstance(r['message_ids'], list) and len(r['message_ids']) == len(ordered)
    assert all(str(x).strip() for x in r['message_ids'])
    assert r['file_message_ids'] == dict(zip(ordered, r['message_ids']))
    assert len(r['readback_items']) == len(ordered) and all(x.get('readback_verified') is True for x in r['readback_items'])
    assert isinstance(r['sender'], dict) and str(r['sender'].get('id') or r['sender'].get('username') or '').strip()
except Exception as exc:
    print(f'receipt reuse rejected: {exc}', file=sys.stderr)
    raise SystemExit(1)
PY
then
  echo "startup pack already sent for target+hash"
  exit 0
fi

if [[ -z "${SUPERGOAL_TRANSPORT_SEND_FILE_CMD:-}" ]]; then
  DEFAULT_TRANSPORT="$ROOT/templates/delivery/send-file-via-hermes-cli.sh"
  [[ -f "$DEFAULT_TRANSPORT" ]] || {
    echo "missing default Hermes CLI attachment transport: $DEFAULT_TRANSPORT" >&2
    exit 3
  }
  SUPERGOAL_TRANSPORT_SEND_FILE_CMD="bash '$DEFAULT_TRANSPORT'"
fi

ATTEMPTS_DIR="$OUT/startup-delivery-attempts/$RUN_ID"
mkdir -p "$ATTEMPTS_DIR"

TRANSPORT_SEND_FILE() {
  local file="$1" label="$2" caption raw parsed rc attempt_file file_hash recovery
  if [[ "$label" == "LAUNCH_GOAL.md" ]]; then
    caption="[SuperGoal START · reply /goal to this file] LAUNCH_GOAL.md"
  else
    caption="[SuperGoal startup pack] $label"
  fi
  file_hash="$(sha256sum "$file" | cut -d' ' -f1)"
  attempt_file="$ATTEMPTS_DIR/${label}.json"

  if [[ -f "$attempt_file" ]]; then
    set +e
    recovery="$(python3 - <<'PY' "$attempt_file" "$TARGET" "$label" "$file_hash"
import json, sys
path, target, label, file_hash = sys.argv[1:]
r = json.load(open(path, encoding='utf-8'))
if r.get('target') != target or r.get('label') != label or r.get('file_sha256') != file_hash:
    print('attempt intent mismatch', file=sys.stderr)
    raise SystemExit(21)
if r.get('state') == 'accepted' and str(r.get('message_id', '')).strip():
    print(r['message_id'])
    raise SystemExit(0)
if r.get('state') in {'prepared', 'unknown_delivery'}:
    raise SystemExit(20)
raise SystemExit(21)
PY
)"
    rc=$?
    set -e
    if [[ "$rc" -eq 0 && -n "$recovery" ]]; then
      printf '%s\n' "$recovery"
      return 0
    fi
    if [[ "$rc" -eq 20 ]]; then
      printf 'UNKNOWN_DELIVERY for %s; canonical read-only Telegram lookup must recover a message_id before any resend: %s\n' "$label" "$attempt_file" >&2
      return 20
    fi
    printf 'delivery attempt intent mismatch or corruption for %s: %s\n' "$label" "$attempt_file" >&2
    return 21
  fi

  python3 - <<'PY' "$attempt_file" "$TARGET" "$label" "$file" "$file_hash"
import datetime, json, os, sys, tempfile, uuid
path, target, label, file_path, file_hash = sys.argv[1:]
record = {
    'schema': 'chip-supergoal.startup-delivery-attempt.v1',
    'attempt_id': str(uuid.uuid4()),
    'state': 'prepared',
    'target': target,
    'label': label,
    'file': file_path,
    'file_sha256': file_hash,
    'prepared_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
directory = os.path.dirname(path)
fd, temp = tempfile.mkstemp(prefix='.attempt-', dir=directory, text=True)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
PY

  set +e
  raw="$(SUPERGOAL_SEND_TARGET="$TARGET" SUPERGOAL_SEND_FILE="$file" SUPERGOAL_SEND_LABEL="$label" SUPERGOAL_SEND_CAPTION="$caption" bash -lc "$SUPERGOAL_TRANSPORT_SEND_FILE_CMD" 2>&1)"
  rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    set +e
    parsed="$(python3 - <<'PY' "$raw"
import json, re, sys
raw = sys.argv[1].strip()
if not raw:
    raise SystemExit(1)
try:
    obj = json.loads(raw)
except Exception:
    if re.fullmatch(r'[A-Za-z0-9:_-]+', raw):
        print(raw)
        raise SystemExit(0)
    raise SystemExit(1)
for candidate in (
    obj.get('message_id') if isinstance(obj, dict) else None,
    obj.get('data', {}).get('message_id') if isinstance(obj, dict) and isinstance(obj.get('data'), dict) else None,
    obj.get('result', {}).get('message_id') if isinstance(obj, dict) and isinstance(obj.get('result'), dict) else None,
):
    if candidate is not None and str(candidate).strip():
        print(candidate)
        raise SystemExit(0)
raise SystemExit(1)
PY
)"
    rc=$?
    set -e
  fi

  if [[ "$rc" -ne 0 || -z "${parsed:-}" ]]; then
    python3 - <<'PY' "$attempt_file" "$raw"
import datetime, json, os, sys, tempfile
path, detail = sys.argv[1:]
r = json.load(open(path, encoding='utf-8'))
r['state'] = 'unknown_delivery'
r['unknown_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
r['transport_detail_tail'] = detail[-1000:]
fd, temp = tempfile.mkstemp(prefix='.attempt-', dir=os.path.dirname(path), text=True)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(r, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
finally:
    if os.path.exists(temp): os.unlink(temp)
PY
    printf 'UNKNOWN_DELIVERY for %s; no automatic retry is allowed: %s\n' "$label" "$attempt_file" >&2
    return 20
  fi

  python3 - <<'PY' "$attempt_file" "$parsed"
import datetime, json, os, sys, tempfile
path, message_id = sys.argv[1:]
r = json.load(open(path, encoding='utf-8'))
r['state'] = 'accepted'
r['message_id'] = message_id
r['accepted_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
fd, temp = tempfile.mkstemp(prefix='.attempt-', dir=os.path.dirname(path), text=True)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(r, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
finally:
    if os.path.exists(temp): os.unlink(temp)
PY
  printf '%s\n' "$parsed"
}

MESSAGE_IDS=()
SEND_INTERVAL_SECONDS="${SUPERGOAL_SEND_INTERVAL_SECONDS:-2.5}"
for i in "${!FILES[@]}"; do
  msg_id="$(TRANSPORT_SEND_FILE "${FILES[$i]}" "${FILE_LABELS[$i]}")"
  [[ -n "$msg_id" ]] || { echo "transport returned empty message id for ${FILE_LABELS[$i]}" >&2; exit 4; }
  MESSAGE_IDS+=("$msg_id")
  if (( i + 1 < ${#FILES[@]} )); then sleep "$SEND_INTERVAL_SECONDS"; fi
done

IDS_JSON="$(python3 - <<'PY' "${MESSAGE_IDS[@]}"
import json, sys
print(json.dumps(sys.argv[1:]))
PY
)"
python3 - <<'PY' "$TRANSPORT_RECEIPT" "$TARGET" "$HASHES" "$LABELS_JSON" "$IDS_JSON" "$RUN_ID"
import datetime, json, sys
path, target, hashes, labels, ids, run_id = sys.argv[1:]
h = json.loads(hashes)
ordered = json.loads(labels)
message_ids = json.loads(ids)
assert ordered == ['THINKING.md', 'ROADMAP.md', 'LAUNCH_GOAL.md']
assert len(message_ids) == 3 and all(str(x).strip() for x in message_ids)
receipt = {
    'ok': False,
    'sent': True,
    'readback_verified': False,
    'kind': 'startup-files-transport',
    'pack_version': 'startup_pack_v4',
    'delivery_run_id': run_id,
    'target': target,
    'files': ordered,
    'hashes': h,
    'message_ids': message_ids,
    'file_message_ids': dict(zip(ordered, message_ids)),
    'launch_file': 'LAUNCH_GOAL.md',
    'launch_message_id': message_ids[-1],
    'sent_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
json.dump(receipt, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2, sort_keys=True)
PY

VERIFY_READBACK="$ROOT/templates/delivery/verify-startup-delivery-readback.py"
[[ -f "$VERIFY_READBACK" ]] || { echo "missing readback verifier: $VERIFY_READBACK" >&2; exit 3; }
if [[ -z "${SUPERGOAL_DELIVERY_READBACK_RECEIPT:-}" ]]; then
  echo "SUPERGOAL_STARTUP_TRANSPORT_ACCEPTED readback_required=1 transport_receipt=$TRANSPORT_RECEIPT launch_message_id=${MESSAGE_IDS[-1]}" >&2
  exit 3
fi
python3 "$VERIFY_READBACK" \
  --contract "$ROOT/CONTRACT.json" \
  --transport-receipt "$TRANSPORT_RECEIPT" \
  --readback-receipt "$SUPERGOAL_DELIVERY_READBACK_RECEIPT" \
  --out "$RECEIPT"
echo "SUPERGOAL_STARTUP_FILES_SENT_AND_READBACK_VERIFIED receipt=$RECEIPT launch_message_id=${MESSAGE_IDS[-1]}"
