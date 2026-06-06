from __future__ import annotations

import json
import time

import httpx

from .config import DeepSeekConfig, load_deepseek_config


class DeepSeekClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


class DeepSeekPreflightError(DeepSeekClientError):
    """Raised when remote LLM preflight fails."""


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig | None = None):
        self.config = config or load_deepseek_config()

    def is_available(self) -> bool:
        return bool(self.config.enabled and self.config.api_key)

    def ensure_ready(self, *, model: str | None = None) -> dict:
        probe_model = model or self.config.model_llm2
        if not self.config.enabled:
            raise DeepSeekPreflightError("DATA_CLEAN_USE_REMOTE_LLM is disabled.", error_type="config_error")
        if not self.config.api_key:
            raise DeepSeekPreflightError("DeepSeek API key is missing.", error_type="config_error")
        if not self.config.base_url:
            raise DeepSeekPreflightError("DeepSeek base_url is missing.", error_type="config_error")
        if not probe_model:
            raise DeepSeekPreflightError("DeepSeek model_llm2 is missing.", error_type="config_error")

        started_at = time.perf_counter()
        try:
            content = self.chat_text(
                model=probe_model,
                system_prompt="Reply with a short confirmation.",
                user_message="ping",
            )
        except DeepSeekClientError as exc:
            raise DeepSeekPreflightError(str(exc), error_type=exc.error_type, status_code=exc.status_code) from exc

        if not content.strip():
            raise DeepSeekPreflightError(
                "DeepSeek preflight returned an empty assistant message.",
                error_type="protocol_error",
            )

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "available": True,
            "model": probe_model,
            "base_url": self.config.base_url,
            "latency_ms": latency_ms,
        }

    def chat_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict,
        reasoning_effort: str | None = None,
        thinking_enabled: bool | None = None,
    ) -> dict:
        content = self.chat_text(
            model=model,
            system_prompt=system_prompt,
            user_message=json.dumps(user_payload, ensure_ascii=False, indent=2),
            reasoning_effort=reasoning_effort,
            thinking_enabled=thinking_enabled,
        )
        return _parse_json_content(content)

    def chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        reasoning_effort: str | None = None,
        thinking_enabled: bool | None = None,
    ) -> str:
        if not self.is_available():
            raise DeepSeekClientError("DeepSeek API is not configured.", error_type="config_error")

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        if thinking_enabled is not None:
            body["thinking"] = {"type": "enabled" if thinking_enabled else "disabled"}

        payload = self._post_with_retries(body)
        return _extract_message_content(payload)

    def _post_with_retries(self, body: dict) -> dict:
        last_error: DeepSeekClientError | None = None
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
                if _should_retry_status(response.status_code) and attempt < attempts:
                    time.sleep(_retry_delay_seconds(attempt))
                    continue
                if response.status_code >= 400:
                    raise DeepSeekClientError(
                        f"DeepSeek API request failed with status {response.status_code}: {response.text}",
                        error_type="api_error",
                        status_code=response.status_code,
                    )
                try:
                    payload = response.json()
                except json.JSONDecodeError as exc:
                    raise DeepSeekClientError(
                        f"DeepSeek API returned invalid JSON: {response.text}",
                        error_type="protocol_error",
                        status_code=response.status_code,
                    ) from exc
                if not isinstance(payload, dict):
                    raise DeepSeekClientError(
                        f"Unexpected DeepSeek response shape: {payload}",
                        error_type="protocol_error",
                        status_code=response.status_code,
                    )
                return payload
            except httpx.TimeoutException as exc:
                last_error = DeepSeekClientError(
                    f"DeepSeek API request timed out: {exc}",
                    error_type="transport_error",
                )
            except httpx.TransportError as exc:
                last_error = DeepSeekClientError(
                    f"DeepSeek API transport failed: {exc}",
                    error_type="transport_error",
                )
            except DeepSeekClientError as exc:
                last_error = exc

            if attempt >= attempts and last_error is not None:
                raise last_error
            time.sleep(_retry_delay_seconds(attempt))

        if last_error is None:
            raise DeepSeekClientError("DeepSeek API request failed.", error_type="transport_error")
        raise last_error


def _extract_message_content(payload: dict) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekClientError(
            f"Unexpected DeepSeek response shape: {payload}",
            error_type="protocol_error",
        ) from exc

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    raise DeepSeekClientError(
        f"Unexpected DeepSeek message content: {content}",
        error_type="protocol_error",
    )


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
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError as exc:
            raise DeepSeekClientError(
                f"Unable to parse JSON from DeepSeek response: {content}",
                error_type="parse_error",
            ) from exc
        if isinstance(parsed, dict):
            return parsed
    raise DeepSeekClientError(
        f"Unable to parse JSON from DeepSeek response: {content}",
        error_type="parse_error",
    )


def _should_retry_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _retry_delay_seconds(attempt: int) -> float:
    return min(2 ** (attempt - 1), 8)
