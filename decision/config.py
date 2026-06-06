from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionConfig:
    db_path: str
    db_helper_path: str
    llm_api_key: str | None
    llm_base_url: str
    llm1_model: str
    llm2_model: str
    embedding_backend: str
    embedding_model: str
    embedding_api_key: str | None
    embedding_base_url: str
    embedding_dimensions: int
    context_max_turns: int
    idle_ttl_seconds: int
    cleanup_interval_seconds: int
    request_timeout_seconds: float
    max_retries: int
    recall_k: int
    final_k: int


def load_config() -> DecisionConfig:
    embedding_backend = _first_non_empty(
        os.environ.get("DECISION_EMBEDDING_BACKEND"),
        "local_bge_m3",
    )
    default_embedding_model = "BAAI/bge-m3" if embedding_backend == "local_bge_m3" else "text-embedding-3-small"
    return DecisionConfig(
        db_path=_first_non_empty(
            os.environ.get("DECISION_DB_PATH"),
            "/root/rivermind-data/database/seu_campus_assistant.db",
        ),
        db_helper_path=_first_non_empty(
            os.environ.get("DECISION_DB_HELPER_PATH"),
            "/root/rivermind-data/seu_campus_db_v2.py",
        ),
        llm_api_key=_first_non_empty_optional(
            os.environ.get("DECISION_LLM_API_KEY"),
            os.environ.get("DEEPSEEK_API_KEY"),
        ),
        llm_base_url=_first_non_empty(
            os.environ.get("DECISION_LLM_BASE_URL"),
            os.environ.get("DEEPSEEK_BASE_URL"),
            "https://api.deepseek.com",
        ).rstrip("/"),
        llm1_model=_first_non_empty(
            os.environ.get("DECISION_LLM1_MODEL"),
            "deepseek-v4-flash",
        ),
        llm2_model=_first_non_empty(
            os.environ.get("DECISION_LLM2_MODEL"),
            "deepseek-v4-pro",
        ),
        embedding_backend=embedding_backend,
        embedding_model=_first_non_empty(
            os.environ.get("DECISION_EMBEDDING_MODEL"),
            default_embedding_model,
        ),
        embedding_api_key=_first_non_empty_optional(
            os.environ.get("DECISION_EMBEDDING_API_KEY"),
            os.environ.get("OPENAI_API_KEY"),
            os.environ.get("ZAI_API_KEY"),
        ),
        embedding_base_url=_first_non_empty(
            os.environ.get("DECISION_EMBEDDING_BASE_URL"),
            os.environ.get("OPENAI_BASE_URL"),
            "https://api.openai.com/v1",
        ).rstrip("/"),
        embedding_dimensions=int(_first_non_empty(os.environ.get("DECISION_EMBEDDING_DIMENSIONS"), "1024")),
        context_max_turns=int(_first_non_empty(os.environ.get("DECISION_CONTEXT_MAX_TURNS"), "10")),
        idle_ttl_seconds=int(_first_non_empty(os.environ.get("DECISION_IDLE_TTL_SECONDS"), "1800")),
        cleanup_interval_seconds=int(_first_non_empty(os.environ.get("DECISION_CLEANUP_INTERVAL_SECONDS"), "300")),
        request_timeout_seconds=float(_first_non_empty(os.environ.get("DECISION_TIMEOUT_SECONDS"), "30")),
        max_retries=int(_first_non_empty(os.environ.get("DECISION_MAX_RETRIES"), "0")),
        recall_k=int(_first_non_empty(os.environ.get("DECISION_RECALL_K"), "12")),
        final_k=int(_first_non_empty(os.environ.get("DECISION_FINAL_K"), "4")),
    )


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    raise ValueError("Expected at least one non-empty value.")


def _first_non_empty_optional(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
