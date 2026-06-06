from __future__ import annotations

from dataclasses import dataclass

from .document_normalizer import normalize_cleaned_document
from .models import JwcDbRecord, RawPage, TempEvent, WechatDbArticleRecord


@dataclass(frozen=True)
class SourcePolicy:
    source_type: str
    require_remote_llm_for_batch: bool
    require_title_in_original_text: bool
    allow_time_fields_all_empty: bool
    anchor_title_to_source: bool
    anchor_website_to_source: bool

    def finalize_temp_event(
        self,
        temp_event: TempEvent,
        input_record: RawPage | JwcDbRecord | WechatDbArticleRecord,
    ) -> TempEvent:
        temp_event.cleaned_document = normalize_cleaned_document(temp_event.cleaned_document)
        if self.anchor_website_to_source:
            temp_event.website = input_record.source_url
        if self.anchor_title_to_source:
            temp_event.title = input_record.title
        return temp_event


WECHAT_DB_POLICY = SourcePolicy(
    source_type="wechat_db",
    require_remote_llm_for_batch=True,
    require_title_in_original_text=False,
    allow_time_fields_all_empty=True,
    anchor_title_to_source=True,
    anchor_website_to_source=True,
)

JWC_DB_POLICY = SourcePolicy(
    source_type="jwc_db",
    require_remote_llm_for_batch=False,
    require_title_in_original_text=True,
    allow_time_fields_all_empty=True,
    anchor_title_to_source=True,
    anchor_website_to_source=True,
)

RAW_PAGE_POLICY = SourcePolicy(
    source_type="raw_page",
    require_remote_llm_for_batch=False,
    require_title_in_original_text=True,
    allow_time_fields_all_empty=True,
    anchor_title_to_source=False,
    anchor_website_to_source=False,
)


def get_source_policy(source_type: str) -> SourcePolicy:
    normalized = str(source_type or "").strip()
    if normalized == "wechat_db":
        return WECHAT_DB_POLICY
    if normalized == "jwc_db":
        return JWC_DB_POLICY
    return RAW_PAGE_POLICY


def detect_source_type_from_page_id(page_id: str) -> str:
    if page_id.startswith("wechat_db_"):
        return "wechat_db"
    if page_id.startswith("jwc_db_"):
        return "jwc_db"
    return "raw_page"
