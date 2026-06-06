from __future__ import annotations

import asyncio
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
DECISION_PARENT = Path(os.environ.get("DECISION_PACKAGE_PARENT", APP_DIR.parent.parent))

if str(DECISION_PARENT) not in sys.path:
    sys.path.insert(0, str(DECISION_PARENT))

from decision import ClientManager, load_config  # noqa: E402


@dataclass
class ChatResult:
    reply: str
    context: list[dict[str, str]]
    engine: str
    trace: dict[str, Any] | None = None


class DecisionBridge:
    STARTUP_TIMEOUT_SECONDS = 15.0
    CALL_TIMEOUT_SECONDS = 180.0

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager: ClientManager | None = None
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        self._startup_error: Exception | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready_event = threading.Event()
            self._startup_error = None
            self._loop = None
            self._manager = None
            self._thread = threading.Thread(target=self._thread_main, name="decision-bridge", daemon=True)
            self._thread.start()
        if not self._ready_event.wait(self.STARTUP_TIMEOUT_SECONDS):
            self._startup_error = RuntimeError("decision bridge startup timed out")

    def ask(self, user_id: str, message: str) -> ChatResult:
        return self._run_sync(self._ask_async(user_id, message))

    def clear_context(self, user_id: str) -> list[dict[str, str]]:
        return self._run_sync(self._clear_context_async(user_id))

    def get_shared_context(self, user_id: str) -> list[dict[str, str]]:
        return self._run_sync(self._get_shared_context_async(user_id))

    def record_reply(self, user_id: str, message: str, reply: str) -> list[dict[str, str]]:
        return self._run_sync(self._record_reply_async(user_id, message, reply))

    def close(self) -> None:
        thread = self._thread
        loop = self._loop
        if thread is None:
            return
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop)
            try:
                future.result(timeout=self.CALL_TIMEOUT_SECONDS)
            finally:
                loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=self.STARTUP_TIMEOUT_SECONDS)
        with self._lock:
            self._thread = None
            self._loop = None
            self._manager = None
            self._ready_event = threading.Event()

    def status(self) -> dict[str, str]:
        error = self._startup_error
        env_error = self._env_error()
        thread = self._thread
        ready = (
            error is None
            and env_error is None
            and thread is not None
            and thread.is_alive()
            and self._loop is not None
            and self._manager is not None
        )
        payload = {
            "name": "decision",
            "status": "ready" if ready else "degraded",
        }
        detail = error or env_error
        if detail is not None:
            payload["error"] = f"{type(detail).__name__}: {detail}"
        return payload

    async def _ask_async(self, user_id: str, message: str) -> ChatResult:
        manager = self._require_manager()
        client = await manager.get_client(user_id)
        result = await client.respond_result(message)
        context = await client.get_context_snapshot()
        return ChatResult(
            reply=result.response_text,
            context=context,
            engine=f"decision:{result.route}",
            trace=result.trace or None,
        )

    async def _clear_context_async(self, user_id: str) -> list[dict[str, str]]:
        manager = self._require_manager()
        await manager.clear_client_context(user_id)
        return []

    async def _get_shared_context_async(self, user_id: str) -> list[dict[str, str]]:
        manager = self._require_manager()
        client = await manager.get_client(user_id)
        return await client.get_context_snapshot()

    async def _record_reply_async(self, user_id: str, message: str, reply: str) -> list[dict[str, str]]:
        manager = self._require_manager()
        return await manager.record_exchange(user_id, message, reply)

    async def _shutdown_async(self) -> None:
        manager = self._manager
        if manager is None:
            return
        try:
            await manager.close()
        finally:
            self._manager = None

    def _run_sync(self, coro):
        self.start()
        manager = self._require_manager()
        loop = self._loop
        if loop is None:
            raise RuntimeError("decision bridge event loop is not available")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=self.CALL_TIMEOUT_SECONDS)
        except Exception:
            if future.done():
                future.cancel()
            raise

    def _require_manager(self) -> ClientManager:
        if self._startup_error is not None:
            raise RuntimeError(f"decision bridge unavailable: {self._startup_error}")
        if self._manager is None:
            raise RuntimeError("decision bridge manager is not initialized")
        return self._manager

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            self._manager = ClientManager()
        except Exception as exc:
            self._startup_error = exc
            self._ready_event.set()
            loop.close()
            self._loop = None
            return

        self._ready_event.set()
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self._loop = None

    def _env_error(self) -> Exception | None:
        try:
            config = load_config()
        except Exception as exc:
            return exc
        if not Path(config.db_path).exists():
            return FileNotFoundError(config.db_path)
        if not Path(config.db_helper_path).exists():
            return FileNotFoundError(config.db_helper_path)
        if not config.llm_api_key:
            return RuntimeError("missing DECISION_LLM_API_KEY/DEEPSEEK_API_KEY")
        if config.embedding_backend.strip().lower() == "openai" and not config.embedding_api_key:
            return RuntimeError("missing DECISION_EMBEDDING_API_KEY/OPENAI_API_KEY/ZAI_API_KEY")
        return None


decision_bridge = DecisionBridge()
