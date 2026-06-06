from __future__ import annotations

from .models import ToolRecord


KEYWORD_TOOLS: dict[str, list[str]] = {
    "教务系统": ["成绩", "课表", "选课", "教务系统", "培养方案", "考试安排"],
    "图书馆": ["图书馆", "馆藏", "借书", "还书"],
    "校历": ["校历", "学期安排"],
}


def match_tool(instruct: str, tools: list[ToolRecord]) -> ToolRecord | None:
    lowered = instruct.strip()
    if not lowered or not tools:
        return None

    matched_tools: list[ToolRecord] = []
    for tool_name, keywords in KEYWORD_TOOLS.items():
        if not any(keyword in lowered for keyword in keywords):
            continue
        tool = _find_tool_by_name(tool_name, tools)
        if tool is not None and tool not in matched_tools:
            matched_tools.append(tool)

    if len(matched_tools) == 1:
        return matched_tools[0]
    return None


def find_tool_by_name(tool_name: str | None, tools: list[ToolRecord]) -> ToolRecord | None:
    if not tool_name:
        return None
    return _find_tool_by_name(tool_name, tools)


def _find_tool_by_name(tool_name: str, tools: list[ToolRecord]) -> ToolRecord | None:
    target = tool_name.strip().lower()
    for tool in tools:
        if target in tool.name.lower():
            return tool
    return None
