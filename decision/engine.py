from __future__ import annotations

from copy import deepcopy
from typing import Any

from .config import DecisionConfig, load_config
from .context_store import ContextStore
from .db_gateway import DecisionDBGateway
from .embedder import EmbeddingProvider, build_embedding_provider
from .llm_client import DecisionLlmClient
from .models import DecisionResult, EventRecord, Llm1RouteResult
from .prompts import (
    build_llm1_payload,
    build_llm2_payload,
    format_candidate_fallback,
    format_tool_reply,
    llm1_system_prompt,
    llm2_system_prompt,
    normalize_plain_text_response,
)
from .ranking import RuleRanker
from .retriever import VectorRetriever
from .tool_router import find_tool_by_name, match_tool


class DecisionEngine:
    def __init__(
        self,
        *,
        config: DecisionConfig | None = None,
        gateway: DecisionDBGateway | None = None,
        llm_client: DecisionLlmClient | None = None,
        embedder: EmbeddingProvider | None = None,
        retriever: VectorRetriever | None = None,
        ranker: RuleRanker | None = None,
        context_store: ContextStore | None = None,
    ):
        self.config = config or load_config()
        self.gateway = gateway or DecisionDBGateway(self.config)
        self.llm_client = llm_client or DecisionLlmClient(self.config)
        self.embedder = embedder or build_embedding_provider(self.config)
        self.retriever = retriever or VectorRetriever(config=self.config, gateway=self.gateway, embedder=self.embedder)
        self.ranker = ranker or RuleRanker(self.config)
        self.context_store = context_store or ContextStore(self.config.context_max_turns)

    async def respond(self, *, user_id: str, instruct: str, context: list[dict]) -> DecisionResult:
        user = await self.gateway.get_user(user_id) or {}
        tools = await self.gateway.get_tools()
        normalized_context = self.context_store.normalize(context)
        context[:] = normalized_context

        trace = {
            "rule_tool_match": None,
            "llm1_route": None,
            "llm1_fallback": False,
            "llm1_clarify_override": None,
            "fast_path": None,
            "rewritten_query": None,
            "filters": {},
            "missing_profile_fields": [],
            "candidate_count_before_vector": 0,
            "retrieved_topk": [],
            "used_context_message_count": 0,
            "llm2_fallback": False,
        }

        rule_tool = match_tool(instruct, tools)
        if rule_tool is not None:
            response_text = format_tool_reply(rule_tool)
            self.context_store.append_exchange(context, instruct, response_text)
            trace["rule_tool_match"] = {
                "name": rule_tool.name,
                "website": rule_tool.website,
                "description": rule_tool.description,
            }
            return DecisionResult(
                response_text=response_text,
                route="tool_direct",
                tool_name=rule_tool.name,
                tool_url=rule_tool.website,
                trace=trace,
            )

        keyword_route = _keyword_rag_route(instruct)
        if keyword_route is not None:
            route = keyword_route
            llm1_fallback = False
            trace["fast_path"] = "keyword_rag"
        else:
            route, llm1_fallback = await self._route_request(instruct=instruct, tools=tools, user=user, context=context)
        trace["llm1_route"] = {
            "route": route.route,
            "intent": route.intent,
            "tool_name": route.tool_name,
            "tool_reason": route.tool_reason,
            "need_profile_fields": list(route.need_profile_fields),
            "profile_used_fields": list(route.profile_used_fields),
        }
        trace["llm1_fallback"] = llm1_fallback

        clarify_override = _maybe_override_clarify_route(instruct=instruct, context=context, route=route)
        if clarify_override is not None:
            route, override_reason = clarify_override
            trace["llm1_clarify_override"] = override_reason

        route = _sanitize_route(instruct=instruct, route=route)

        trace["rewritten_query"] = route.rewritten_query
        trace["filters"] = deepcopy(route.filters)

        if route.route == "tool_direct":
            tool = find_tool_by_name(route.tool_name, tools)
            if tool is not None:
                response_text = format_tool_reply(tool, route.tool_reason)
                self.context_store.append_exchange(context, instruct, response_text)
                return DecisionResult(
                    response_text=response_text,
                    route="tool_direct",
                    tool_name=tool.name,
                    tool_url=tool.website,
                    rewritten_query=route.rewritten_query,
                    trace=trace,
                )

        if route.route == "clarify":
            response_text = route.tool_reason or "你可以再具体一点说明你的需求，比如活动主题、时间范围或你想查的工具。"
            self.context_store.append_exchange(context, instruct, response_text)
            return DecisionResult(
                response_text=response_text,
                route="clarify",
                rewritten_query=route.rewritten_query,
                trace=trace,
            )

        missing_profile_fields = _missing_profile_fields(user, instruct, route)
        trace["missing_profile_fields"] = list(missing_profile_fields)

        retrieved, retrieval_trace = await self.retriever.retrieve_with_trace(query=route.rewritten_query, filters=route.filters)
        trace["candidate_count_before_vector"] = int(retrieval_trace.get("candidate_count_before_vector") or 0)
        trace["retrieval"] = retrieval_trace

        ranked = self.ranker.rank(retrieved, user=user, filters=route.filters)
        trace["retrieved_topk"] = [
            {
                "id": item.event.id,
                "title": item.event.title,
                "similarity": round(item.similarity, 6),
                "final_score": round(item.final_score, 6),
            }
            for item in ranked
        ]
        candidates = [item.event for item in ranked]
        trace["used_context_message_count"] = len(self.context_store.trim(list(context)))

        response_text, llm2_fallback = await self._build_final_response(
            instruct=instruct,
            route=route,
            context=context,
            user=user,
            candidates=candidates,
            missing_profile_fields=missing_profile_fields,
        )
        trace["llm2_fallback"] = llm2_fallback
        self.context_store.append_exchange(context, instruct, response_text)
        return DecisionResult(
            response_text=response_text,
            route="rag",
            rewritten_query=route.rewritten_query,
            retrieved_event_ids=[item.event.id for item in ranked],
            retrieved_events=list(candidates),
            missing_profile_fields=missing_profile_fields,
            trace=trace,
        )

    async def respond_from_candidates(
        self,
        *,
        user_id: str,
        instruct: str,
        context: list[dict],
        candidates: list[EventRecord],
    ) -> DecisionResult:
        user = await self.gateway.get_user(user_id) or {}
        missing_profile_fields = _missing_profile_fields(
            user,
            instruct,
            Llm1RouteResult(route="rag", intent="candidate_follow_up", rewritten_query=instruct),
        )
        trace = {
            "rule_tool_match": None,
            "llm1_route": None,
            "llm1_fallback": False,
            "llm1_clarify_override": None,
            "fast_path": "candidate_follow_up_llm2",
            "rewritten_query": instruct,
            "filters": {},
            "missing_profile_fields": list(missing_profile_fields),
            "candidate_count_before_vector": len(candidates),
            "retrieved_topk": [
                {
                    "id": event.id,
                    "title": event.title,
                    "similarity": 0.0,
                    "final_score": 0.0,
                }
                for event in candidates[: self.config.final_k]
            ],
            "used_context_message_count": len(self.context_store.trim(list(context))),
            "llm2_fallback": False,
        }
        response_text, llm2_fallback = await self._build_final_response(
            instruct=instruct,
            route=Llm1RouteResult(route="rag", intent="candidate_follow_up", rewritten_query=instruct),
            context=context,
            user=user,
            candidates=candidates[: self.config.final_k],
            missing_profile_fields=missing_profile_fields,
        )
        trace["llm2_fallback"] = llm2_fallback
        self.context_store.append_exchange(context, instruct, response_text)
        return DecisionResult(
            response_text=response_text,
            route="rag",
            rewritten_query=instruct,
            retrieved_event_ids=[item.id for item in candidates[: self.config.final_k]],
            retrieved_events=list(candidates[: self.config.final_k]),
            missing_profile_fields=missing_profile_fields,
            trace=trace,
        )

    def close(self) -> None:
        if hasattr(self.llm_client, "close"):
            self.llm_client.close()
        if hasattr(self.embedder, "close"):
            self.embedder.close()

    async def _route_request(
        self,
        *,
        instruct: str,
        tools: list,
        user: dict[str, Any],
        context: list[dict],
    ) -> tuple[Llm1RouteResult, bool]:
        payload = build_llm1_payload(
            instruct=instruct,
            tools=tools,
            user_profile=_user_profile_summary(user),
            context_summary=self.context_store.summarize(context),
        )
        try:
            result = self.llm_client.chat_json(
                model=self.config.llm1_model,
                system_prompt=llm1_system_prompt(),
                user_payload=payload,
                max_tokens=160,
                disable_thinking=True,
            )
            return Llm1RouteResult.from_payload(result, instruct), False
        except Exception:
            return (
                Llm1RouteResult(
                    route="rag",
                    intent="fallback",
                    rewritten_query=instruct,
                    filters={"topics": [], "campus": [], "target_grade": [], "time_hint": None},
                ),
                True,
            )

    async def _build_final_response(
        self,
        *,
        instruct: str,
        route: Llm1RouteResult,
        context: list[dict],
        user: dict[str, Any],
        candidates: list[EventRecord],
        missing_profile_fields: list[str],
    ) -> tuple[str, bool]:
        payload = build_llm2_payload(
            instruct=instruct,
            rewritten_query=route.rewritten_query,
            context=self.context_store.trim(list(context)),
            user_profile_summary=_user_profile_summary(user),
            candidates=candidates,
            missing_profile_fields=missing_profile_fields,
        )
        try:
            return (
                normalize_plain_text_response(
                    self.llm_client.chat_text(
                        model=self.config.llm2_model,
                        system_prompt=llm2_system_prompt(),
                        user_payload=payload,
                        max_tokens=220,
                        disable_thinking=True,
                    )
                ),
                False,
            )
        except Exception:
            return normalize_plain_text_response(format_candidate_fallback(candidates, missing_profile_fields)), True


