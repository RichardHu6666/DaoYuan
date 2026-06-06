from __future__ import annotations

import asyncio
import time

from .config import DecisionConfig
from .context_store import ContextStore
from .db_gateway import DecisionDBGateway
from .engine import DecisionEngine
from .models import ClientStatus, DecisionResult, EventRecord
from .prompts import format_tool_reply
from .tool_router import match_tool


PROFILE_PATTERNS = {
    "identity": ["我是谁", "我的身份"],
    "major": ["我是什么专业", "我的专业是什么"],
    "grade": ["我几年级", "我的年级是什么"],
    "interest": ["我的兴趣是什么", "我喜欢什么"],
    "school": ["我的学院是什么", "我的学校是什么", "我是哪个学院", "我是哪个学校"],
}
FOLLOW_UP_TIME_MARKERS = ["报名截止时间", "截止时间", "开始时间", "活动时间", "什么时候", "地点", "链接", "网址"]


class ClientSession:
    def __init__(
        self,
        *,
        user_id: str,
        engine: DecisionEngine,
        gateway: DecisionDBGateway,
        config: DecisionConfig,
    ):
        self.uuid = user_id
        self.engine = engine
        self.gateway = gateway
        self.config = config
        self.status = ClientStatus.IDLE
        self.last_time = time.monotonic()
        self.context: list[dict] = []
        self.lock = asyncio.Lock()
        self._loaded = False
        self._context_store = ContextStore(config.context_max_turns)
        self.last_result: DecisionResult | None = None
        self.last_retrieved_events: list[EventRecord] = []

    async def respond(self, instruct: str) -> str:
        result = await self.respond_result(instruct)
        return result.response_text

    async def respond_result(self, instruct: str) -> DecisionResult:
        async with self.lock:
            await self._ensure_loaded()
            self.status = ClientStatus.RUNNING
            try:
                result = await self._respond_inner(instruct)
                self.context = self._context_store.trim(self.context)
                normalized = self._context_store.normalize(self.context)
                await self.gateway.save_context(self.uuid, normalized)
                self.last_result = result
                self.last_retrieved_events = list(result.retrieved_events[: self.config.final_k]) if result.route == "rag" else []
                self.status = ClientStatus.IDLE
                self.last_time = time.monotonic()
                return result
            except Exception:
                self.status = ClientStatus.ERROR
                self.last_time = time.monotonic()
                raise

    async def flush_context(self) -> None:
        if not self._loaded:
            return
        normalized = self._context_store.normalize(self.context)
        await self.gateway.save_context(self.uuid, normalized)

    async def clear_context(self) -> list[dict[str, str]]:
        async with self.lock:
            self.context = []
            self.last_result = None
            self.last_retrieved_events = []
            self._loaded = True
            await self.gateway.save_context(self.uuid, [])
            self.status = ClientStatus.IDLE
            self.last_time = time.monotonic()
            return []

    async def get_context_snapshot(self) -> list[dict[str, str]]:
        async with self.lock:
            await self._ensure_loaded()
            snapshot = self._context_store.trim(list(self.context))
            self.context = list(snapshot)
            return list(snapshot)

    async def record_exchange(self, user_text: str, assistant_text: str) -> list[dict[str, str]]:
        async with self.lock:
            await self._ensure_loaded()
            self._context_store.append_exchange(self.context, user_text, assistant_text)
            self.context = self._context_store.trim(self.context)
            self.last_result = None
            self.last_retrieved_events = []
            normalized = self._context_store.normalize(self.context)
            await self.gateway.save_context(self.uuid, normalized)
            self.status = ClientStatus.IDLE
            self.last_time = time.monotonic()
            return list(self.context)

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self.context = self._context_store.normalize(await self.gateway.get_context(self.uuid))
        self._loaded = True

    async def _respond_inner(self, instruct: str) -> DecisionResult:
        fast_result = await self._try_profile_direct(instruct)
        if fast_result is not None:
            return fast_result

        tool_result = await self._try_tool_direct(instruct)
        if tool_result is not None:
            return tool_result

        follow_up_result = await self._try_cached_follow_up(instruct)
        if follow_up_result is not None:
            return follow_up_result

        return await self.engine.respond(user_id=self.uuid, instruct=instruct, context=self.context)

    async def _try_profile_direct(self, instruct: str) -> DecisionResult | None:
        query_kind = _match_profile_query(instruct)
        if query_kind is None:
            return None
        user = await self.gateway.get_user(self.uuid) or {}
        response_text = _format_profile_reply(self.uuid, user, query_kind)
        trace = {"fast_path": "profile_direct", "profile_query_kind": query_kind}
        self._context_store.append_exchange(self.context, instruct, response_text)
        return DecisionResult(response_text=response_text, route="profile_direct", trace=trace)

    async def _try_tool_direct(self, instruct: str) -> DecisionResult | None:
        tools = await self.gateway.get_tools()
        tool = match_tool(instruct, tools)
        if tool is None:
            return None
        response_text = format_tool_reply(tool)
        trace = {"fast_path": "tool_direct"}
        self._context_store.append_exchange(self.context, instruct, response_text)
        return DecisionResult(
            response_text=response_text,
            route="tool_direct",
            tool_name=tool.name,
            tool_url=tool.website,
            trace=trace,
        )

    async def _try_cached_follow_up(self, instruct: str) -> DecisionResult | None:
        if not self.last_retrieved_events or not _is_cached_follow_up(instruct):
            return None

        cached_events = list(self.last_retrieved_events[: self.config.final_k])
        used_context_message_count = len(self._context_store.trim(list(self.context)))
        template_reply = _format_follow_up_template(self.last_retrieved_events, instruct)
        if template_reply is not None:
            trace = {
                "fast_path": "candidate_follow_up_template",
                "used_cached_candidate_count": len(cached_events),
                "used_context_message_count": used_context_message_count,
                "retrieved_topk": [
                    {
                        "id": event.id,
                        "title": event.title,
                        "similarity": 0.0,
                        "final_score": 0.0,
                    }
                    for event in cached_events
                ],
            }
            self._context_store.append_exchange(self.context, instruct, template_reply)
            return DecisionResult(
                response_text=template_reply,
                route="rag",
                rewritten_query=instruct,
                retrieved_event_ids=[event.id for event in cached_events],
                retrieved_events=cached_events,
                trace=trace,
            )

        return await self.engine.respond_from_candidates(
            user_id=self.uuid,
            instruct=instruct,
            context=self.context,
            candidates=self.last_retrieved_events,
        )


