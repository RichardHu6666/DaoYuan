from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .client_manager import ClientManager
from .config import DecisionConfig, load_config


SERVICE_NAME = "decision"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1)
    instruct: str = Field(min_length=1)
    debug: bool = False


class ClearContextRequest(BaseModel):
    user_id: str = Field(min_length=1)


def create_app(
    *,
    config: DecisionConfig | None = None,
    manager_factory: Callable[[DecisionConfig], ClientManager] | None = None,
) -> FastAPI:
    runtime_config = config or load_config()
    builder = manager_factory or (lambda cfg: ClientManager(config=cfg))
    manager: ClientManager | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal manager
        manager = builder(runtime_config)
        _app.state.manager = manager
        _app.state.config = runtime_config
        try:
            yield
        finally:
            if manager is not None:
                await manager.close()

    app = FastAPI(title="Decision Service", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        current_manager = _manager_from_app(app)
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "session_count": len(getattr(current_manager, "sessions", {})),
        }

    @app.post("/api/chat")
    async def chat(request: ChatRequest) -> dict[str, Any]:
        current_manager = _manager_from_app(app)
        client = await current_manager.get_client(request.user_id)
        result = await client.respond_result(request.instruct)
        payload: dict[str, Any] = {
            "response_text": result.response_text,
            "route": result.route,
            "rewritten_query": result.rewritten_query,
            "tool_name": result.tool_name,
            "tool_url": result.tool_url,
            "retrieved_event_ids": list(result.retrieved_event_ids or []),
            "missing_profile_fields": list(result.missing_profile_fields or []),
        }
        if request.debug:
            payload["trace"] = dict(result.trace or {})
        return payload

    @app.post("/api/chat/clear")
    async def clear_chat(request: ClearContextRequest) -> dict[str, Any]:
        current_manager = _manager_from_app(app)
        context = await current_manager.clear_client_context(request.user_id)
        return {"ok": True, "context_length": len(context)}

    return app


def run_service(*, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, db_path: str | None = None) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Missing uvicorn. Install project dependencies before running `python -m decision serve`.") from exc

    config = load_config()
    if db_path:
        config = replace(config, db_path=db_path)
    app = create_app(config=config)
    uvicorn.run(app, host=host, port=port, workers=1)


def _manager_from_app(app: FastAPI) -> ClientManager:
    manager = getattr(app.state, "manager", None)
    if manager is None:
        raise RuntimeError("Decision service manager is not initialized.")
    return manager
