from __future__ import annotations

import json
import re

from .models import EventRecord, ToolRecord


def llm1_system_prompt() -> str:
    return (
        "你是 CampusJarvis 的 LLM1 路由器。"
        "你只输出 JSON，不要输出额外解释。"
        "你的任务是判断用户请求应该走 tool_direct、rag 还是 clarify。"
        "如果用户请求可以直接通过固定工具网址解决，就返回 tool_direct。"
        "如果信息不充分，就返回 clarify。"
        "否则返回 rag，并给出简洁的 rewritten_query 和 filters。"
    )


def llm2_system_prompt() -> str:
    return (
        "你是 CampusJarvis 的 LLM2 决策助手。"
        "你基于候选校园活动和用户画像生成最终中文回答。"
        "优先使用候选事件，不要编造数据库里没有的信息。"
        "如果 missing_profile_fields 非空且请求带有个性化倾向，"
        "请明确说明当前推荐为通用推荐，并引导用户补充资料。"
        "直接回答用户问题，再补一句简短建议即可。"
        "禁止输出 markdown、标题、项目符号、编号列表、加粗、代码块或链接语法。"
        "输出必须是简洁自然的纯文字。"
    )


def build_llm1_payload(
    *,
    instruct: str,
    tools: list[ToolRecord],
    user_profile: dict,
    context_summary: str,
) -> dict:
    return {
        "instruct": instruct,
        "tools": [tool.__dict__ for tool in tools],
        "user_profile": user_profile,
        "context_summary": context_summary,
        "required_output_schema": {
            "route": "tool_direct | rag | clarify",
            "intent": "string",
            "rewritten_query": "string",
            "tool_name": "string or null",
            "tool_reason": "string",
            "filters": {
                "topics": [],
                "campus": [],
                "target_grade": [],
                "time_hint": None,
            },
            "need_profile_fields": [],
            "profile_used_fields": [],
        },
    }


def build_llm2_payload(
    *,
    instruct: str,
    rewritten_query: str,
    context: list[dict],
    user_profile_summary: dict,
    candidates: list[EventRecord],
    missing_profile_fields: list[str],
) -> dict:
    return {
        "instruct": instruct,
        "rewritten_query": rewritten_query,
        "context": context,
        "user_profile_summary": user_profile_summary,
        "missing_profile_fields": missing_profile_fields,
        "candidates": [
            {
                "id": event.id,
                "title": event.title,
                "summary": event.summary,
                "website": event.website,
                "regis_end_time": event.regis_end_time,
                "activity_start_time": event.activity_start_time,
                "campus": event.campus,
                "topics": event.topics,
            }
            for event in candidates[:3]
        ],
        "instructions": (
            "优先基于 candidates 组织回答。"
            "若 candidates 为空，请明确说明暂未找到足够匹配的校园活动。"
            "直接先回答，再补一句建议。"
            "总长度尽量控制在简短范围内。"
            "输出自然中文纯文字，不要输出 JSON，不要使用任何 markdown 格式。"
        ),
    }


def format_tool_reply(tool: ToolRecord, reason: str | None = None) -> str:
    lines = [f"你可以直接使用这个工具：{tool.name}", f"网址：{tool.website}"]
    if reason:
        lines.append(f"说明：{reason}")
    elif tool.description:
        lines.append(f"说明：{tool.description}")
    return "\n".join(lines)


def format_candidate_fallback(candidates: list[EventRecord], missing_profile_fields: list[str]) -> str:
    if not candidates:
        return "暂时没有找到足够匹配的校园活动。你可以换个更具体的说法试试，比如活动主题、校区或时间范围。"

    top_events = candidates[:3]
    event_text = "；".join(
        f"{event.title}，可查看 {event.website}" + (f"，摘要是 {event.summary}" if event.summary else "")
        for event in top_events
    )
    if missing_profile_fields:
        return (
            f"我先按通用信息给你推荐几条相关活动：{event_text}。"
            "由于你的兴趣或年级等资料还不完整，这次先给通用推荐；如果你补充资料，我可以继续帮你缩小范围。"
        )
    return f"我先给你推荐几条相关活动：{event_text}。如果你愿意，我可以再按主题、校区或时间继续帮你缩小范围。"


def normalize_plain_text_response(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = re.sub(r"```.*?```", "", normalized, flags=re.DOTALL)
    normalized = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", normalized)
    normalized = normalized.replace("**", "").replace("__", "").replace("`", "")
    cleaned_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[-*+]\s*", "", line)
        line = re.sub(r"^\d+\.\s*", "", line)
        cleaned_lines.append(line)
    normalized = "\n".join(cleaned_lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def pretty_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
