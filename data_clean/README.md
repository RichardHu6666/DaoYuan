# data_clean

`data_clean` 是 `CampusJarvis` 中独立的清洗入库子应用。

当前已拆成两条入口：

- 微信公众号线：读取 `data/data_clean/input/wechat/*` 的 `RawPage`，走 `HTML -> original_text -> LLM/规则 -> 入库`
- 教务数据库线：直读教务源库 `/root/data_process/data/seu_campus_assistant.db` 的 `school_event_table`，使用 `id / website / title / cleaned_document` 进入清洗链路

最终事件主库默认写入：

- Jarvis：`/root/rivermind-data/database/jiaowu.db`

教务线新增 CLI：

- `python -m data_clean process-jwc-db-one --record-id 1 --json`
- `python -m data_clean process-jwc-db-batch --limit 3 --concurrency 100 --json`

微信线原有 CLI 仍可用：

- `python -m data_clean process-one --input-file ...`
- `python -m data_clean process-batch --source wechat --limit 10 --json`

LLM 配置继续使用 DeepSeek 兼容接口：

- `DATA_CLEAN_API_KEY` 或 `DEEPSEEK_API_KEY`
- `DATA_CLEAN_BASE_URL`
- `DATA_CLEAN_MODEL_LLM1`
- `DATA_CLEAN_MODEL_LLM2`
- `DATA_CLEAN_MODEL_LLM3`

若未配置 key，则自动回退到本地 fallback 逻辑。
## 2026-06-06 WeChat DB Notes

- New WeChat DB entrypoints:
  - `python -m data_clean process-wechat-db-one --account "东大仪科" --article-id 1 --json`
  - `python -m data_clean process-wechat-db-account --account "东大仪科" --limit 10 --json`
  - `python -m data_clean --main-db /root/rivermind-data/database/gongzhonghao_batch1.db process-wechat-db-batch --batch-file data/data_clean/meta/wechat_batches/gongzhonghao_batch1.txt --json`
- The account path must be resolved through `data/wechat_ingest/control/control.sqlite3`.
- Exact-match priority is: `account_dir -> display_name -> alias -> input_name`.
- Do not assume `data/wechat_ingest/accounts/<dir>` is a pure public-account name.
- The first batch file lives at `data/data_clean/meta/wechat_batches/gongzhonghao_batch1.txt`.
