from __future__ import annotations

import asyncio
import contextlib
import time

from .client_session import ClientSession
from .config import DecisionConfig, load_config
from .db_gateway import DecisionDBGateway
from .engine import DecisionEngine


class ClientManager:
    def __init__(
        self,
        *,
        config: DecisionConfig | None = None,
        engine: DecisionEngine | None = None,
        gateway: DecisionDBGateway | None = None,
    ):
        self.config = config or load_config()
        self.gateway = gateway or DecisionDBGateway(self.config)
        self.engine = engine or DecisionEngine(config=self.config, gateway=self.gateway)
        self.sessions: dict[str, ClientSession] = {}
        self.manager_lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def get_client(self, user_id: str) -> ClientSession:
        await self._ensure_cleanup_task()
        async with self.manager_lock:
            session = self.sessions.get(user_id)
            if session is None:
                session = ClientSession(
                    user_id=user_id,
                    engine=self.engine,
                    gateway=self.gateway,
                    config=self.config,
                )
                self.sessions[user_id] = session
            return session

    async def release_idle_clients(self) -> None:
        expired: list[ClientSession] = []
        now = time.monotonic()
        async with self.manager_lock:
            for user_id, session in list(self.sessions.items()):
                idle_seconds = now - session.last_time
                if idle_seconds < self.config.idle_ttl_seconds:
                    continue
                expired.append(session)
                self.sessions.pop(user_id, None)
        for session in expired:
            await session.flush_context()

    async def clear_client_context(self, user_id: str) -> list[dict[str, str]]:
        await self._ensure_cleanup_task()
        session: ClientSession | None
        async with self.manager_lock:
            session = self.sessions.get(user_id)
        if session is not None:
            return await session.clear_context()
        await self.gateway.save_context(user_id, [])
        return []

    async def record_exchange(self, user_id: str, user_text: str, assistant_text: str) -> list[dict[str, str]]:
        session = await self.get_client(user_id)
        return await session.record_exchange(user_text, assistant_text)

    async def close(self) -> None:
        task = self._cleanup_task
        self._cleanup_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        async with self.manager_lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            await session.flush_context()
        if hasattr(self.engine, "close"):
            self.engine.close()

    async def _ensure_cleanup_task(self) -> None:
        if self._cleanup_task is not None:
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                await self.release_idle_clients()
        except asyncio.CancelledError:
            raise
