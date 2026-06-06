from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from html import escape
import hashlib
import json
from pathlib import Path
import threading
import traceback
from typing import Callable

from .dedupe_recall import DedupeRecallService
from .deepseek_client import DeepSeekClient, DeepSeekClientError
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
    make_id,
)
from .rule_validator import RuleValidator
from .sql_sink import SqlSink
from .state_store import StateStore
from .source_policy import get_source_policy
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
        self._state_lock = threading.RLock()
        self._main_db_lock = threading.RLock()
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
        concurrency: int = 100,
        preflight: bool = True,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        if preflight:
            self.ensure_wechat_batch_remote_llm()
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
            pending_records.append(record)

        max_workers = max(1, int(concurrency))
        total = len(pending_records)
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "wechat_account_start",
                    "account_name": resolution.display_name,
                    "account_dir": resolution.account_dir,
                    "total": total,
                    "skipped": skipped,
                    "concurrency": max_workers,
                }
            )

        if max_workers == 1:
            for record in pending_records:
                result = self._process_wechat_batch_record(record)
                _accumulate_result(results, counts, result)
                _emit_wechat_progress(
                    progress_callback,
                    account_name=resolution.display_name,
                    account_dir=resolution.account_dir,
                    results=results,
                    counts=counts,
                    result=result,
                    total=total,
                    concurrency=max_workers,
                )
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_record = {
                    executor.submit(self._process_wechat_batch_record, record): record for record in pending_records
                }
                for future in as_completed(future_to_record):
                    result = future.result()
                    _accumulate_result(results, counts, result)
                    _emit_wechat_progress(
                        progress_callback,
                        account_name=resolution.display_name,
                        account_dir=resolution.account_dir,
                        results=results,
                        counts=counts,
                        result=result,
                        total=total,
                        concurrency=max_workers,
                    )

        results.sort(key=_result_sort_key)
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "wechat_account_end",
                    "account_name": resolution.display_name,
                    "account_dir": resolution.account_dir,
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
            "account_dir": resolution.account_dir,
            "account_name": resolution.display_name,
            "results": results,
        }

    def process_wechat_db_batch(
        self,
        *,
        batch_file: str | Path,
        include_completed: bool = False,
        concurrency: int = 100,
        progress_callback: Callable[[dict], None] | None = None,
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
        accounts_by_dir: dict[str, dict] = {}
        pending_items: list[tuple[dict, WechatDbArticleRecord]] = []
        resolutions = self.wechat_account_resolver.resolve_batch_file(batch_file)
        completed_statuses = {"stored", "duplicate", "manual_review"}
        max_workers = max(1, int(concurrency))

        if progress_callback is not None:
            progress_callback(
                {
                    "event": "wechat_batch_start",
                    "batch_file": str(batch_file),
                    "accounts_total": len(resolutions),
                    "concurrency": max_workers,
                }
            )

        for index, resolution in enumerate(resolutions, start=1):
            account_state = {
                "account_dir": resolution.account_dir,
                "account_name": resolution.display_name,
                "processed": 0,
                "skipped": 0,
                "total": 0,
                "counts": {
                    "stored": 0,
                    "duplicate": 0,
                    "manual_review": 0,
                    "failed": 0,
                },
                "results": [],
            }
            accounts_by_dir[resolution.account_dir] = account_state
            for record in self.wechat_db_loader.iter_account_records(
                account_dir=resolution.account_dir,
            ):
                existing_status = self.state_store.get_raw_page_status(record.page_id)
                if not include_completed and existing_status in completed_statuses:
                    account_state["skipped"] += 1
                    continue
                account_state["total"] += 1
                pending_items.append((account_state, record))
            if progress_callback is not None:
                progress_callback(
                    {
                        "event": "wechat_batch_account",
                        "batch_file": str(batch_file),
                        "account_index": index,
                        "accounts_total": len(resolutions),
                        "account_name": resolution.display_name,
                        "account_dir": resolution.account_dir,
                        "concurrency": max_workers,
                    }
                )
                progress_callback(
                    {
                        "event": "wechat_account_start",
                        "account_name": resolution.display_name,
                        "account_dir": resolution.account_dir,
                        "total": account_state["total"],
                        "skipped": account_state["skipped"],
                        "concurrency": max_workers,
                    }
                )
            if account_state["total"] == 0 and progress_callback is not None:
                progress_callback(
                    {
                        "event": "wechat_account_end",
                        "account_name": resolution.display_name,
                        "account_dir": resolution.account_dir,
                        "processed": 0,
                        "total": 0,
                        "skipped": account_state["skipped"],
                        "concurrency": max_workers,
                        "counts": dict(account_state["counts"]),
                    }
                )

        skipped = sum(int(account_state["skipped"]) for account_state in accounts_by_dir.values())

        def handle_result(account_state: dict, result: dict) -> None:
            nonlocal processed
            _accumulate_result(account_state["results"], account_state["counts"], result)
            account_state["processed"] = len(account_state["results"])
            _accumulate_result([], counts, result)
            processed += 1
            _emit_wechat_progress(
                progress_callback,
                account_name=account_state["account_name"],
                account_dir=account_state["account_dir"],
                results=account_state["results"],
                counts=account_state["counts"],
                result=result,
                total=int(account_state["total"]),
                concurrency=max_workers,
            )
            if account_state["processed"] == account_state["total"] and progress_callback is not None:
                progress_callback(
                    {
                        "event": "wechat_account_end",
                        "account_name": account_state["account_name"],
                        "account_dir": account_state["account_dir"],
                        "processed": account_state["processed"],
                        "total": account_state["total"],
                        "skipped": account_state["skipped"],
                        "concurrency": max_workers,
                        "counts": dict(account_state["counts"]),
                    }
                )

        if max_workers == 1:
            for account_state, record in pending_items:
                result = self._process_wechat_batch_record(record)
                handle_result(account_state, result)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {
                    executor.submit(self._process_wechat_batch_record, record): (account_state, record)
                    for account_state, record in pending_items
                }
                for future in as_completed(future_to_item):
                    account_state, _record = future_to_item[future]
                    result = future.result()
                    handle_result(account_state, result)

        accounts = []
        for resolution in resolutions:
            account_state = accounts_by_dir[resolution.account_dir]
            account_state["results"].sort(key=_result_sort_key)
            accounts.append(
                {
                    "processed": int(account_state["processed"]),
                    "skipped": int(account_state["skipped"]),
                    "counts": dict(account_state["counts"]),
                    "account_dir": str(account_state["account_dir"]),
                    "account_name": str(account_state["account_name"]),
                    "results": list(account_state["results"]),
                }
            )

        if progress_callback is not None:
            progress_callback(
                {
                    "event": "wechat_batch_end",
                    "batch_file": str(batch_file),
                    "processed": processed,
                    "skipped": skipped,
                    "accounts_total": len(resolutions),
                    "concurrency": max_workers,
                    "counts": dict(counts),
                }
            )
        return {
            "processed": processed,
            "skipped": skipped,
            "concurrency": max_workers,
            "counts": counts,
            "accounts": accounts,
        }

    def ensure_wechat_batch_remote_llm(self) -> dict:
        result = self.remote_llm_client.ensure_ready(model=self.remote_llm_client.config.model_llm2)
        config = self.remote_llm_client.config
        return {
            "available": True,
            "enabled": bool(config.enabled),
            "api_key_present": bool(config.api_key),
            "base_url": config.base_url,
            "model_llm1": config.model_llm1,
            "model_llm2": config.model_llm2,
            "model_llm3": config.model_llm3,
            "latency_ms": result.get("latency_ms"),
            "model": result.get("model"),
        }

    def reset_wechat_batch(self, *, batch_file: str | Path, drop_main_db: bool = True) -> dict:
        return self.wechat_batch_reset.reset_batch(batch_file=batch_file, drop_main_db=drop_main_db)

    def retry_manual(
        self,
        *,
        review_id: str | None = None,
        all_pending: bool = False,
        source_type: str | None = None,
        reason_code: str | None = None,
    ) -> dict:
        items: list[dict]
        if review_id:
            item = self.manual_queue.get(review_id)
            items = [item] if item else []
        elif all_pending:
            items = _dedupe_manual_items_by_page_id(
                self.state_store.list_manual_review(
                    status="pending",
                    source_type=source_type,
                    reason_code=reason_code,
                )
            )
        else:
            raise ValueError("retry_manual requires `review_id` or `all_pending=True`.")

        retried = []
        for item in items:
            if not item:
                continue
            result = self._retry_manual_item(item)
            if result.get("status") in {"stored", "duplicate"}:
                self.state_store.update_manual_review_status_by_page_id(item["page_id"], "resolved")
            retried.append(result)
        return {"retried": len(retried), "results": retried}

    def show_status(self) -> dict:
        return self.state_store.summary()

    def show_manual(
        self,
        *,
        status: str = "pending",
        source_type: str | None = None,
        reason_code: str | None = None,
    ) -> list[dict]:
        return self.state_store.list_manual_review(
            status=status,
            source_type=source_type,
            reason_code=reason_code,
        )

    def process_raw_page(self, raw_page: RawPage) -> dict:
        self._with_state_lock(self.state_store.upsert_raw_page, raw_page, status="loaded")
        original_body = self.cleaner.clean(raw_page)
        self._with_state_lock(self.state_store.attach_original_body, original_body, status="cleaned")
        return self._process_input_record(raw_page, original_body)

    def process_jwc_db_record(self, record: JwcDbRecord) -> dict:
        self._with_state_lock(self.state_store.upsert_raw_page, record, status="loaded")
        original_body = self._build_original_body_from_text(record.page_id, record.cleaned_document)
        self._with_state_lock(self.state_store.attach_original_body, original_body, status="cleaned")
        return self._process_input_record(record, original_body)

    def process_wechat_db_record(self, record: WechatDbArticleRecord) -> dict:
        record = self._materialize_wechat_html(record)
        self._with_state_lock(self.state_store.upsert_raw_page, record, status="loaded")
        original_body = self.cleaner.clean(record)
        self._with_state_lock(self.state_store.attach_original_body, original_body, status="cleaned")
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
        source_policy = get_source_policy(input_record.source_type)
        sink = SqlSink(self.sql_sink.paths, helper_path=self.sql_sink.helper_path)
        with sink:
            for attempt in range(1, self.max_retry + 1):
                try:
                    temp_event = self.extract_service.extract(
                        raw_page=input_record,
                        original_body=original_body,
                        attempt=attempt,
                        feedback=feedback,
                    )
                except DeepSeekClientError as exc:
                    return self._queue_llm_error_manual_review(
                        input_record=input_record,
                        temp_id=make_id("temp_error"),
                        stage="llm_extract",
                        error=exc,
                        attempt=attempt,
                    )

                temp_event = source_policy.finalize_temp_event(temp_event, input_record)
                self._with_state_lock(self.state_store.save_temp_event, temp_event)

                candidates = self.dedupe_recall.recall(temp_event)
                try:
                    dedupe_check = self.dedupe_service.check(temp_event, candidates)
                except DeepSeekClientError as exc:
                    return self._queue_llm_error_manual_review(
                        input_record=input_record,
                        temp_id=temp_event.temp_id,
                        stage="llm_dedupe",
                        error=exc,
                        attempt=attempt,
                    )
                self._with_state_lock(self.state_store.save_dedupe_check, dedupe_check)
                if dedupe_check.is_duplicate:
                    self._with_state_lock(self.state_store.mark_raw_page_status, input_record.page_id, "duplicate")
                    return {
                        "status": "duplicate",
                        "page_id": input_record.page_id,
                        "temp_id": temp_event.temp_id,
                        "matched_record_id": dedupe_check.matched_record_id,
                    }

                rule_result = self.rule_validator.validate(temp_event, original_body)
                try:
                    semantic_result = self._validate_with_source_type(
                        temp_event=temp_event,
                        original_body=original_body,
                        rule_result=rule_result,
                        source_type=input_record.source_type,
                    )
                except DeepSeekClientError as exc:
                    return self._queue_llm_error_manual_review(
                        input_record=input_record,
                        temp_id=temp_event.temp_id,
                        stage="llm_validate",
                        error=exc,
                        attempt=attempt,
                        rule_result=rule_result,
                    )
                rule_result = {**rule_result, "source_type": input_record.source_type}
                semantic_result = {**semantic_result, "source_type": input_record.source_type}
                final_passed = bool(rule_result.get("rule_passed")) and bool(semantic_result.get("semantic_passed"))
                validation_check = ValidationCheck.create(
                    temp_id=temp_event.temp_id,
                    rule_result=rule_result,
                    semantic_result=semantic_result,
                    final_passed=final_passed,
                )
                self._with_state_lock(self.state_store.save_validation_check, validation_check)

                if final_passed:
                    record_id = self._with_main_db_lock(sink.upsert_event, temp_event.to_school_event_record())
                    self._with_state_lock(self.state_store.mark_raw_page_status, input_record.page_id, "stored")
                    return {
                        "status": "stored",
                        "page_id": input_record.page_id,
                        "temp_id": temp_event.temp_id,
                        "record_id": record_id,
                    }

                salvaged = self._maybe_salvage_jwc_record(
                    input_record=input_record,
                    temp_event=temp_event,
                    rule_result=rule_result,
                    semantic_result=semantic_result,
                    sink=sink,
                )
                if salvaged is not None:
                    return salvaged

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

            return self._queue_manual_review(
                input_record=input_record,
                temp_id=temp_event.temp_id,
                retry_count=self.max_retry,
                reason=str(semantic_result.get("semantic_feedback") or "规则与语义核验连续失败。"),
                reason_code=str(semantic_result.get("failure_type") or "validation_failed"),
                reason_detail={
                    "source_type": input_record.source_type,
                    "rule_feedback": rule_result,
                    "semantic_feedback": semantic_result.get("semantic_feedback", ""),
                    "field_feedback": semantic_result.get("field_feedback", {}),
                    "failure_type": semantic_result.get("failure_type", "validation_failed"),
                    "attempt": self.max_retry,
                },
            )

    def _queue_llm_error_manual_review(
        self,
        *,
        input_record: RawPage | JwcDbRecord | WechatDbArticleRecord,
        temp_id: str,
        stage: str,
        error: DeepSeekClientError,
        attempt: int,
        rule_result: dict | None = None,
    ) -> dict:
        return self._queue_manual_review(
            input_record=input_record,
            temp_id=temp_id,
            retry_count=attempt,
            reason=str(error),
            reason_code=f"{stage}_{error.error_type}",
            reason_detail={
                "source_type": input_record.source_type,
                "stage": stage,
                "error_type": error.error_type,
                "status_code": error.status_code,
                "message": str(error),
                "rule_feedback": rule_result or {},
                "attempt": attempt,
            },
        )

    def _queue_manual_review(
        self,
        *,
        input_record: RawPage | JwcDbRecord | WechatDbArticleRecord,
        temp_id: str,
        retry_count: int,
        reason: str,
        reason_code: str,
        reason_detail: dict,
    ) -> dict:
        manual_item = ManualReviewItem.create(
            page_id=input_record.page_id,
            temp_id=temp_id,
            retry_count=retry_count,
            reason=reason,
            reason_code=reason_code,
            reason_detail_json=json.dumps(reason_detail, ensure_ascii=False),
        )
        self._with_state_lock(self.manual_queue.enqueue, manual_item)
        self._with_state_lock(self.state_store.mark_raw_page_status, input_record.page_id, "manual_review")
        return {
            "status": "manual_review",
            "page_id": input_record.page_id,
            "temp_id": temp_id,
            "reason_code": reason_code,
            "review_id": manual_item.review_id,
        }

    def _validate_with_source_type(
        self,
        *,
        temp_event,
        original_body: OriginalBody,
        rule_result: dict,
        source_type: str,
    ) -> dict:
        try:
            return self.validate_service.validate(
                temp_event,
                original_body,
                rule_result,
                source_type=source_type,
            )
        except TypeError as exc:
            if "source_type" not in str(exc):
                raise
            return self.validate_service.validate(temp_event, original_body, rule_result)

    def _process_jwc_batch_record(self, record: JwcDbRecord) -> dict:
        try:
            result = self.process_jwc_db_record(record)
        except Exception as exc:
            result = self._process_jwc_db_record_with_fallback(record, exc)
        result.setdefault("record_id", record.record_id)
        return result

    def _process_wechat_batch_record(self, record: WechatDbArticleRecord) -> dict:
        try:
            result = self.process_wechat_db_record(record)
        except Exception as exc:
            return self._queue_unexpected_wechat_batch_error(record, exc)
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

    def _maybe_salvage_jwc_record(
        self,
        *,
        input_record: RawPage | JwcDbRecord | WechatDbArticleRecord,
        temp_event,
        rule_result: dict,
        semantic_result: dict,
        sink: SqlSink,
    ) -> dict | None:
        if input_record.source_type != "jwc_db":
            return None

        semantic_passed = bool(semantic_result.get("semantic_passed"))
        if semantic_passed:
            record_id = self._with_main_db_lock(sink.upsert_event, temp_event.to_school_event_record())
            self._with_state_lock(self.state_store.mark_raw_page_status, input_record.page_id, "stored")
            return {
                "status": "stored",
                "page_id": input_record.page_id,
                "temp_id": temp_event.temp_id,
                "record_id": record_id,
                "salvaged": True,
                "salvage_reason": "semantic_passed_rule_relaxed",
            }

        if _should_trust_jwc_source_title(semantic_result):
            record_id = self._with_main_db_lock(sink.upsert_event, temp_event.to_school_event_record())
            self._with_state_lock(self.state_store.mark_raw_page_status, input_record.page_id, "stored")
            return {
                "status": "stored",
                "page_id": input_record.page_id,
                "temp_id": temp_event.temp_id,
                "record_id": record_id,
                "salvaged": True,
                "salvage_reason": "jwc_source_title_anchored",
            }

        sanitized_event, cleared_fields = _sanitize_jwc_temp_event(
            temp_event=temp_event,
            rule_result=rule_result,
            semantic_result=semantic_result,
        )
        if sanitized_event is None:
            return None

        record_id = self._with_main_db_lock(sink.upsert_event, sanitized_event.to_school_event_record())
        self._with_state_lock(self.state_store.mark_raw_page_status, input_record.page_id, "stored")
        return {
            "status": "stored",
            "page_id": input_record.page_id,
            "temp_id": sanitized_event.temp_id,
            "record_id": record_id,
            "salvaged": True,
            "salvage_reason": "jwc_field_sanitized",
            "cleared_fields": cleared_fields,
        }

    def _process_jwc_db_record_with_fallback(self, record: JwcDbRecord, exc: Exception) -> dict:
        try:
            original_body = self._build_original_body_from_text(record.page_id, record.cleaned_document)
            self._with_state_lock(self.state_store.upsert_raw_page, record, status="loaded")
            self._with_state_lock(self.state_store.attach_original_body, original_body, status="cleaned")
            temp_event = self.extract_service._extract_fallback(
                raw_page=record,
                original_body=original_body,
                attempt=1,
                feedback=None,
            )
            temp_event = get_source_policy(record.source_type).finalize_temp_event(temp_event, record)
            temp_event = _sanitize_fallback_jwc_temp_event(temp_event)
            self._with_state_lock(self.state_store.save_temp_event, temp_event)
            with SqlSink(self.sql_sink.paths, helper_path=self.sql_sink.helper_path) as sink:
                record_id = self._with_main_db_lock(sink.upsert_event, temp_event.to_school_event_record())
            self._with_state_lock(self.state_store.mark_raw_page_status, record.page_id, "stored")
            return {
                "status": "stored",
                "page_id": record.page_id,
                "record_id": record_id,
                "temp_id": temp_event.temp_id,
                "salvaged": True,
                "salvage_reason": "jwc_exception_fallback",
                "fallback_error": str(exc),
            }
        except Exception as fallback_exc:
            return {
                "status": "failed",
                "page_id": record.page_id,
                "record_id": record.record_id,
                "error": str(exc),
                "fallback_error": str(fallback_exc),
            }

    def _retry_manual_item(self, item: dict) -> dict:
        page_id = str(item.get("page_id") or "")
        if page_id.startswith("jwc_db_"):
            salvaged = self._retry_jwc_manual_from_state(page_id)
            if salvaged is not None:
                return salvaged
        return self.process_page_id(page_id)

    def _retry_jwc_manual_from_state(self, page_id: str) -> dict | None:
        latest_temp_row = self.state_store.get_latest_temp_event(page_id)
        if latest_temp_row is None:
            return None
        validation_row = self.state_store.get_validation_check(str(latest_temp_row["temp_id"]))
        if validation_row is None:
            return None
        record = self.jwc_db_loader.load_by_page_id(page_id)
        if record is None:
            return None

        try:
            temp_event_payload = json.loads(str(latest_temp_row["temp_json"]))
            temp_event = _temp_event_from_payload(temp_event_payload)
            temp_event = get_source_policy(record.source_type).finalize_temp_event(temp_event, record)
            rule_result = json.loads(str(validation_row["rule_result_json"]))
            semantic_result = json.loads(str(validation_row["semantic_result_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

        with SqlSink(self.sql_sink.paths, helper_path=self.sql_sink.helper_path) as sink:
            return self._maybe_salvage_jwc_record(
                input_record=record,
                temp_event=temp_event,
                rule_result=rule_result,
                semantic_result=semantic_result,
                sink=sink,
            )

    def _queue_unexpected_wechat_batch_error(self, record: WechatDbArticleRecord, exc: Exception) -> dict:
        temp_id = make_id("temp_unexpected")
        reason = f"{type(exc).__name__}: {exc}"
        detail = {
            "source_type": record.source_type,
            "account_dir": record.account_dir,
            "article_id": record.article_id,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        try:
            result = self._queue_manual_review(
                input_record=record,
                temp_id=temp_id,
                retry_count=0,
                reason=reason,
                reason_code="unexpected_exception",
                reason_detail=detail,
            )
            result.setdefault("article_id", record.article_id)
            result.setdefault("account_dir", record.account_dir)
            result.setdefault("error", reason)
            return result
        except Exception as queue_exc:
            return {
                "status": "failed",
                "page_id": record.page_id,
                "article_id": record.article_id,
                "account_dir": record.account_dir,
                "error": reason,
                "queue_error": f"{type(queue_exc).__name__}: {queue_exc}",
            }

    def _with_state_lock(self, func: Callable, *args, **kwargs):
        with self._state_lock:
            return func(*args, **kwargs)

    def _with_main_db_lock(self, func: Callable, *args, **kwargs):
        with self._main_db_lock:
            return func(*args, **kwargs)

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


def _emit_wechat_progress(
    progress_callback: Callable[[dict], None] | None,
    *,
    account_name: str,
    account_dir: str,
    results: list[dict],
    counts: dict[str, int],
    result: dict,
    total: int,
    concurrency: int,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "event": "wechat_account_progress",
            "account_name": account_name,
            "account_dir": account_dir,
            "completed": len(results),
            "total": total,
            "status": str(result.get("status") or ""),
            "page_id": str(result.get("page_id") or ""),
            "article_id": result.get("article_id"),
            "counts": dict(counts),
            "concurrency": concurrency,
            "reason_code": result.get("reason_code"),
            "error": result.get("error"),
        }
    )


def _sanitize_jwc_temp_event(*, temp_event, rule_result: dict, semantic_result: dict):
    sanitized = deepcopy(temp_event)
    cleared_fields: list[str] = []
    for field in _collect_jwc_fields_to_clear(rule_result=rule_result, semantic_result=semantic_result):
        if field in {"regis_start_time", "regis_end_time", "activity_start_time"}:
            if getattr(sanitized, field):
                setattr(sanitized, field, None)
                sanitized.evidence[field] = None
                cleared_fields.append(field)
        elif field == "target_grade" and sanitized.target_grade:
            sanitized.target_grade = []
            cleared_fields.append(field)
        elif field == "campus" and sanitized.campus:
            sanitized.campus = []
            cleared_fields.append(field)
        elif field == "topics" and sanitized.topics:
            sanitized.topics = []
            cleared_fields.append(field)

    if not cleared_fields and not bool(semantic_result.get("semantic_passed")):
        for field in ("regis_start_time", "regis_end_time", "activity_start_time"):
            if getattr(sanitized, field):
                setattr(sanitized, field, None)
                sanitized.evidence[field] = None
                cleared_fields.append(field)

    if not cleared_fields and not bool(semantic_result.get("semantic_passed")):
        return None, []
    return sanitized, cleared_fields


def _sanitize_fallback_jwc_temp_event(temp_event):
    sanitized = deepcopy(temp_event)
    if sanitized.activity_start_time and _looks_like_default_midnight(sanitized.activity_start_time):
        sanitized.activity_start_time = None
        sanitized.evidence["activity_start_time"] = None
    return sanitized


def _collect_jwc_fields_to_clear(*, rule_result: dict, semantic_result: dict) -> list[str]:
    fields: list[str] = []
    for field in rule_result.get("checked_fields", []):
        if not rule_result.get(field, True):
            fields.append(field)

    field_feedback = semantic_result.get("field_feedback") or {}
    if isinstance(field_feedback, dict):
        for field, message in field_feedback.items():
            normalized_field = str(field)
            if normalized_field in {"regis_start_time", "regis_end_time", "activity_start_time", "target_grade", "campus", "topics"}:
                if _is_negative_field_feedback(str(message or "")):
                    fields.append(normalized_field)

    semantic_feedback = str(semantic_result.get("semantic_feedback") or "")
    if semantic_feedback:
        if _semantic_feedback_mentions_time_precision_issue(semantic_feedback):
            fields.append("activity_start_time")
        if "target_grade" in semantic_feedback or "年级" in semantic_feedback:
            if _is_negative_field_feedback(semantic_feedback):
                fields.append("target_grade")

    return list(dict.fromkeys(fields))


def _semantic_feedback_mentions_time_precision_issue(message: str) -> bool:
    keywords = [
        "上午",
        "下午",
        "晚上",
        "晚",
        "脑补",
        "00:00:00",
        "未提供具体",
        "无具体钟点",
        "具体化为",
        "午夜",
        "不应",
    ]
    return any(keyword in message for keyword in keywords)


def _is_negative_field_feedback(message: str) -> bool:
    negative_keywords = [
        "脑补",
        "不忠实",
        "无依据",
        "不应",
        "错误",
        "误导",
        "缺失",
        "遗漏",
        "推断",
        "推测",
        "未提供",
        "不符",
        "偏差",
        "halluc",
        "fabricat",
        "missing",
        "incorrect",
    ]
    positive_keywords = ["忠实", "正确", "一致", "无误", "faithful", "correct", "consistent"]
    if any(keyword in message for keyword in positive_keywords) and not any(
        keyword in message for keyword in negative_keywords
    ):
        return False
    return any(keyword in message for keyword in negative_keywords)


def _looks_like_default_midnight(value: str) -> bool:
    return str(value).endswith(" 00:00:00")


def _should_trust_jwc_source_title(semantic_result: dict) -> bool:
    failure_type = str(semantic_result.get("failure_type") or "")
    if failure_type == "title_not_in_original_text":
        return True

    field_feedback = semantic_result.get("field_feedback") or {}
    if not isinstance(field_feedback, dict):
        field_feedback = {}
    title_feedback = str(field_feedback.get("title") or "")
    semantic_feedback = str(semantic_result.get("semantic_feedback") or "")
    combined = f"{title_feedback} {semantic_feedback}".lower()
    title_markers = [
        "title does not appear in original_text",
        "title is inconsistent with original_text",
        "标题未在原始正文中出现",
        "标题未在原文中出现",
        "标题与原始正文不一致",
        "标题与原文不一致",
    ]
    return any(marker.lower() in combined for marker in title_markers)


def _dedupe_manual_items_by_page_id(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in items:
        page_id = str(item.get("page_id") or "")
        if not page_id or page_id in seen:
            continue
        seen.add(page_id)
        deduped.append(item)
    return deduped


def _temp_event_from_payload(payload: dict):
    from .models import TempEvent

    data = dict(payload)
    return TempEvent(
        temp_id=str(data.get("temp_id") or ""),
        page_id=str(data.get("page_id") or ""),
        attempt=int(data.get("attempt") or 1),
        website=str(data.get("website") or ""),
        title=str(data.get("title") or ""),
        cleaned_document=str(data.get("cleaned_document") or ""),
        summary=str(data.get("summary") or ""),
        regis_start_time=data.get("regis_start_time"),
        regis_end_time=data.get("regis_end_time"),
        activity_start_time=data.get("activity_start_time"),
        campus=list(data.get("campus") or []),
        target_grade=list(data.get("target_grade") or []),
        topics=list(data.get("topics") or []),
        evidence=dict(data.get("evidence") or {}),
        need_retry=bool(data.get("need_retry", False)),
        retry_reason=str(data.get("retry_reason") or ""),
    )
