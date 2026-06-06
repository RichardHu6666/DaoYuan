from __future__ import annotations

from .deepseek_client import DeepSeekClient
from .models import OriginalBody, TempEvent
from .source_policy import detect_source_type_from_page_id, get_source_policy


class LLMValidateService:
    def __init__(self, client: DeepSeekClient | None = None):
        self.client = client or DeepSeekClient()

    def validate(
        self,
        temp_event: TempEvent,
        original_body: OriginalBody,
        rule_result: dict,
        *,
        source_type: str | None = None,
    ) -> dict:
        if self.client.is_available():
            return self._validate_remote(temp_event, original_body, rule_result, source_type=source_type)
        return self._validate_fallback(temp_event, original_body, rule_result, source_type=source_type)

    def _validate_remote(
        self,
        temp_event: TempEvent,
        original_body: OriginalBody,
        rule_result: dict,
        *,
        source_type: str | None = None,
    ) -> dict:
        system_prompt = (
            "You are LLM3 for semantic faithfulness validation. "
            "Check whether temp_event is faithful to original_text, especially time fields. "
            "Return JSON only."
        )
        normalized_source_type = source_type or detect_source_type_from_page_id(temp_event.page_id)
        payload = {
            "temp_event": temp_event.to_dict(),
            "original_text": original_body.original_text,
            "rule_result": rule_result,
            "source_type": normalized_source_type,
            "required_output_schema": {
                "semantic_passed": "boolean",
                "semantic_feedback": "string",
                "field_feedback": "object",
                "failure_type": "string",
            },
        }
        response = self.client.chat_json(
            model=self.client.config.model_llm3,
            system_prompt=system_prompt,
            user_payload=payload,
            reasoning_effort="high",
            thinking_enabled=True,
        )
        semantic_passed = bool(response.get("semantic_passed", False))
        return {
            "semantic_passed": semantic_passed,
            "semantic_feedback": str(response.get("semantic_feedback") or ""),
            "field_feedback": _string_dict(response.get("field_feedback")),
            "failure_type": str(response.get("failure_type") or _default_failure_type(semantic_passed)),
            "source_type": normalized_source_type,
        }

    def _validate_fallback(
        self,
        temp_event: TempEvent,
        original_body: OriginalBody,
        rule_result: dict,
        *,
        source_type: str | None = None,
    ) -> dict:
        normalized_source_type = source_type or detect_source_type_from_page_id(temp_event.page_id)
        policy = get_source_policy(normalized_source_type)
        if not rule_result.get("rule_passed", False):
            field_feedback = {
                field: "Rule validation failed: the extracted field does not appear in original_text."
                for field in rule_result.get("checked_fields", [])
                if not rule_result.get(field, True)
            }
            return {
                "semantic_passed": False,
                "semantic_feedback": "Time fields do not align with original_text.",
                "field_feedback": field_feedback,
                "failure_type": "time_field_mismatch",
                "source_type": normalized_source_type,
            }
        if not temp_event.cleaned_document.strip():
            return {
                "semantic_passed": False,
                "semantic_feedback": "cleaned_document is empty.",
                "field_feedback": {"cleaned_document": "The candidate cleaned_document is empty."},
                "failure_type": "empty_cleaned_document",
                "source_type": normalized_source_type,
            }
        if not temp_event.website.strip():
            return {
                "semantic_passed": False,
                "semantic_feedback": "website is empty or lost.",
                "field_feedback": {"website": "website must stay anchored to the source article URL."},
                "failure_type": "missing_website",
                "source_type": normalized_source_type,
            }
        if (
            policy.require_title_in_original_text
            and temp_event.title.strip()
            and temp_event.title.strip() not in original_body.original_text
        ):
            return {
                "semantic_passed": False,
                "semantic_feedback": "Title does not appear in original_text.",
                "field_feedback": {"title": "title is inconsistent with original_text."},
                "failure_type": "title_not_in_original_text",
                "source_type": normalized_source_type,
            }
        return {
            "semantic_passed": True,
            "semantic_feedback": "The candidate event is consistent with original_text.",
            "field_feedback": {},
            "failure_type": "passed",
            "source_type": normalized_source_type,
        }


def _string_dict(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _default_failure_type(semantic_passed: bool) -> str:
    return "passed" if semantic_passed else "semantic_validation_failed"