def _user_profile_summary(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "nickname": user.get("nickname"),
        "school": user.get("school"),
        "major": user.get("major"),
        "student_level": user.get("student_level"),
        "enrollment_year": user.get("enrollment_year"),
        "interest": user.get("interest") or [],
        "profile": user.get("profile"),
    }


def _missing_profile_fields(user: dict[str, Any], instruct: str, route: Llm1RouteResult) -> list[str]:
    personalized_keywords = ["适合我", "我的兴趣", "推荐给我", "我能参加", "适合我的"]
    personalized = any(keyword in instruct for keyword in personalized_keywords)
    personalized = personalized or bool(route.need_profile_fields)
    if not personalized:
        return []

    required = ["interest", "school", "major", "enrollment_year", "student_level"]
    missing: list[str] = []
    for field in required:
        value = user.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing


def _maybe_override_clarify_route(
    *,
    instruct: str,
    context: list[dict],
    route: Llm1RouteResult,
) -> tuple[Llm1RouteResult, str] | None:
    if route.route != "clarify":
        return None

    if _is_context_follow_up(instruct, context):
        anchor = _latest_user_message(context)
        rewritten_query = f"{anchor} {instruct}".strip() if anchor else instruct
        return (
            Llm1RouteResult(
                route="rag",
                intent=route.intent or "context_follow_up",
                rewritten_query=rewritten_query,
                filters=_normalized_filters(route.filters),
                need_profile_fields=list(route.need_profile_fields),
                profile_used_fields=list(route.profile_used_fields),
            ),
            "context_follow_up",
        )

    if _is_personalized_request(instruct, route):
        return (
            Llm1RouteResult(
                route="rag",
                intent=route.intent or "missing_profile_fallback",
                rewritten_query=instruct,
                filters=_normalized_filters(route.filters),
                need_profile_fields=list(route.need_profile_fields),
                profile_used_fields=list(route.profile_used_fields),
            ),
            "missing_profile_fallback",
        )

    return None


