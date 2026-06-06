import unittest

from decision.config import DecisionConfig
from decision.engine import DecisionEngine
from decision.models import EventRecord, RetrievedEvent, ToolRecord


class _FakeGateway:
    def __init__(self, *, user=None, tools=None):
        self.user = user or {}
        self.tools = tools or []

    async def get_user(self, user_id: str):
        return self.user

    async def get_tools(self):
        return self.tools


class _FakeLlmClient:
    def __init__(self, *, llm1_payload=None, llm2_text="好的"):
        self.llm1_payload = llm1_payload
        self.llm2_text = llm2_text
        self.llm1_calls = 0

    def chat_json(self, **kwargs):
        self.llm1_calls += 1
        if isinstance(self.llm1_payload, Exception):
            raise self.llm1_payload
        return self.llm1_payload

    def chat_text(self, **kwargs):
        if isinstance(self.llm2_text, Exception):
            raise self.llm2_text
        return self.llm2_text


class _FakeRetriever:
    def __init__(self, events):
        self.events = events

    async def retrieve(self, *, query: str, filters=None):
        return [RetrievedEvent(event=event, similarity=0.8) for event in self.events]


class _FakeRanker:
    def rank(self, retrieved, *, user=None, filters=None):
        return retrieved


class DecisionEngineTests(unittest.IsolatedAsyncioTestCase):
    def _config(self) -> DecisionConfig:
        return DecisionConfig(
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
            embedding_dimensions=1024,
            context_max_turns=10,
            idle_ttl_seconds=1800,
            cleanup_interval_seconds=300,
            request_timeout_seconds=60,
            max_retries=1,
            recall_k=20,
            final_k=6,
        )

    async def test_rule_tool_direct(self) -> None:
        gateway = _FakeGateway(
            tools=[ToolRecord(name="教务系统", website="https://jw.example.com", description="成绩查询")]
        )
        engine = DecisionEngine(
            config=self._config(),
            gateway=gateway,
            llm_client=_FakeLlmClient(llm1_payload={"route": "rag", "rewritten_query": "ignored"}),
            retriever=_FakeRetriever([]),
            ranker=_FakeRanker(),
        )
        context = []
        result = await engine.respond(user_id="u1", instruct="查成绩", context=context)
        self.assertEqual(result.route, "tool_direct")
        self.assertIn("https://jw.example.com", result.response_text)

    async def test_missing_profile_fields_flow(self) -> None:
        event = EventRecord(
            id=1,
            title="竞赛通知",
            summary="一条竞赛活动",
            website="https://example.com/1",
            regis_end_time=None,
            activity_start_time=None,
            campus=["九龙湖"],
            topics=["竞赛"],
            target_grade=[1, 2],
            embedded_summary=None,
        )
        gateway = _FakeGateway(
            user={"uuid": "u1", "interest": [], "school": "", "major": "", "enrollment_year": None, "student_level": ""},
            tools=[],
        )
        engine = DecisionEngine(
            config=self._config(),
            gateway=gateway,
            llm_client=_FakeLlmClient(
                llm1_payload={"route": "rag", "rewritten_query": "竞赛", "filters": {"topics": ["竞赛"]}},
                llm2_text="当前先按通用推荐给你几条竞赛活动，后续可以补充资料。",
            ),
            retriever=_FakeRetriever([event]),
            ranker=_FakeRanker(),
        )
        result = await engine.respond(user_id="u1", instruct="适合我的竞赛有哪些", context=[])
        self.assertIn("interest", result.missing_profile_fields)
        self.assertEqual(result.retrieved_event_ids, [1])

    async def test_llm1_failure_falls_back_to_rag(self) -> None:
        event = EventRecord(
            id=9,
            title="活动",
            summary="摘要",
            website="https://example.com/9",
            regis_end_time=None,
            activity_start_time=None,
            campus=[],
            topics=[],
            target_grade=[],
            embedded_summary=None,
        )
        engine = DecisionEngine(
            config=self._config(),
            gateway=_FakeGateway(user={"uuid": "u1"}, tools=[]),
            llm_client=_FakeLlmClient(llm1_payload=RuntimeError("boom"), llm2_text="正常降级"),
            retriever=_FakeRetriever([event]),
            ranker=_FakeRanker(),
        )
        result = await engine.respond(user_id="u1", instruct="最近有什么竞赛", context=[])
        self.assertEqual(result.route, "rag")
        self.assertEqual(result.rewritten_query, "最近有什么竞赛")


if __name__ == "__main__":
    unittest.main()
