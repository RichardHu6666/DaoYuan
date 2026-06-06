#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="/root/data_process/data_clean"
BATCH_FILE="/root/data_process/data/data_clean/meta/wechat_batches/gongzhonghao_batch1.txt"
TARGET_DB="/root/rivermind-data/database/gongzhonghao_batch1.db"
SMOKE_ACCOUNT="东南大学电气工程学院"

cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT"

if [ -f /root/.bashrc ]; then
  eval "$(
    grep -E '^(export )?(DATA_CLEAN_|DEEPSEEK_)' /root/.bashrc \
      | grep '=' \
      | sed -E 's/^[[:space:]]*export[[:space:]]*//; s/^/export /'
  )"
fi

python -m data_clean --main-db "$TARGET_DB" check-remote-llm
python -m data_clean --main-db "$TARGET_DB" reset-wechat-batch --batch-file "$BATCH_FILE"

python -m data_clean --main-db "$TARGET_DB" process-wechat-db-account --account "$SMOKE_ACCOUNT" --limit 1
python -m data_clean --main-db "$TARGET_DB" process-wechat-db-account --account "$SMOKE_ACCOUNT" --limit 1 --include-completed
python -m data_clean --main-db "$TARGET_DB" process-wechat-db-account --account "$SMOKE_ACCOUNT" --limit 3
python -m data_clean --main-db "$TARGET_DB" process-wechat-db-batch --batch-file "$BATCH_FILE"
