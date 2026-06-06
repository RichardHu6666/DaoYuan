import unittest

from decision.config import DecisionConfig
from decision.models import EventRecord
from decision.retriever import VectorRetriever


class _FakeGateway:
    def __init__(self, events):
        self.events = events

    async def list_candidate_events(self, filters=None):
        return self.events


class _FakeEmbedder:
    async def embed_query(self, text: str):
        return [1.0, 0.0]


class RetrieverTests(unittest.IsolatedAsyncioTestCase):
    async def test_skip_invalid_vectors(self) -> None:
        config = DecisionConfig(
            db_path="db",
            db_helper_path="helper",
            llm_api_key=None,
            llm_base_url="https://api.deepseek.com",
            llm1_model="llm1",
            llm2_model="llm2",
            embedding_backend="openai",
            embedding_model="text-embedding-3-small",
            embedding_api_key=None,
            embedding_base_url="https://api.openai.com/v1",
            embedding_dimensions=2,
            context_max_turns=10,
            idle_ttl_seconds=1800,
            cleanup_interval_seconds=300,
            request_timeout_seconds=60,
            max_retries=1,
            recall_k=20,
            final_k=6,
        )
        valid = EventRecord(
            id=1,
            title="活动1",
            summary="摘要",
            website="https://example.com/1",
            regis_end_time=None,
            activity_start_time=None,
            campus=[],
            topics=[],
            target_grade=[],
            embedded_summary=b"\x00\x00\x80?\x00\x00\x00\x00",
        )
        invalid = EventRecord(
            id=2,
            title="活动2",
            summary="摘要",
            website="https://example.com/2",
            regis_end_time=None,
            activity_start_time=None,
            campus=[],
            topics=[],
            target_grade=[],
            embedded_summary=b"broken",
        )
        retriever = VectorRetriever(config=config, gateway=_FakeGateway([valid, invalid]), embedder=_FakeEmbedder())
        results = await retriever.retrieve(query="竞赛")
        self.assertEqual([item.event.id for item in results], [1])


if __name__ == "__main__":
    unittest.main()