def _is_personalized_request(instruct: str, route: Llm1RouteResult) -> bool:
    personalized_keywords = ["适合我", "我的兴趣", "推荐给我", "我能参加", "适合我的"]
    return any(keyword in instruct for keyword in personalized_keywords) or bool(route.need_profile_fields)


def _is_context_follow_up(instruct: str, context: list[dict]) -> bool:
    text = instruct.strip()
    if not text or not context:
        return False
    if len(text) > 24:
        return False
    follow_up_markers = ["那", "这个", "那个", "该活动", "这场", "那场", "它", "报名", "截止", "时间", "地点", "什么时候"]
    return any(marker in text for marker in follow_up_markers)


def _latest_user_message(context: list[dict]) -> str:
    for message in reversed(context):
        if str(message.get("role") or "").strip() != "user":
            continue
        content = str(message.get("content") or "").strip()
        if content:
            return content
    return ""


def _normalized_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    raw = filters or {}
    return {
        "topics": list(raw.get("topics") or []),
        "campus": list(raw.get("campus") or []),
        "target_grade": list(raw.get("target_grade") or []),
        "time_hint": raw.get("time_hint"),
    }


def _sanitize_route(*, instruct: str, route: Llm1RouteResult) -> Llm1RouteResult:
    if route.route != "rag":
        return route
    query_text = instruct if _contains_filter_markers(instruct) else (route.rewritten_query or instruct)
    filters = _sanitize_filters(query_text, route.filters)
    return Llm1RouteResult(
        route=route.route,
        intent=route.intent,
        rewritten_query=route.rewritten_query,
        tool_name=route.tool_name,
        tool_reason=route.tool_reason,
        filters=filters,
        need_profile_fields=list(route.need_profile_fields),
        profile_used_fields=list(route.profile_used_fields),
    )


