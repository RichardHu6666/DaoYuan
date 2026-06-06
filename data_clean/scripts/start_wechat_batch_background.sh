#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="/root/data_process/data_clean"
DB="/root/rivermind-data/database/gongzhonghao_batch1.db"

cd "$APP_ROOT"
mkdir -p "$APP_ROOT/runtime/logs"

TS="$(date +%F_%H-%M-%S)"
LOG="$APP_ROOT/runtime/logs/wechat_batch1_rebuild_${TS}.log"
MON="$APP_ROOT/runtime/logs/wechat_batch1_monitor_${TS}.log"
PIDFILE="$APP_ROOT/runtime/logs/wechat_batch1_rebuild.pid"
MONPIDFILE="$APP_ROOT/runtime/logs/wechat_batch1_monitor.pid"

nohup bash -lc "cd '$APP_ROOT' && export PYTHONPATH='$APP_ROOT' && stdbuf -oL -eL bash scripts/run_wechat_batch.sh" >"$LOG" 2>&1 < /dev/null &
REBUILD_PID=$!
echo "$REBUILD_PID" > "$PIDFILE"

nohup bash -lc "
PID='$REBUILD_PID'
MONITOR_LOG='$MON'
DB_PATH='$DB'
cd '$APP_ROOT'
export PYTHONPATH='$APP_ROOT'
while kill -0 \"\$PID\" 2>/dev/null; do
  {
    echo \"[monitor] \$(date -Is) pid=\$PID\"
    python -m data_clean --main-db \"\$DB_PATH\" show-status --json || true
    echo
  } >> \"\$MONITOR_LOG\" 2>&1
  sleep 600
done
{
  echo \"[monitor] \$(date -Is) pid=\$PID finished\"
  python -m data_clean --main-db \"\$DB_PATH\" show-status --json || true
} >> \"\$MONITOR_LOG\" 2>&1
" >/dev/null 2>&1 < /dev/null &
MONITOR_PID=$!
echo "$MONITOR_PID" > "$MONPIDFILE"

echo "LOG=$LOG"
echo "MONITOR_LOG=$MON"
echo "REBUILD_PID=$REBUILD_PID"
echo "MONITOR_PID=$MONITOR_PID"
