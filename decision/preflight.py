from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .client_manager import ClientManager
from .config import DecisionConfig, load_config
from .db_gateway import _load_db_class
from .engine import DecisionEngine
from .models import EventRecord, RetrievedEvent, ToolRecord


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    checks: list[CheckResult]

    @property
    def ok(self) -> bool:
        return all(item.status != "fail" for item in self.checks)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "checks": [asdict(item) for item in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [f"overall={ 'PASS' if self.ok else 'FAIL' }"]
        for item in self.checks:
            lines.append(f"[{item.status.upper()}] {item.name}: {item.detail}")
        return "\n".join(lines)


def run_preflight(*, include_runtime: bool = False, config: DecisionConfig | None = None) -> PreflightReport:
    checks: list[CheckResult] = []
    checks.extend(_run_code_checks())
    if include_runtime:
        checks.extend(_run_runtime_checks(config=config))
    return PreflightReport(checks=checks)


def _run_code_checks() -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.append(_pass("code_imports", "decision package modules loaded successfully."))

    contract_issues = _config_contract_issues(_sample_config())
    if contract_issues:
        checks.append(_fail("code_config_contract", "; ".join(contract_issues)))
    else:
        checks.append(_pass("code_config_contract", "default decision config contract looks consistent."))

    try:
        detail = asyncio.run(_run_in_memory_smoke())
    except Exception as exc:
        checks.append(_fail("code_in_memory_smoke", f"{type(exc).__name__}: {exc}"))
    else:
        checks.append(_pass("code_in_memory_smoke", detail))
    return checks


def _run_runtime_checks(*, config: DecisionConfig | None) -> list[CheckResult]:
    checks: list[CheckResult] = []
    try:
        runtime_config = config or load_config()
    except Exception as exc:
        return [_fail("runtime_config_load", f"{type(exc).__name__}: {exc}")]

    issues = _config_contract_issues(runtime_config)
    if issues:
        checks.append(_fail("runtime_config_contract", "; ".join(issues)))
    else:
        checks.append(
            _pass(
                "runtime_config_contract",
                f"recall_k={runtime_config.recall_k}, final_k={runtime_config.final_k}, backend={runtime_config.embedding_backend}.",
            )
        )

    helper_path = Path(runtime_config.db_helper_path)
    if not helper_path.exists():
        checks.append(_fail("runtime_db_helper_path", f"DB helper not found: {helper_path}"))
    else:
        try:
            _load_db_class(helper_path)
        except Exception as exc:
            checks.append(_fail("runtime_db_helper_import", f"{type(exc).__name__}: {exc}"))
        else:
            checks.append(_pass("runtime_db_helper_import", f"Loaded `SEUCampusDB` from {helper_path}."))

    db_path = Path(runtime_config.db_path)
    if db_path.parent.exists():
        checks.append(_pass("runtime_db_parent_dir", f"DB parent directory exists: {db_path.parent}"))
    else:
        checks.append(
            _warn(
                "runtime_db_parent_dir",
                f"DB parent directory is missing: {db_path.parent}. This is acceptable before deployment/data initialization.",
            )
        )
    if db_path.exists():
        checks.append(_pass("runtime_db_file", f"DB file exists: {db_path}"))
    else:
        checks.append(
            _warn(
                "runtime_db_file",
                f"DB file is missing: {db_path}. This is acceptable before real data is loaded.",
            )
        )

    if runtime_config.llm_api_key:
        checks.append(_pass("runtime_llm_api_key", "LLM API key is configured."))
    else:
        checks.append(_warn("runtime_llm_api_key", "LLM API key is missing. Live decision requests will not run yet."))

    if runtime_config.embedding_backend == "openai":
        if runtime_config.embedding_api_key:
            checks.append(_pass("runtime_embedding_api_key", "Embedding API key is configured."))
        else:
            checks.append(
                _warn(
                    "runtime_embedding_api_key",
                    "Embedding API key is missing for `openai` backend. Retrieval will not run live yet.",
                )
            )
    elif runtime_config.embedding_backend == "local_bge_m3":
        if importlib.util.find_spec("sentence_transformers") is None:
            checks.append(
                _warn(
                    "runtime_local_embedding_dependency",
                    "`sentence_transformers` is not installed. Local BGE-M3 embedding cannot run yet.",
                )
            )
        else:
            checks.append(_pass("runtime_local_embedding_dependency", "`sentence_transformers` is available."))

    return checks


async def _run_in_memory_smoke() -> str:
    config = _sample_config()
    gateway = _FakeGateway(
        user={
            "uuid": "u1",
            "interest": ["contest"],
            "school": "SEU",
            "major": "CS",
            "enrollment_year": 2024,
            "student_level": "undergraduate",
        },
        tools=[ToolRecord(name="alpha-tool", website="https://example.com/tool", description="grade lookup")],
    )
    engine = DecisionEngine(
        config=config,
        gateway=gateway,
        llm_client=_FakeLlmClient(),
        retriever=_FakeRetriever(),
        ranker=_FakeRanker(),
    )

    tool_result = await engine.respond(user_id="u1", instruct="need direct tool", context=[])
    if tool_result.route != "tool_direct" or tool_result.tool_url != "https://example.com/tool":
        raise AssertionError("tool-direct path did not produce the expected URL.")

    manager = ClientManager(config=config, engine=engine, gateway=gateway)
    try:
        session = await manager.get_client("u1")
        rag_text = await session.respond("need rag answer")
        if rag_text != "OK_RAG_RESPONSE":
            raise AssertionError("RAG path did not return the expected response text.")
        session.last_time = time.monotonic() - 10
        await manager.release_idle_clients()
        if "u1" not in gateway.saved_contexts:
            raise AssertionError("idle session cleanup did not flush context.")
    finally:
        await manager.close()
    return "tool-direct, RAG flow, and idle-session flush all passed with fake dependencies."


def _sample_config() -> DecisionConfig:
    return DecisionConfig(
        db_path="db.sqlite3",
        db_helper_path="helper.py",
        llm_api_key=None,
        llm_base_url="https://api.deepseek.com",
        llm1_model="llm1",
        llm2_model="llm2",
        embedding_backend="openai",
        embedding_model="text-embedding-3-small",
        embedding_api_key=None,
        embedding_base_url="https://api.openai.com/v1",
        embedding_dimensions=1024,
        context_max_turns=10,
        idle_ttl_seconds=1,
        cleanup_interval_seconds=300,
        request_timeout_seconds=60,
        max_retries=1,
        recall_k=20,
        final_k=6,
    )


def _config_contract_issues(config: DecisionConfig) -> list[str]:
    issues: list[str] = []
    if config.embedding_backend not in {"openai", "local_bge_m3"}:
        issues.append(f"unsupported embedding backend `{config.embedding_backend}`")
    if config.embedding_dimensions <= 0:
        issues.append("embedding_dimensions must be > 0")
    if config.context_max_turns <= 0:
        issues.append("context_max_turns must be > 0")
    if config.idle_ttl_seconds <= 0:
        issues.append("idle_ttl_seconds must be > 0")
    if config.cleanup_interval_seconds <= 0:
        issues.append("cleanup_interval_seconds must be > 0")
    if config.request_timeout_seconds <= 0:
        issues.append("request_timeout_seconds must be > 0")
    if config.max_retries < 0:
        issues.append("max_retries must be >= 0")
    if config.recall_k <= 0:
        issues.append("recall_k must be > 0")
    if config.final_k <= 0:
        issues.append("final_k must be > 0")
    if config.final_k > config.recall_k:
        issues.append("final_k must be <= recall_k")
    return issues


def _pass(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="pass", detail=detail)


def _warn(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="warn", detail=detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="fail", detail=detail)


class _FakeGateway:
    def __init__(self, *, user: dict | None = None, tools: list[ToolRecord] | None = None):
        self.user = user or {}
        self.tools = tools or []
        self.saved_contexts: dict[str, list[dict]] = {}

    async def get_user(self, user_id: str) -> dict:
        return self.user

    async def get_tools(self) -> list[ToolRecord]:
        return list(self.tools)

    async def get_context(self, user_id: str) -> list[dict]:
        return []

    async def save_context(self, user_id: str, context: list[dict]) -> None:
        self.saved_contexts[user_id] = list(context)


class _FakeLlmClient:
    def chat_json(self, **kwargs) -> dict:
        payload = kwargs.get("user_payload") or {}
        instruct = str(payload.get("instruct") or "")
        if instruct == "need direct tool":
            return {
                "route": "tool_direct",
                "intent": "tool",
                "rewritten_query": instruct,
                "tool_name": "alpha-tool",
                "tool_reason": "matched fake tool",
                "filters": {},
            }
        return {
            "route": "rag",
            "intent": "rag",
            "rewritten_query": "contest",
            "filters": {"topics": ["contest"]},
        }

    def chat_text(self, **kwargs) -> str:
        return "OK_RAG_RESPONSE"


class _FakeRetriever:
    async def retrieve_with_trace(self, *, query: str, filters=None) -> tuple[list[RetrievedEvent], dict]:
        event = EventRecord(
            id=1,
            title="contest",
            summary="contest summary",
            website="https://example.com/contest",
            regis_end_time=None,
            activity_start_time=None,
            campus=["jlh"],
            topics=["contest"],
            target_grade=[1, 2],
            embedded_summary=None,
        )
        retrieved = [RetrievedEvent(event=event, similarity=0.8)]
        return retrieved, {
            "candidate_count_before_vector": 1,
            "fallback_to_unfiltered": False,
            "vector_scored_count": 1,
            "invalid_vector_count": 0,
            "query_vector_dim": 1024,
        }

    async def retrieve(self, *, query: str, filters=None) -> list[RetrievedEvent]:
        retrieved, _ = await self.retrieve_with_trace(query=query, filters=filters)
        return retrieved


class _FakeRanker:
    def rank(self, retrieved: list[RetrievedEvent], *, user=None, filters=None) -> list[RetrievedEvent]:
        for item in retrieved:
            item.final_score = item.similarity
        return retrieved