def _sanitize_filters(query_text: str, filters: dict[str, Any] | None) -> dict[str, Any]:
    raw = _normalized_filters(filters)
    text = query_text.strip()

    topic_markers = []
    if "讲座" in text:
        topic_markers.append("讲座")
    if "竞赛" in text or "比赛" in text:
        topic_markers.append("竞赛")
    if "AI" in text or "人工智能" in text:
        topic_markers.append("AI")

    campus_markers = [name for name in ("九龙湖", "四牌楼", "丁家桥", "无锡") if name in text]

    if topic_markers:
        raw["topics"] = topic_markers
    else:
        raw["topics"] = [item for item in raw["topics"] if item in {"讲座", "竞赛", "AI"}]

    if campus_markers:
        raw["campus"] = campus_markers
    else:
        raw["campus"] = []

    return raw


def _contains_filter_markers(text: str) -> bool:
    markers = ["讲座", "竞赛", "比赛", "AI", "人工智能", "九龙湖", "四牌楼", "丁家桥", "无锡"]
    return any(marker in text for marker in markers)


def _keyword_rag_route(instruct: str) -> Llm1RouteResult | None:
    text = instruct.strip()
    if not text:
        return None

    topics: list[str] = []
    if "讲座" in text:
        topics.append("讲座")
    if "竞赛" in text or "比赛" in text:
        topics.append("竞赛")
    if "AI" in text or "人工智能" in text:
        topics.append("AI")
    if not topics:
        return None

    campus = [name for name in ("九龙湖", "四牌楼", "丁家桥", "无锡") if name in text]
    time_hint = "近期" if ("最近" in text or "近期" in text) else None
    return Llm1RouteResult(
        route="rag",
        intent="keyword_fast_rag",
        rewritten_query=text,
        filters={
            "topics": topics,
            "campus": campus,
            "target_grade": [],
            "time_hint": time_hint,
        },
    )
