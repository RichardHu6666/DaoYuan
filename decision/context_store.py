from __future__ import annotations


class ContextStore:
    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns

    def normalize(self, context: list[dict] | None) -> list[dict[str, str]]:
        if not isinstance(context, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in context:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role in {"user", "assistant", "system"} and content:
                normalized.append({"role": role, "content": content})
        return normalized

    def trim(self, context: list[dict[str, str]]) -> list[dict[str, str]]:
        max_messages = max(1, self.max_turns) * 2
        if len(context) <= max_messages:
            return context
        return context[-max_messages:]

    def append_exchange(self, context: list[dict[str, str]], user_text: str, assistant_text: str) -> list[dict[str, str]]:
        context.append({"role": "user", "content": user_text})
        context.append({"role": "assistant", "content": assistant_text})
        trimmed = self.trim(context)
        context[:] = trimmed
        return context

    def summarize(self, context: list[dict[str, str]], *, max_messages: int = 4) -> str:
        recent = context[-max_messages:]
        return "\n".join(f"{item['role']}: {item['content']}" for item in recent)
