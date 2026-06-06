#!/usr/bin/env bash
set -euo pipefail

while IFS= read -r line; do
  case "${line}" in
    export\ DATA_CLEAN_*|export\ DEEPSEEK_*)
      eval "${line}"
      ;;
  esac
done < /root/.bashrc

cd /root/data_process/data_clean
python3 -m data_clean process-batch --source jwc --limit 1 --json
