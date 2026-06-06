#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="/root/data_process/data_clean"
SIDECAR_DB="$APP_ROOT/runtime/process_state.sqlite3"
TARGET_DB="/root/rivermind-data/database/gongzhonghao_batch1.db"
PIDFILE="$APP_ROOT/runtime/logs/wechat_batch1_rebuild.pid"

cd "$APP_ROOT"
mkdir -p "$APP_ROOT/runtime/logs"

if [ ! -f "$PIDFILE" ]; then
  echo "missing pid file: $PIDFILE" >&2
  exit 1
fi

PID="$(cat "$PIDFILE")"
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  echo "rebuild pid is not running: $PID" >&2
  exit 1
fi

TS="$(date +%F_%H-%M-%S)"
LOG="$APP_ROOT/runtime/logs/wechat_batch1_wechat_only_monitor_${TS}.log"
MONPIDFILE="$APP_ROOT/runtime/logs/wechat_batch1_wechat_only_monitor.pid"

nohup bash -lc "
PID='$PID'
LOG_PATH='$LOG'
SIDECAR_PATH='$SIDECAR_DB'
TARGET_PATH='$TARGET_DB'
while kill -0 \"\$PID\" 2>/dev/null; do
  python3 - \"\$SIDECAR_PATH\" \"\$TARGET_PATH\" \"\$PID\" >> \"\$LOG_PATH\" 2>&1 <<'PY'
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sidecar = Path(sys.argv[1])
target = Path(sys.argv[2])
pid = sys.argv[3]
payload = {
    'monitor_time': datetime.now().astimezone().isoformat(),
    'pid': pid,
}

conn = sqlite3.connect(sidecar)
try:
    payload['wechat_total'] = conn.execute(
        \"select count(*) from raw_pages where source_type='wechat_db'\"
    ).fetchone()[0]
    payload['wechat_status'] = dict(
        conn.execute(
            \"select status, count(*) from raw_pages where source_type='wechat_db' group by status\"
        ).fetchall()
    )
    payload['manual_by_reason_code'] = dict(
        conn.execute(
            \"select reason_code, count(*) from manual_review_queue where page_id like 'wechat_db_%' and status='pending' group by reason_code\"
        ).fetchall()
    )
finally:
    conn.close()

if target.exists():
    conn = sqlite3.connect(target)
    try:
        payload['target_db_count'] = conn.execute(
            'select count(*) from school_event_table'
        ).fetchone()[0]
    finally:
        conn.close()
else:
    payload['target_db_count'] = 0

print(json.dumps(payload, ensure_ascii=False, indent=2))
print()
PY
  sleep 600
done
python3 - \"\$SIDECAR_PATH\" \"\$TARGET_PATH\" \"\$PID\" >> \"\$LOG_PATH\" 2>&1 <<'PY'
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sidecar = Path(sys.argv[1])
target = Path(sys.argv[2])
pid = sys.argv[3]
payload = {
    'monitor_time': datetime.now().astimezone().isoformat(),
    'pid': pid,
    'finished': True,
}

conn = sqlite3.connect(sidecar)
try:
    payload['wechat_total'] = conn.execute(
        \"select count(*) from raw_pages where source_type='wechat_db'\"
    ).fetchone()[0]
    payload['wechat_status'] = dict(
        conn.execute(
            \"select status, count(*) from raw_pages where source_type='wechat_db' group by status\"
        ).fetchall()
    )
    payload['manual_by_reason_code'] = dict(
        conn.execute(
            \"select reason_code, count(*) from manual_review_queue where page_id like 'wechat_db_%' and status='pending' group by reason_code\"
        ).fetchall()
    )
finally:
    conn.close()

if target.exists():
    conn = sqlite3.connect(target)
    try:
        payload['target_db_count'] = conn.execute(
            'select count(*) from school_event_table'
        ).fetchone()[0]
    finally:
        conn.close()
else:
    payload['target_db_count'] = 0

print(json.dumps(payload, ensure_ascii=False, indent=2))
print()
PY
" >/dev/null 2>&1 < /dev/null &
MONITOR_PID=$!
echo "$MONITOR_PID" > "$MONPIDFILE"

echo "WECHAT_ONLY_MONITOR_LOG=$LOG"
echo "WECHAT_ONLY_MONITOR_PID=$MONITOR_PID"
