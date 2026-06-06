from __future__ import annotations

import json
import time

import httpx

from .config import DeepSeekConfig, load_deepseek_config


class DeepSeekPreflightError(RuntimeError):
    """Raised when remote LLM preflight fails."""


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig | None = None):
        self.config = config or load_deepseek_config()

    def is_available(self) -> bool:
        return bool(self.config.enabled and self.config.api_key)

    def ensure_ready(self, *, model: str | None = None) -> None:
        if not self.config.enabled:
            raise DeepSeekPreflightError("DATA_CLEAN_USE_REMOTE_LLM is disabled.")
        if not self.config.api_key:
            raise DeepSeekPreflightError("DeepSeek API key is missing.")
        probe_model = model or self.config.model_llm2
        try:
            payload = self.chat_json(
                model=probe_model,
                system_prompt="Return JSON only.",
                user_payload={"probe": "ping", "required_output_schema": {"ok": "boolean"}},
                reasoning_effort="low",
                thinking_enabled=False,
            )
        except Exception as exc:
            raise DeepSeekPreflightError(f"DeepSeek preflight failed: {exc}") from exc
        if not isinstance(payload, dict) or "ok" not in payload:
            raise DeepSeekPreflightError(f"DeepSeek preflight returned unexpected payload: {payload}")

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

        last_error: Exception | None = None
        attempts = max(1, int(self.config.max_retries) + 1)
        for attempt in range(1, attempts + 1):
            try:
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
                        if _should_retry_status(response.status_code) and attempt < attempts:
                            time.sleep(_retry_delay_seconds(attempt))
                            continue
                        raise RuntimeError(
                            f"DeepSeek API request failed with status {response.status_code}: {response.text}"
                        ) from exc
                    payload = response.json()
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise RuntimeError(
                        f"DeepSeek API request failed after {attempts} attempts: {exc}"
                    ) from exc
                time.sleep(_retry_delay_seconds(attempt))
        else:
            raise RuntimeError(f"DeepSeek API request failed: {last_error}")

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


def _should_retry_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _retry_delay_seconds(attempt: int) -> float:
    return min(2**(attempt - 1), 8)
