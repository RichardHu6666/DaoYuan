from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str | None
    base_url: str
    model_llm1: str
    model_llm2: str
    model_llm3: str
    timeout_seconds: float
    max_retries: int
    enabled: bool


def load_deepseek_config() -> DeepSeekConfig:
    api_key = _first_non_empty(
        os.environ.get("DATA_CLEAN_API_KEY"),
        os.environ.get("DEEPSEEK_API_KEY"),
    )
    base_url = _first_non_empty(
        os.environ.get("DATA_CLEAN_BASE_URL"),
        os.environ.get("DEEPSEEK_BASE_URL"),
        "https://api.deepseek.com",
    )
    model_llm1 = _first_non_empty(
        os.environ.get("DATA_CLEAN_MODEL_LLM1"),
        "deepseek-v4-pro",
    )
    model_llm2 = _first_non_empty(
        os.environ.get("DATA_CLEAN_MODEL_LLM2"),
        "deepseek-v4-flash",
    )
    model_llm3 = _first_non_empty(
        os.environ.get("DATA_CLEAN_MODEL_LLM3"),
        "deepseek-v4-pro",
    )
    timeout_seconds = float(_first_non_empty(os.environ.get("DATA_CLEAN_TIMEOUT_SECONDS"), "180"))
    max_retries = int(_first_non_empty(os.environ.get("DATA_CLEAN_MAX_RETRIES"), "2"))
    enabled = _first_non_empty(os.environ.get("DATA_CLEAN_USE_REMOTE_LLM"), "1") not in {"0", "false", "False"}
    return DeepSeekConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model_llm1=model_llm1,
        model_llm2=model_llm2,
        model_llm3=model_llm3,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        enabled=enabled,
    )


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
