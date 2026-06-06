#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="/root/data_process/data_clean"

cd "$APP_ROOT"

python3 - <<'PY'
from pathlib import Path

for relative_path in (
    "scripts/run_wechat_batch.sh",
    "scripts/start_wechat_batch_background.sh",
    "scripts/restart_wechat_batch_remote.sh",
    "data_clean/pipeline.py",
    "data_clean/cli.py",
):
    path = Path(relative_path)
    path.write_text(path.read_text(encoding="utf-8").replace("\r\n", "\n"), encoding="utf-8")
PY

chmod +x \
  scripts/run_wechat_batch.sh \
  scripts/start_wechat_batch_background.sh \
  scripts/restart_wechat_batch_remote.sh

for pid_file in \
  runtime/logs/wechat_batch1_rebuild.pid \
  runtime/logs/wechat_batch1_monitor.pid
do
  if [ -f "$pid_file" ]; then
    pid="$(cat "$pid_file" || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
    fi
  fi
done

sleep 1
bash scripts/start_wechat_batch_background.sh
