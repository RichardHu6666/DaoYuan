from __future__ import annotations

import re

from .deepseek_client import DeepSeekClient
from .models import DedupeCheck, TempEvent


class LLMDedupeService:
    def __init__(self):
        self.client = DeepSeekClient()

    def check(self, temp_event: TempEvent, candidates: list[dict]) -> DedupeCheck:
        if self.client.is_available():
            return self._check_remote(temp_event, candidates)
        return self._check_fallback(temp_event, candidates)

    def _check_remote(self, temp_event: TempEvent, candidates: list[dict]) -> DedupeCheck:
        system_prompt = (
            "你是 LLM2 (deepseek-v4-flash) 的重复活动判定器。"
            "只在 candidate 和某条旧记录明确是同一活动时，才输出 is_duplicate=true。"
            "只输出 JSON。"
        )
        payload = {
            "temp_event": temp_event.to_dict(),
            "candidate_records": candidates,
            "required_output_schema": {
                "is_duplicate": "boolean",
                "matched_record_id": "integer|null",
                "duplicate_reason": "string",
            },
        }
        response = self.client.chat_json(
            model=self.client.config.model_llm2,
            system_prompt=system_prompt,
            user_payload=payload,
        )
        return DedupeCheck.create(
            temp_id=temp_event.temp_id,
            recall_key=temp_event.regis_start_time,
            candidate_record_ids=[int(item["id"]) for item in candidates if item.get("id") is not None],
            is_duplicate=bool(response.get("is_duplicate", False)),
            matched_record_id=_optional_int(response.get("matched_record_id")),
            duplicate_reason=str(response.get("duplicate_reason") or ""),
        )

    def _check_fallback(self, temp_event: TempEvent, candidates: list[dict]) -> DedupeCheck:
        normalized_title = _normalize_text(temp_event.title)
        normalized_doc = _normalize_text(temp_event.cleaned_document)
        for candidate in candidates:
            candidate_title = _normalize_text(str(candidate.get("title", "")))
            candidate_doc = _normalize_text(str(candidate.get("cleaned_document", "")))
            if normalized_title and normalized_title == candidate_title:
                return DedupeCheck.create(
                    temp_id=temp_event.temp_id,
                    recall_key=temp_event.regis_start_time,
                    candidate_record_ids=[int(item["id"]) for item in candidates if item.get("id") is not None],
                    is_duplicate=True,
                    matched_record_id=int(candidate["id"]),
                    duplicate_reason="标题在相同报名开始时间候选中完全一致。",
                )
            if normalized_doc and candidate_doc and normalized_doc[:120] == candidate_doc[:120]:
                return DedupeCheck.create(
                    temp_id=temp_event.temp_id,
                    recall_key=temp_event.regis_start_time,
                    candidate_record_ids=[int(item["id"]) for item in candidates if item.get("id") is not None],
                    is_duplicate=True,
                    matched_record_id=int(candidate["id"]),
                    duplicate_reason="正文前段在相同报名开始时间候选中一致。",
                )
        return DedupeCheck.create(
            temp_id=temp_event.temp_id,
            recall_key=temp_event.regis_start_time,
            candidate_record_ids=[int(item["id"]) for item in candidates if item.get("id") is not None],
            is_duplicate=False,
            matched_record_id=None,
            duplicate_reason="未发现同一活动语义重复。",
        )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).strip().lower()


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
