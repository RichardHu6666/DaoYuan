#!/usr/bin/env bash
set -euo pipefail

LOG_PATH="/root/data_process/data_clean/runtime/logs/remote_llm_debug.log"
: > "${LOG_PATH}"

echo "step=start" >> "${LOG_PATH}"
while IFS= read -r line; do
  case "${line}" in
    export\ DATA_CLEAN_*|export\ DEEPSEEK_*)
      eval "${line}"
      ;;
  esac
done < /root/.bashrc
echo "loaded_exports=1" >> "${LOG_PATH}"

cd /root/data_process/data_clean
echo "cwd=$(pwd)" >> "${LOG_PATH}"

python3 - <<'PY' >> "${LOG_PATH}" 2>&1
import os
print(f"api_key_present={bool(os.environ.get('DATA_CLEAN_API_KEY'))}")
print(f"base_url={os.environ.get('DATA_CLEAN_BASE_URL', '')}")
print(f"llm1={os.environ.get('DATA_CLEAN_MODEL_LLM1', '')}")
print(f"llm2={os.environ.get('DATA_CLEAN_MODEL_LLM2', '')}")
print(f"llm3={os.environ.get('DATA_CLEAN_MODEL_LLM3', '')}")
PY

python3 -m data_clean process-batch --source jwc --limit 1 --json >> "${LOG_PATH}" 2>&1
