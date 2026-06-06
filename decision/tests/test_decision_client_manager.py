import time
import unittest

from decision.client_manager import ClientManager
from decision.config import DecisionConfig


class _FakeGateway:
    def __init__(self):
        self.saved = {}

    async def get_context(self, user_id: str):
        return []

    async def save_context(self, user_id: str, context):
        self.saved[user_id] = list(context)

    async def get_user(self, user_id: str):
        return {}

    async def get_tools(self):
        return []


class _FakeEngine:
    async def respond(self, *, user_id: str, instruct: str, context: list[dict]):
        context.append({"role": "user", "content": instruct})
        context.append({"role": "assistant", "content": f"reply:{instruct}"})
        return type("Result", (), {"response_text": f"reply:{instruct}"})()


class ClientManagerTests(unittest.IsolatedAsyncioTestCase):
    def _config(self):
        return DecisionConfig(
            db_path="db",
            db_helper_path="helper",
            llm_api_key=None,
            llm_base_url="url",
            llm1_model="llm1",
            llm2_model="llm2",
            embedding_backend="openai",
            embedding_model="model",
            embedding_api_key=None,
            embedding_base_url="embed",
            embedding_dimensions=1024,
            context_max_turns=10,
            idle_ttl_seconds=1,
            cleanup_interval_seconds=300,
            request_timeout_seconds=60,
            max_retries=1,
            recall_k=20,
            final_k=6,
        )

    async def test_release_idle_clients_flushes_context(self) -> None:
        gateway = _FakeGateway()
        manager = ClientManager(config=self._config(), engine=_FakeEngine(), gateway=gateway)
        try:
            session = await manager.get_client("u1")
            await session.respond("hello")
            session.last_time = time.monotonic() - 10
            await manager.release_idle_clients()
            self.assertNotIn("u1", manager.sessions)
            self.assertIn("u1", gateway.saved)
        finally:
            await manager.close()


if __name__ == "__main__":
    unittest.main()
