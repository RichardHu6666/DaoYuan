from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ClientStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class ToolRecord:
    name: str
    website: str
    description: str


@dataclass
class EventRecord:
    id: int
    title: str
    summary: str
    website: str
    regis_end_time: str | None
    activity_start_time: str | None
    campus: list[str]
    topics: list[str]
    target_grade: list[int]
    embedded_summary: bytes | None
    cleaned_document: str | None = None


@dataclass
class RetrievedEvent:
    event: EventRecord
    similarity: float
    final_score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class DecisionResult:
    response_text: str
    route: str
    tool_name: str | None = None
    tool_url: str | None = None
    rewritten_query: str | None = None
    retrieved_event_ids: list[int] = field(default_factory=list)
    retrieved_events: list[EventRecord] = field(default_factory=list)
    missing_profile_fields: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass
class Llm1RouteResult:
    route: str
    intent: str
    rewritten_query: str
    tool_name: str | None = None
    tool_reason: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    need_profile_fields: list[str] = field(default_factory=list)
    profile_used_fields: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], fallback_query: str) -> "Llm1RouteResult":
        filters = payload.get("filters")
        if not isinstance(filters, dict):
            filters = {}
        return cls(
            route=str(payload.get("route") or "rag").strip().lower(),
            intent=str(payload.get("intent") or "").strip(),
            rewritten_query=str(payload.get("rewritten_query") or fallback_query).strip() or fallback_query,
            tool_name=_optional_text(payload.get("tool_name")),
            tool_reason=str(payload.get("tool_reason") or "").strip(),
            filters={
                "topics": _string_list(filters.get("topics")),
                "campus": _string_list(filters.get("campus")),
                "target_grade": _int_list(filters.get("target_grade")),
                "time_hint": filters.get("time_hint"),
            },
            need_profile_fields=_string_list(payload.get("need_profile_fields")),
            profile_used_fields=_string_list(payload.get("profile_used_fields")),
        )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            output.append(text)
    return output


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    output: list[int] = []
    for item in value:
        try:
            output.append(int(item))
        except (TypeError, ValueError):
            continue
    return output
