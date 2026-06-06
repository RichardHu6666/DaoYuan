from __future__ import annotations

import json

import httpx

from .config import DeepSeekConfig, load_deepseek_config


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig | None = None):
        self.config = config or load_deepseek_config()

    def is_available(self) -> bool:
        return bool(self.config.enabled and self.config.api_key)

    def chat_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict,
        reasoning_effort: str | None = None,
        thinking_enabled: bool | None = None,
    ) -> dict:
        if not self.is_available():
            raise RuntimeError("DeepSeek API is not configured.")

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
            ],
            "stream": False,
        }
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        if thinking_enabled is not None:
            body["thinking"] = {"type": "enabled" if thinking_enabled else "disabled"}

        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(
                f"{self.config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"DeepSeek API request failed with status {response.status_code}: {response.text}"
                ) from exc
            payload = response.json()

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected DeepSeek response shape: {payload}") from exc
        return _parse_json_content(content)


def _parse_json_content(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        parsed = json.loads(snippet)
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError(f"Unable to parse JSON from DeepSeek response: {content}")
