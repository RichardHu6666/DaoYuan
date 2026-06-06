#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="/root/data_process/data_clean"
ENV_FILE="$APP_ROOT/runtime/env/deepseek.env"
BATCH_FILE="/root/data_process/data/data_clean/meta/wechat_batches/gongzhonghao_batch1.txt"
TARGET_DB="/root/rivermind-data/database/gongzhonghao_batch1.db"
CONCURRENCY="${DATA_CLEAN_WECHAT_CONCURRENCY:-300}"

cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT"

if [ ! -f "$ENV_FILE" ]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 2
fi

set -a
source "$ENV_FILE"
set +a

log_step() {
  printf '[step] %s\n' "$1"
}

log_step "check-remote-llm"
python -m data_clean --main-db "$TARGET_DB" check-remote-llm
log_step "reset-wechat-batch"
python -m data_clean --main-db "$TARGET_DB" reset-wechat-batch --batch-file "$BATCH_FILE"

SMOKE_INFO="$(
  python - <<'PY'
from data_clean.models import default_app_paths
from data_clean.wechat_account_resolver import WechatAccountResolver
from data_clean.wechat_db_loader import WechatDbLoader

paths = default_app_paths()
resolver = WechatAccountResolver(paths)
loader = WechatDbLoader(paths, resolver=resolver)
resolutions = resolver.resolve_batch_file("/root/data_process/data/data_clean/meta/wechat_batches/gongzhonghao_batch1.txt")
if not resolutions:
    raise SystemExit("No accounts found in batch file.")
first_account = resolutions[0]
first_article = next(loader.iter_account_records(account_dir=first_account.account_dir, limit=1), None)
if first_article is None:
    raise SystemExit(f"No article rows found for account: {first_account.display_name}")
print(first_account.display_name)
print(first_article.article_id)
PY
)"

SMOKE_ACCOUNT="$(printf '%s\n' "$SMOKE_INFO" | sed -n '1p')"
SMOKE_ARTICLE_ID="$(printf '%s\n' "$SMOKE_INFO" | sed -n '2p')"

log_step "smoke-one"
python -m data_clean --main-db "$TARGET_DB" process-wechat-db-one --account "$SMOKE_ACCOUNT" --article-id "$SMOKE_ARTICLE_ID"
log_step "smoke-idempotency-rerun"
python -m data_clean --main-db "$TARGET_DB" process-wechat-db-one --account "$SMOKE_ACCOUNT" --article-id "$SMOKE_ARTICLE_ID"
log_step "account-limit-3"
python -m data_clean --main-db "$TARGET_DB" process-wechat-db-account --account "$SMOKE_ACCOUNT" --limit 3 --concurrency "$CONCURRENCY"
log_step "batch1-full-rebuild"
python -m data_clean --main-db "$TARGET_DB" process-wechat-db-batch --batch-file "$BATCH_FILE" --concurrency "$CONCURRENCY"
log_step "show-status"
python -m data_clean --main-db "$TARGET_DB" show-status --json
log_step "show-manual-wechat"
python -m data_clean --main-db "$TARGET_DB" show-manual --source-type wechat_db --json
