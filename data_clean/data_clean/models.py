from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utcnow_str() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass
class RawPage:
    page_id: str
    source_type: str
    source_name: str
    source_url: str
    title: str
    raw_html_path: str
    published_at: str | None = None
    fetched_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RawPage":
        required = [
            "page_id",
            "source_type",
            "source_name",
            "source_url",
            "title",
            "raw_html_path",
        ]
        missing = [key for key in required if not payload.get(key)]
        if missing:
            raise ValueError(f"RawPage missing required fields: {', '.join(missing)}")
        return cls(
            page_id=str(payload["page_id"]),
            source_type=str(payload["source_type"]),
            source_name=str(payload["source_name"]),
            source_url=str(payload["source_url"]),
            title=str(payload["title"]),
            raw_html_path=str(payload["raw_html_path"]),
            published_at=_optional_str(payload.get("published_at")),
            fetched_at=_optional_str(payload.get("fetched_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JwcDbRecord:
    record_id: int
    website: str
    title: str
    cleaned_document: str

    @property
    def page_id(self) -> str:
        return f"jwc_db_{self.record_id}"

    @property
    def source_type(self) -> str:
        return "jwc_db"

    @property
    def source_name(self) -> str:
        return "school_event_table"

    @property
    def source_url(self) -> str:
        return self.website

    @property
    def raw_html_path(self) -> str:
        return ""

    @property
    def published_at(self) -> str | None:
        return None

    @property
    def fetched_at(self) -> str | None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "page_id": self.page_id,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "title": self.title,
            "cleaned_document": self.cleaned_document,
        }


@dataclass
class WechatAccountResolution:
    account_dir: str
    display_name: str
    alias: str | None
    input_name: str
    biz_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WechatDbArticleRecord:
    article_id: int
    account_dir: str
    account_name: str
    biz_key: str
    article_url: str
    title: str
    content_html: str
    content_text: str
    publish_time: str | None = None
    raw_html_path: str = ""

    @property
    def page_id(self) -> str:
        return f"wechat_db_{self.biz_key}_{self.article_id}"

    @property
    def source_type(self) -> str:
        return "wechat_db"

    @property
    def source_name(self) -> str:
        return self.account_name

    @property
    def source_url(self) -> str:
        return self.article_url

    @property
    def published_at(self) -> str | None:
        return self.publish_time

    @property
    def fetched_at(self) -> str | None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "page_id": self.page_id,
            "account_dir": self.account_dir,
            "account_name": self.account_name,
            "biz_key": self.biz_key,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "title": self.title,
            "content_html": self.content_html,
            "content_text": self.content_text,
            "publish_time": self.publish_time,
            "raw_html_path": self.raw_html_path,
        }


@dataclass
class OriginalBody:
    page_id: str
    original_text: str
    content_hash: str
    clean_rule_version: str
    original_text_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TempEvent:
    temp_id: str
    page_id: str
    attempt: int
    website: str
    title: str
    cleaned_document: str
    summary: str
    regis_start_time: str | None = None
    regis_end_time: str | None = None
    activity_start_time: str | None = None
    campus: list[str] = field(default_factory=list)
    target_grade: list[int] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    evidence: dict[str, str | None] = field(default_factory=dict)
    need_retry: bool = False
    retry_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        *,
        page_id: str,
        attempt: int,
        website: str,
        title: str,
        cleaned_document: str,
        summary: str,
        regis_start_time: str | None = None,
        regis_end_time: str | None = None,
        activity_start_time: str | None = None,
        campus: list[str] | None = None,
        target_grade: list[int] | None = None,
        topics: list[str] | None = None,
        evidence: dict[str, str | None] | None = None,
        need_retry: bool = False,
        retry_reason: str = "",
    ) -> "TempEvent":
        return cls(
            temp_id=make_id("temp"),
            page_id=page_id,
            attempt=attempt,
            website=website,
            title=title,
            cleaned_document=cleaned_document,
            summary=summary,
            regis_start_time=regis_start_time,
            regis_end_time=regis_end_time,
            activity_start_time=activity_start_time,
            campus=campus or [],
            target_grade=target_grade or [],
            topics=topics or [],
            evidence=evidence or {},
            need_retry=need_retry,
            retry_reason=retry_reason,
        )

    def to_school_event_record(self) -> "SchoolEventRecord":
        return SchoolEventRecord(
            website=self.website,
            title=self.title,
            cleaned_document=self.cleaned_document,
            summary=self.summary,
            embedded_summary=None,
            regis_start_time=self.regis_start_time,
            regis_end_time=self.regis_end_time,
            activity_start_time=self.activity_start_time,
            campus=self.campus,
            target_grade=self.target_grade,
            topics=self.topics,
        )


