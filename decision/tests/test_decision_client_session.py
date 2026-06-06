import asyncio
import unittest

from decision.client_session import ClientSession
from decision.config import DecisionConfig


class _FakeGateway:
    def __init__(self):
        self.saved = None

    async def get_context(self, user_id: str):
        return []

    async def save_context(self, user_id: str, context):
        self.saved = (user_id, list(context))


class _FakeEngine:
    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def respond(self, *, user_id: str, instruct: str, context: list[dict]):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        context.append({"role": "user", "content": instruct})
        context.append({"role": "assistant", "content": f"reply:{instruct}"})
        self.active -= 1
        return type("Result", (), {"response_text": f"reply:{instruct}"})()


class ClientSessionTests(unittest.IsolatedAsyncioTestCase):
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
            idle_ttl_seconds=1800,
            cleanup_interval_seconds=300,
            request_timeout_seconds=60,
            max_retries=1,
            recall_k=20,
            final_k=6,
        )

    async def test_same_user_requests_are_serialized(self) -> None:
        engine = _FakeEngine()
        gateway = _FakeGateway()
        session = ClientSession(user_id="u1", engine=engine, gateway=gateway, config=self._config())
        await asyncio.gather(session.respond("a"), session.respond("b"))
        self.assertEqual(engine.max_active, 1)
        self.assertEqual(len(session.context), 4)


if __name__ == "__main__":
    unittest.main()