def _match_profile_query(instruct: str) -> str | None:
    text = instruct.strip()
    for kind, patterns in PROFILE_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            return kind
    return None


def _format_profile_reply(user_id: str, user: dict, query_kind: str) -> str:
    school = str(user.get("school") or "未填写")
    major = str(user.get("major") or "未填写")
    student_level = str(user.get("student_level") or "未填写")
    enrollment_year = user.get("enrollment_year")
    enrollment_text = str(enrollment_year) if enrollment_year not in {None, ""} else "未填写"
    interests = user.get("interest") or []
    interest_text = "、".join(str(item) for item in interests if str(item).strip()) or "未填写"
    nickname = str(user.get("nickname") or "未填写")

    if query_kind == "major":
        return f"你当前登记的专业是：{major}。"
    if query_kind == "grade":
        return f"你当前登记的年级信息是：{enrollment_text}级，培养层次是：{student_level}。"
    if query_kind == "interest":
        return f"你当前登记的兴趣方向是：{interest_text}。"
    if query_kind == "school":
        return f"你当前登记的学院/学校信息是：{school}。"
    return (
        f"你当前的用户信息是：昵称 {nickname}，用户ID {user_id}，学院/学校 {school}，"
        f"专业 {major}，年级 {enrollment_text}级，培养层次 {student_level}，兴趣 {interest_text}。"
    )


def _is_cached_follow_up(instruct: str) -> bool:
    text = instruct.strip()
    return any(marker in text for marker in FOLLOW_UP_TIME_MARKERS)


def _format_follow_up_template(events: list[EventRecord], instruct: str) -> str | None:
    if not events:
        return None
    event = events[0]
    text = instruct.strip()
    if "报名截止时间" in text or "截止时间" in text:
        if event.regis_end_time:
            return f"我优先按上一条推荐的活动理解：{event.title} 的报名截止时间是 {event.regis_end_time}。详情链接：{event.website}"
        return f"我优先按上一条推荐的活动理解：{event.title} 暂未在库里找到明确的报名截止时间。你可以直接查看原始链接：{event.website}"
    if "开始时间" in text or "活动时间" in text or "什么时候" in text:
        if event.activity_start_time:
            return f"我优先按上一条推荐的活动理解：{event.title} 的活动开始时间是 {event.activity_start_time}。"
        return f"我优先按上一条推荐的活动理解：{event.title} 暂未在库里找到明确的活动开始时间。详情可查看：{event.website}"
    if "地点" in text:
        campus_text = "、".join(event.campus) if event.campus else "暂未明确校区"
        return f"我优先按上一条推荐的活动理解：{event.title} 的地点信息是 {campus_text}。详情链接：{event.website}"
    if "链接" in text or "网址" in text:
        return f"我优先按上一条推荐的活动理解：{event.title} 的详情链接是：{event.website}"
    return None