@dataclass
class DedupeCheck:
    dedupe_id: str
    temp_id: str
    recall_key: str | None
    candidate_record_ids: list[int]
    is_duplicate: bool
    matched_record_id: int | None
    duplicate_reason: str

    @classmethod
    def create(
        cls,
        *,
        temp_id: str,
        recall_key: str | None,
        candidate_record_ids: list[int],
        is_duplicate: bool,
        matched_record_id: int | None,
        duplicate_reason: str,
    ) -> "DedupeCheck":
        return cls(
            dedupe_id=make_id("dedupe"),
            temp_id=temp_id,
            recall_key=recall_key,
            candidate_record_ids=candidate_record_ids,
            is_duplicate=is_duplicate,
            matched_record_id=matched_record_id,
            duplicate_reason=duplicate_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationCheck:
    validation_id: str
    temp_id: str
    rule_result: dict[str, Any]
    semantic_result: dict[str, Any]
    final_passed: bool

    @classmethod
    def create(
        cls,
        *,
        temp_id: str,
        rule_result: dict[str, Any],
        semantic_result: dict[str, Any],
        final_passed: bool,
    ) -> "ValidationCheck":
        return cls(
            validation_id=make_id("validation"),
            temp_id=temp_id,
            rule_result=rule_result,
            semantic_result=semantic_result,
            final_passed=final_passed,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManualReviewItem:
    review_id: str
    page_id: str
    temp_id: str
    retry_count: int
    reason: str
    reason_code: str
    reason_detail_json: str
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        *,
        page_id: str,
        temp_id: str,
        retry_count: int,
        reason: str,
        reason_code: str = "validation_failed",
        reason_detail_json: str = "{}",
        status: str = "pending",
    ) -> "ManualReviewItem":
        now = utcnow_str()
        return cls(
            review_id=make_id("review"),
            page_id=page_id,
            temp_id=temp_id,
            retry_count=retry_count,
            reason=reason,
            reason_code=reason_code,
            reason_detail_json=reason_detail_json,
            status=status,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SchoolEventRecord:
    website: str
    title: str
    cleaned_document: str
    summary: str
    embedded_summary: bytes | None
    regis_start_time: str | None
    regis_end_time: str | None
    activity_start_time: str | None
    campus: list[str]
    target_grade: list[int]
    topics: list[str]

    def to_db_row(self) -> dict[str, Any]:
        return {
            "website": self.website,
            "title": self.title,
            "cleaned_document": self.cleaned_document,
            "summary": self.summary,
            "embedded_summary": self.embedded_summary,
            "regis_start_time": self.regis_start_time,
            "regis_end_time": self.regis_end_time,
            "activity_start_time": self.activity_start_time,
            "campus": self.campus or None,
            "target_grade": self.target_grade or None,
            "topics": self.topics or None,
        }


@dataclass
class AppPaths:
    repo_root: Path
    app_root: Path
    package_root: Path
    prompts_dir: Path
    runtime_dir: Path
    raw_cache_dir: Path
    logs_dir: Path
    sidecar_db_path: Path
    shared_root: Path
    input_root: Path
    output_root: Path
    cache_root: Path
    meta_root: Path
    jwc_source_db_path: Path
    wechat_control_db_path: Path
    wechat_accounts_root: Path
    wechat_batch_root: Path
    main_db_path: Path
    schema_path: Path

    def ensure(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.raw_cache_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.shared_root.mkdir(parents=True, exist_ok=True)
        self.input_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.meta_root.mkdir(parents=True, exist_ok=True)
        self.wechat_control_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.wechat_accounts_root.mkdir(parents=True, exist_ok=True)
        self.wechat_batch_root.mkdir(parents=True, exist_ok=True)
        self.main_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema_path.parent.mkdir(parents=True, exist_ok=True)
        for source in ("wechat", "jwc", "open_web"):
            (self.input_root / source).mkdir(parents=True, exist_ok=True)


def default_app_paths() -> AppPaths:
    repo_root = Path(__file__).resolve().parents[2]
    app_root = repo_root / "data_clean"
    shared_root = repo_root / "data" / "data_clean"
    default_jwc_source = repo_root / "data" / "seu_campus_assistant.db"
    default_wechat_root = repo_root / "data" / "wechat_ingest"
    default_main_db = shared_root / "output" / "seu_campus_assistant.db"
    if repo_root == Path("/root/data_process"):
        default_jwc_source = Path("/root/data_process/data/seu_campus_assistant.db")
        default_wechat_root = Path("/root/data_process/data/wechat_ingest")
        default_main_db = Path("/root/rivermind-data/database/seu_campus_assistant.db")
    jwc_source_db_path = Path(os.environ.get("DATA_CLEAN_JWC_SOURCE_DB_PATH", str(default_jwc_source)))
    wechat_control_db_path = Path(
        os.environ.get(
            "DATA_CLEAN_WECHAT_CONTROL_DB_PATH",
            str(default_wechat_root / "control" / "control.sqlite3"),
        )
    )
    wechat_accounts_root = Path(
        os.environ.get(
            "DATA_CLEAN_WECHAT_ACCOUNTS_ROOT",
            str(default_wechat_root / "accounts"),
        )
    )
    main_db_path = Path(os.environ.get("DATA_CLEAN_MAIN_DB_PATH", str(default_main_db)))
    return AppPaths(
        repo_root=repo_root,
        app_root=app_root,
        package_root=app_root / "data_clean",
        prompts_dir=app_root / "prompts",
        runtime_dir=app_root / "runtime",
        raw_cache_dir=app_root / "runtime" / "raw_cache",
        logs_dir=app_root / "runtime" / "logs",
        sidecar_db_path=app_root / "runtime" / "process_state.sqlite3",
        shared_root=shared_root,
        input_root=shared_root / "input",
        output_root=shared_root / "output",
        cache_root=shared_root / "cache",
        meta_root=shared_root / "meta",
        jwc_source_db_path=jwc_source_db_path,
        wechat_control_db_path=wechat_control_db_path,
        wechat_accounts_root=wechat_accounts_root,
        wechat_batch_root=shared_root / "meta" / "wechat_batches",
        main_db_path=main_db_path,
        schema_path=shared_root / "meta" / "input_contracts" / "raw_page.schema.json",
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
