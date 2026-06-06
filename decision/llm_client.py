from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import DecisionConfig
from .prompts import pretty_json


class DecisionLlmClient:
    def __init__(self, config: DecisionConfig):
        self.config = config
        self._client = httpx.Client(
            timeout=self.config.request_timeout_seconds,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    def chat_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_tokens: int | None = None,
        disable_thinking: bool = False,
    ) -> dict[str, Any]:
        content = self._chat(
            model=model,
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=max_tokens,
            disable_thinking=disable_thinking,
        )
        return _parse_json_content(content)

    def chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_tokens: int | None = None,
        disable_thinking: bool = False,
    ) -> str:
        return self._chat(
            model=model,
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=max_tokens,
            disable_thinking=disable_thinking,
        ).strip()

    def _chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_tokens: int | None = None,
        disable_thinking: bool = False,
    ) -> str:
        if not self.config.llm_api_key:
            raise RuntimeError(
                "Missing LLM API key. Expected it from ~/.bashrc via DECISION_LLM_API_KEY or DEEPSEEK_API_KEY."
            )
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": pretty_json(user_payload)},
            ],
            "stream": False,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if disable_thinking and _is_deepseek_api(self.config.llm_base_url):
            body["thinking"] = {"type": "disabled"}
        last_error: Exception | None = None
        attempts = max(1, self.config.max_retries + 1)
        for attempt in range(1, attempts + 1):
            try:
                response = self._client.post(
                    f"{self.config.llm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.config.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
                return str(payload["choices"][0]["message"]["content"])
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, KeyError, IndexError, TypeError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))
        raise RuntimeError(f"LLM request failed: {last_error}")

    def close(self) -> None:
        self._client.close()


def _parse_json_content(content: str) -> dict[str, Any]:
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
    raise RuntimeError(f"Unable to parse JSON from model response: {content}")


def _is_deepseek_api(base_url: str) -> bool:
    return "deepseek.com" in base_url.lower()
