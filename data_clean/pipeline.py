from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape
import hashlib
import json
from pathlib import Path
from typing import Callable

from .dedupe_recall import DedupeRecallService
from .deepseek_client import DeepSeekClient
from .document_normalizer import JWC_CLEAN_RULE_VERSION, normalize_jwc_cleaned_document
from .html_cleaner import HtmlCleaner
from .input_loader import InputLoader
from .jwc_db_loader import JwcDbLoader
from .llm_dedupe import LLMDedupeService
from .llm_extract import LLMExtractService
from .llm_validate import LLMValidateService
from .manual_queue import ManualQueue
from .models import (
    AppPaths,
    JwcDbRecord,
    ManualReviewItem,
    OriginalBody,
    RawPage,
    ValidationCheck,
    WechatDbArticleRecord,
    default_app_paths,
)
from .rule_validator import RuleValidator
from .sql_sink import SqlSink
from .state_store import StateStore
from .wechat_account_resolver import WechatAccountResolver
from .wechat_batch_reset import WechatBatchResetService
from .wechat_db_loader import WechatDbLoader


class DataCleanPipeline:
    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        input_loader: InputLoader | None = None,
        jwc_db_loader: JwcDbLoader | None = None,
        wechat_account_resolver: WechatAccountResolver | None = None,
        wechat_db_loader: WechatDbLoader | None = None,
        cleaner: HtmlCleaner | None = None,
        extract_service: LLMExtractService | None = None,
        dedupe_recall: DedupeRecallService | None = None,
        dedupe_service: LLMDedupeService | None = None,
        rule_validator: RuleValidator | None = None,
        validate_service: LLMValidateService | None = None,
        state_store: StateStore | None = None,
        sql_sink: SqlSink | None = None,
        remote_llm_client: DeepSeekClient | None = None,
        max_retry: int = 2,
    ):
        self.paths = paths or default_app_paths()
        self.paths.ensure()
        self.input_loader = input_loader or InputLoader(self.paths)
        self.jwc_db_loader = jwc_db_loader or JwcDbLoader(self.paths)
        self.wechat_account_resolver = wechat_account_resolver or WechatAccountResolver(self.paths)
        self.wechat_db_loader = wechat_db_loader or WechatDbLoader(self.paths, resolver=self.wechat_account_resolver)
        self.cleaner = cleaner or HtmlCleaner(self.paths)
        self.extract_service = extract_service or LLMExtractService(self.paths)
        self.dedupe_recall = dedupe_recall or DedupeRecallService(self.paths)
        self.dedupe_service = dedupe_service or LLMDedupeService()
        self.rule_validator = rule_validator or RuleValidator()
        self.validate_service = validate_service or LLMValidateService()
        self.state_store = state_store or StateStore(self.paths)
        self.sql_sink = sql_sink or SqlSink(self.paths)
        self.manual_queue = ManualQueue(self.state_store)
        self.remote_llm_client = remote_llm_client or getattr(self.validate_service, "client", None) or DeepSeekClient()
        self.wechat_batch_reset = WechatBatchResetService(
            self.paths,
            resolver=self.wechat_account_resolver,
            loader=self.wechat_db_loader,
            state_store=self.state_store,
        )
        self.max_retry = max_retry

    def process_input_file(self, input_file: str | Path) -> dict:
        raw_page = self.input_loader.load_raw_page(input_file)
        return self.process_raw_page(raw_page)

    def process_page_id(self, page_id: str) -> dict:
        if page_id.startswith("jwc_db_"):
            record = self.jwc_db_loader.load_by_page_id(page_id)
            if record is None:
                raise FileNotFoundError(f"JwcDbRecord `{page_id}` not found in source DB.")
            return self.process_jwc_db_record(record)
        if page_id.startswith("wechat_db_"):
            record = self.wechat_db_loader.load_by_page_id(page_id)
            if record is None:
                raise FileNotFoundError(f"WechatDbArticleRecord `{page_id}` not found in source DB.")
            return self.process_wechat_db_record(record)

        raw_page = self.input_loader.load_by_page_id(page_id)
        if raw_page is None:
            raise FileNotFoundError(f"RawPage `{page_id}` not found in shared input.")
        return self.process_raw_page(raw_page)

    def process_batch(self, *, source: str | None = None, limit: int | None = None) -> dict:
        results = []
        for raw_page in self.input_loader.iter_raw_pages(source=source, limit=limit):
            results.append(self.process_raw_page(raw_page))
        return {
            "processed": len(results),
            "results": results,
        }

    def process_jwc_db_one(self, *, record_id: int) -> dict:
        record = self.jwc_db_loader.load_by_record_id(record_id)
        if record is None:
            raise FileNotFoundError(f"JwcDbRecord `{record_id}` not found in source DB.")
        return self.process_jwc_db_record(record)

    def process_jwc_db_batch(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        include_completed: bool = False,
        concurrency: int = 100,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        results = []
        pending_records = []
        skipped = 0
        counts = {
            "stored": 0,
            "duplicate": 0,
            "manual_review": 0,
            "failed": 0,
        }
        completed_statuses = {"stored", "duplicate", "manual_review"}

        for record in self.jwc_db_loader.iter_records(limit=limit, offset=offset):
            existing_status = self.state_store.get_raw_page_status(record.page_id)
            if not include_completed and existing_status in completed_statuses:
                skipped += 1
                continue
            pending_records.append(record)

        max_workers = max(1, int(concurrency))
        total = len(pending_records)
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "start",
                    "total": total,
                    "skipped": skipped,
                    "concurrency": max_workers,
                }
            )
        if max_workers == 1:
            for record in pending_records:
                result = self._process_jwc_batch_record(record)
                _accumulate_result(results, counts, result)
                _emit_progress(progress_callback, results, counts, result, total)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_record = {
                    executor.submit(self._process_jwc_batch_record, record): record for record in pending_records
                }
                for future in as_completed(future_to_record):
                    result = future.result()
                    _accumulate_result(results, counts, result)
                    _emit_progress(progress_callback, results, counts, result, total)

        results.sort(key=_result_sort_key)
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "end",
                    "processed": len(results),
                    "total": total,
                    "skipped": skipped,
                    "concurrency": max_workers,
                    "counts": dict(counts),
                }
            )

        return {
            "processed": len(results),
            "skipped": skipped,
            "concurrency": max_workers,
            "counts": counts,
            "results": results,
        }

    def process_wechat_db_one(
        self,
        *,
        article_id: int,
        account_identifier: str | None = None,
        account_dir: str | None = None,
    ) -> dict:
        record = self.wechat_db_loader.load_by_article_id(
            article_id=article_id,
            account_identifier=account_identifier,
            account_dir=account_dir,
        )
        if record is None:
            raise FileNotFoundError(f"WechatDbArticleRecord `{article_id}` not found in source DB.")
        return self.process_wechat_db_record(record)

    def process_wechat_db_account(
        self,
        *,
        account_identifier: str | None = None,
        account_dir: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        include_completed: bool = False,
        preflight: bool = True,
    ) -> dict:
        if preflight:
            self.ensure_wechat_batch_remote_llm()
        results = []
        skipped = 0
        counts = {
            "stored": 0,
            "duplicate": 0,
            "manual_review": 0,
            "failed": 0,
        }
        completed_statuses = {"stored", "duplicate"}

        resolution = self.wechat_db_loader.resolve_account(
            account_identifier=account_identifier,
            account_dir=account_dir,
        )
        for record in self.wechat_db_loader.iter_account_records(
            account_dir=resolution.account_dir,
            limit=limit,
            offset=offset,
        ):
            existing_status = self.state_store.get_raw_page_status(record.page_id)
            if not include_completed and existing_status in completed_statuses:
                skipped += 1
                continue
            result = self._process_wechat_batch_record(record)
            _accumulate_result(results, counts, result)

        results.sort(key=_result_sort_key)
        return {
            "processed": len(results),
            "skipped": skipped,
            "counts": counts,
            "account_dir": resolution.account_dir,
            "account_name": resolution.display_name,
            "results": results,
        }

    def process_wechat_db_batch(
        self,
        *,
        batch_file: str | Path,
        include_completed: bool = False,
    ) -> dict:
        self.ensure_wechat_batch_remote_llm()
        processed = 0
        skipped = 0
        counts = {
            "stored": 0,
            "duplicate": 0,
            "manual_review": 0,
            "failed": 0,
        }
        accounts = []

        for resolution in self.wechat_account_resolver.resolve_batch_file(batch_file):
            result = self.process_wechat_db_account(
                account_dir=resolution.account_dir,
                include_completed=include_completed,
                preflight=False,
            )
            accounts.append(result)
            processed += int(result.get("processed", 0))
            skipped += int(result.get("skipped", 0))
            for key in counts:
                counts[key] += int(result.get("counts", {}).get(key, 0))

        return {
            "processed": processed,
            "skipped": skipped,
            "counts": counts,
            "accounts": accounts,
        }

    def ensure_wechat_batch_remote_llm(self) -> dict:
        self.remote_llm_client.ensure_ready(model=self.remote_llm_client.config.model_llm2)
        config = self.remote_llm_client.config
        return {
            "available": True,
            "enabled": bool(config.enabled),
            "api_key_present": bool(config.api_key),
            "base_url": config.base_url,
            "model_llm1": config.model_llm1,
            "model_llm2": config.model_llm2,
            "model_llm3": config.model_llm3,
        }

    def reset_wechat_batch(self, *, batch_file: str | Path, drop_main_db: bool = True) -> dict:
        return self.wechat_batch_reset.reset_batch(batch_file=batch_file, drop_main_db=drop_main_db)

    def retry_manual(self, *, review_id: str | None = None, all_pending: bool = False) -> dict:
        items: list[dict]
        if review_id:
            item = self.manual_queue.get(review_id)
            items = [item] if item else []
        elif all_pending:
            items = self.manual_queue.list_pending()
        else:
            raise ValueError("retry_manual requires `review_id` or `all_pending=True`.")

        retried = []
        for item in items:
            if not item:
                continue
            self.manual_queue.mark_resolved(item["review_id"])
            retried.append(self.process_page_id(item["page_id"]))
        return {"retried": len(retried), "results": retried}

    def show_status(self) -> dict:
        return self.state_store.summary()

    def show_manual(self, *, status: str = "pending") -> list[dict]:
        return self.state_store.list_manual_review(status=status)

    def process_raw_page(self, raw_page: RawPage) -> dict:
        self.state_store.upsert_raw_page(raw_page, status="loaded")
        original_body = self.cleaner.clean(raw_page)
        self.state_store.attach_original_body(original_body, status="cleaned")
        return self._process_input_record(raw_page, original_body)

    def process_jwc_db_record(self, record: JwcDbRecord) -> dict:
        self.state_store.upsert_raw_page(record, status="loaded")
        original_body = self._build_original_body_from_text(record.page_id, record.cleaned_document)
        self.state_store.attach_original_body(original_body, status="cleaned")
        return self._process_input_record(record, original_body)

    def process_wechat_db_record(self, record: WechatDbArticleRecord) -> dict:
        record = self._materialize_wechat_html(record)
        self.state_store.upsert_raw_page(record, status="loaded")
        original_body = self.cleaner.clean(record)
        self.state_store.attach_original_body(original_body, status="cleaned")
        result = self._process_input_record(record, original_body)
        result.setdefault("article_id", record.article_id)
        result.setdefault("account_dir", record.account_dir)
        return result

    def _process_input_record(
        self,
        input_record: RawPage | JwcDbRecord | WechatDbArticleRecord,
        original_body: OriginalBody,
    ) -> dict:
        feedback: dict | None = None
        sink = SqlSink(self.sql_sink.paths, helper_path=self.sql_sink.helper_path)
        with sink:
            for attempt in range(1, self.max_retry + 1):
                temp_event = self.extract_service.extract(
                    raw_page=input_record,
                    original_body=original_body,
                    attempt=attempt,
                    feedback=feedback,
                )
                self.state_store.save_temp_event(temp_event)

                candidates = self.dedupe_recall.recall(temp_event)
                dedupe_check = self.dedupe_service.check(temp_event, candidates)
                self.state_store.save_dedupe_check(dedupe_check)
                if dedupe_check.is_duplicate:
                    self.state_store.mark_raw_page_status(input_record.page_id, "duplicate")
                    return {
                        "status": "duplicate",
                        "page_id": input_record.page_id,
                        "temp_id": temp_event.temp_id,
                        "matched_record_id": dedupe_check.matched_record_id,
                    }

                rule_result = self.rule_validator.validate(temp_event, original_body)
                semantic_result = self.validate_service.validate(temp_event, original_body, rule_result)
                rule_result = {**rule_result, "source_type": input_record.source_type}
                semantic_result = {**semantic_result, "source_type": input_record.source_type}
                final_passed = bool(rule_result.get("rule_passed")) and bool(semantic_result.get("semantic_passed"))
                validation_check = ValidationCheck.create(
                    temp_id=temp_event.temp_id,
                    rule_result=rule_result,
                    semantic_result=semantic_result,
                    final_passed=final_passed,
                )
                self.state_store.save_validation_check(validation_check)

                if final_passed:
                    record_id = sink.upsert_event(temp_event.to_school_event_record())
                    self.state_store.mark_raw_page_status(input_record.page_id, "stored")
                    return {
                        "status": "stored",
                        "page_id": input_record.page_id,
                        "temp_id": temp_event.temp_id,
                        "record_id": record_id,
                    }

                feedback = {
                    "rule_failed_fields": [
                        field
                        for field in rule_result.get("checked_fields", [])
                        if not rule_result.get(field, True)
                    ],
                    "rule_result": rule_result,
                    "semantic_feedback": semantic_result.get("semantic_feedback", ""),
                    "field_feedback": semantic_result.get("field_feedback", {}),
                }

            manual_item = ManualReviewItem.create(
                page_id=input_record.page_id,
                temp_id=temp_event.temp_id,
                retry_count=self.max_retry,
                reason=semantic_result.get("semantic_feedback", "规则与语义核验连续失败。"),
                reason_code=str(semantic_result.get("failure_type") or "validation_failed"),
                reason_detail_json=json.dumps(
                    {
                        "source_type": input_record.source_type,
                        "rule_feedback": rule_result,
                        "semantic_feedback": semantic_result.get("semantic_feedback", ""),
                        "field_feedback": semantic_result.get("field_feedback", {}),
                        "failure_type": semantic_result.get("failure_type", "validation_failed"),
                        "attempt": self.max_retry,
                    },
                    ensure_ascii=False,
                ),
            )
            self.manual_queue.enqueue(manual_item)
            self.state_store.mark_raw_page_status(input_record.page_id, "manual_review")
            return {
                "status": "manual_review",
                "page_id": input_record.page_id,
                "temp_id": temp_event.temp_id,
                "review_id": manual_item.review_id,
            }

    def _process_jwc_batch_record(self, record: JwcDbRecord) -> dict:
        try:
            result = self.process_jwc_db_record(record)
        except Exception as exc:
            return {
                "status": "failed",
                "page_id": record.page_id,
                "record_id": record.record_id,
                "error": str(exc),
            }
        result.setdefault("record_id", record.record_id)
        return result

    def _process_wechat_batch_record(self, record: WechatDbArticleRecord) -> dict:
        try:
            result = self.process_wechat_db_record(record)
        except Exception as exc:
            return {
                "status": "failed",
                "page_id": record.page_id,
                "article_id": record.article_id,
                "account_dir": record.account_dir,
                "error": str(exc),
            }
        result.setdefault("article_id", record.article_id)
        result.setdefault("account_dir", record.account_dir)
        return result

    def _build_original_body_from_text(self, page_id: str, text: str) -> OriginalBody:
        normalized = normalize_jwc_cleaned_document(text)
        content_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        output_path = self.cleaner.paths.raw_cache_dir / f"{page_id}.original.txt"
        output_path.write_text(normalized, encoding="utf-8")
        return OriginalBody(
            page_id=page_id,
            original_text=normalized,
            content_hash=content_hash,
            clean_rule_version=JWC_CLEAN_RULE_VERSION,
            original_text_path=str(output_path),
        )

    def _materialize_wechat_html(self, record: WechatDbArticleRecord) -> WechatDbArticleRecord:
        raw_html = record.content_html.strip() or self._wrap_wechat_content_text(record.content_text)
        cache_dir = self.cleaner.paths.raw_cache_dir / "wechat_batch1"
        cache_dir.mkdir(parents=True, exist_ok=True)
        output_path = cache_dir / f"{record.page_id}.raw.html"
        output_path.write_text(raw_html, encoding="utf-8")
        record.raw_html_path = str(output_path)
        return record

    def _wrap_wechat_content_text(self, content_text: str) -> str:
        lines = [escape(line) for line in content_text.splitlines() if line.strip()]
        body = "<br/>\n".join(lines) if lines else escape(content_text)
        return f"<html><body><article>{body}</article></body></html>"


def _accumulate_result(results: list[dict], counts: dict[str, int], result: dict) -> None:
    status = str(result.get("status") or "")
    if status in counts:
        counts[status] += 1
    results.append(result)


def _result_sort_key(result: dict) -> tuple[int, str]:
    record_id = result.get("record_id")
    if isinstance(record_id, int):
        return (record_id, str(result.get("page_id") or ""))
    return (10**12, str(result.get("page_id") or ""))


def _emit_progress(
    progress_callback: Callable[[dict], None] | None,
    results: list[dict],
    counts: dict[str, int],
    result: dict,
    total: int,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "event": "progress",
            "completed": len(results),
            "total": total,
            "status": str(result.get("status") or ""),
            "page_id": str(result.get("page_id") or ""),
            "record_id": result.get("record_id"),
            "counts": dict(counts),
        }
    )
