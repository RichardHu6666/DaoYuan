from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import (
    AppPaths,
    DedupeCheck,
    JwcDbRecord,
    ManualReviewItem,
    OriginalBody,
    RawPage,
    TempEvent,
    ValidationCheck,
    WechatDbArticleRecord,
    default_app_paths,
    utcnow_str,
)


class StateStore:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or default_app_paths()
        self.paths.ensure()
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.paths.sidecar_db_path, timeout=30.0, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")
        connection.execute("PRAGMA busy_timeout = 30000;")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_pages (
                    page_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    raw_html_path TEXT NOT NULL,
                    original_text_path TEXT,
                    content_hash TEXT,
                    clean_rule_version TEXT,
                    published_at TEXT,
                    fetched_at TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS temp_events (
                    temp_id TEXT PRIMARY KEY,
                    page_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    temp_json TEXT NOT NULL,
                    need_retry INTEGER NOT NULL DEFAULT 0,
                    retry_reason TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dedupe_checks (
                    dedupe_id TEXT PRIMARY KEY,
                    temp_id TEXT NOT NULL,
                    recall_key TEXT,
                    candidate_record_ids_json TEXT NOT NULL,
                    is_duplicate INTEGER NOT NULL,
                    matched_record_id INTEGER,
                    duplicate_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS validation_checks (
                    validation_id TEXT PRIMARY KEY,
                    temp_id TEXT NOT NULL,
                    rule_result_json TEXT NOT NULL,
                    semantic_result_json TEXT NOT NULL,
                    final_passed INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS manual_review_queue (
                    review_id TEXT PRIMARY KEY,
                    page_id TEXT NOT NULL,
                    temp_id TEXT NOT NULL,
                    retry_count INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    reason_code TEXT NOT NULL DEFAULT 'validation_failed',
                    reason_detail_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_manual_review_columns(conn)

    def upsert_raw_page(
        self,
        raw_page: RawPage | JwcDbRecord | WechatDbArticleRecord,
        *,
        status: str = "loaded",
    ) -> None:
        now = utcnow_str()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO raw_pages (
                    page_id, source_type, source_name, source_url, title, raw_html_path,
                    published_at, fetched_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    source_type=excluded.source_type,
                    source_name=excluded.source_name,
                    source_url=excluded.source_url,
                    title=excluded.title,
                    raw_html_path=excluded.raw_html_path,
                    published_at=excluded.published_at,
                    fetched_at=excluded.fetched_at,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    raw_page.page_id,
                    raw_page.source_type,
                    raw_page.source_name,
                    raw_page.source_url,
                    raw_page.title,
                    raw_page.raw_html_path,
                    raw_page.published_at,
                    raw_page.fetched_at,
                    status,
                    now,
                    now,
                ),
            )

    def attach_original_body(self, original_body: OriginalBody, *, status: str = "cleaned") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE raw_pages
                SET original_text_path = ?, content_hash = ?, clean_rule_version = ?, status = ?, updated_at = ?
                WHERE page_id = ?
                """,
                (
                    original_body.original_text_path,
                    original_body.content_hash,
                    original_body.clean_rule_version,
                    status,
                    utcnow_str(),
                    original_body.page_id,
                ),
            )

    def mark_raw_page_status(self, page_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE raw_pages SET status = ?, updated_at = ? WHERE page_id = ?",
                (status, utcnow_str(), page_id),
            )

    def get_raw_page_status(self, page_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT status FROM raw_pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            return None if row is None else str(row["status"])

    def get_raw_page_entry(self, page_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM raw_pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            return None if row is None else dict(row)

    def save_temp_event(self, temp_event: TempEvent) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO temp_events (
                    temp_id, page_id, attempt, temp_json, need_retry, retry_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    temp_event.temp_id,
                    temp_event.page_id,
                    temp_event.attempt,
                    json.dumps(temp_event.to_dict(), ensure_ascii=False),
                    int(temp_event.need_retry),
                    temp_event.retry_reason,
                    utcnow_str(),
                ),
            )

    def get_latest_temp_event(self, page_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM temp_events
                WHERE page_id = ?
                ORDER BY attempt DESC, created_at DESC
                LIMIT 1
                """,
                (page_id,),
            ).fetchone()
            return None if row is None else dict(row)

    def save_dedupe_check(self, dedupe_check: DedupeCheck) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dedupe_checks (
                    dedupe_id, temp_id, recall_key, candidate_record_ids_json,
                    is_duplicate, matched_record_id, duplicate_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dedupe_check.dedupe_id,
                    dedupe_check.temp_id,
                    dedupe_check.recall_key,
                    json.dumps(dedupe_check.candidate_record_ids, ensure_ascii=False),
                    int(dedupe_check.is_duplicate),
                    dedupe_check.matched_record_id,
                    dedupe_check.duplicate_reason,
                    utcnow_str(),
                ),
            )

    def save_validation_check(self, validation_check: ValidationCheck) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO validation_checks (
                    validation_id, temp_id, rule_result_json, semantic_result_json, final_passed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    validation_check.validation_id,
                    validation_check.temp_id,
                    json.dumps(validation_check.rule_result, ensure_ascii=False),
                    json.dumps(validation_check.semantic_result, ensure_ascii=False),
                    int(validation_check.final_passed),
                    utcnow_str(),
                ),
            )

    def get_validation_check(self, temp_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM validation_checks
                WHERE temp_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (temp_id,),
            ).fetchone()
            return None if row is None else dict(row)

    def enqueue_manual_review(self, item: ManualReviewItem) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO manual_review_queue (
                    review_id, page_id, temp_id, retry_count, reason, reason_code, reason_detail_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.review_id,
                    item.page_id,
                    item.temp_id,
                    item.retry_count,
                    item.reason,
                    item.reason_code,
                    item.reason_detail_json,
                    item.status,
                    item.created_at,
                    item.updated_at,
                ),
            )

    def list_manual_review(
        self,
        status: str | None = None,
        source_type: str | None = None,
        reason_code: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM manual_review_queue"
        params: list = []
        clauses: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if source_type:
            prefix = _page_id_prefix_for_source_type(source_type)
            if prefix is not None:
                clauses.append("page_id LIKE ?")
                params.append(f"{prefix}%")
            elif str(source_type).strip() == "raw_page":
                clauses.append("page_id NOT LIKE ? AND page_id NOT LIKE ?")
                params.extend(["wechat_db_%", "jwc_db_%"])
        if reason_code:
            clauses.append("reason_code = ?")
            params.append(reason_code)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_manual_review(self, review_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM manual_review_queue WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_manual_review_status(self, review_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE manual_review_queue SET status = ?, updated_at = ? WHERE review_id = ?",
                (status, utcnow_str(), review_id),
            )

    def update_manual_review_status_by_page_id(self, page_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE manual_review_queue SET status = ?, updated_at = ? WHERE page_id = ? AND status = 'pending'",
                (status, utcnow_str(), page_id),
            )

    def summary(self) -> dict:
        with self.connect() as conn:
            source_rows = conn.execute(
                """
                SELECT source_type, COUNT(*) AS total
                FROM raw_pages
                GROUP BY source_type
                ORDER BY source_type ASC
                """
            ).fetchall()
            status_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM raw_pages
                GROUP BY status
                ORDER BY status ASC
                """
            ).fetchall()
            manual_reason_rows = conn.execute(
                """
                SELECT reason_code, COUNT(*) AS total
                FROM manual_review_queue
                WHERE status = 'pending'
                GROUP BY reason_code
                ORDER BY total DESC, reason_code ASC
                """
            ).fetchall()
            return {
                "raw_pages": conn.execute("SELECT COUNT(*) FROM raw_pages").fetchone()[0],
                "temp_events": conn.execute("SELECT COUNT(*) FROM temp_events").fetchone()[0],
                "dedupe_checks": conn.execute("SELECT COUNT(*) FROM dedupe_checks").fetchone()[0],
                "validation_checks": conn.execute("SELECT COUNT(*) FROM validation_checks").fetchone()[0],
                "manual_pending": conn.execute(
                    "SELECT COUNT(*) FROM manual_review_queue WHERE status = 'pending'"
                ).fetchone()[0],
                "by_source": {str(row["source_type"]): int(row["total"]) for row in source_rows},
                "by_status": {str(row["status"]): int(row["total"]) for row in status_rows},
                "manual_by_reason_code": {str(row["reason_code"]): int(row["total"]) for row in manual_reason_rows},
            }

    def cleanup_pages(self, page_ids: list[str]) -> dict[str, int]:
        if not page_ids:
            return {
                "raw_pages": 0,
                "temp_events": 0,
                "dedupe_checks": 0,
                "validation_checks": 0,
                "manual_review_queue": 0,
            }
        placeholders = ", ".join("?" for _ in page_ids)
        with self.connect() as conn:
            temp_ids = [
                str(row["temp_id"])
                for row in conn.execute(
                    f"SELECT temp_id FROM temp_events WHERE page_id IN ({placeholders})",
                    page_ids,
                ).fetchall()
            ]
            deleted = {
                "manual_review_queue": conn.execute(
                    f"DELETE FROM manual_review_queue WHERE page_id IN ({placeholders})",
                    page_ids,
                ).rowcount,
                "raw_pages": 0,
                "temp_events": 0,
                "dedupe_checks": 0,
                "validation_checks": 0,
            }
            if temp_ids:
                temp_placeholders = ", ".join("?" for _ in temp_ids)
                deleted["dedupe_checks"] = conn.execute(
                    f"DELETE FROM dedupe_checks WHERE temp_id IN ({temp_placeholders})",
                    temp_ids,
                ).rowcount
                deleted["validation_checks"] = conn.execute(
                    f"DELETE FROM validation_checks WHERE temp_id IN ({temp_placeholders})",
                    temp_ids,
                ).rowcount
            deleted["temp_events"] = conn.execute(
                f"DELETE FROM temp_events WHERE page_id IN ({placeholders})",
                page_ids,
            ).rowcount
            deleted["raw_pages"] = conn.execute(
                f"DELETE FROM raw_pages WHERE page_id IN ({placeholders})",
                page_ids,
            ).rowcount
            return deleted

    def _ensure_manual_review_columns(self, conn: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(manual_review_queue)").fetchall()}
        if "reason_code" not in columns:
            conn.execute(
                "ALTER TABLE manual_review_queue ADD COLUMN reason_code TEXT NOT NULL DEFAULT 'validation_failed'"
            )
        if "reason_detail_json" not in columns:
            conn.execute(
                "ALTER TABLE manual_review_queue ADD COLUMN reason_detail_json TEXT NOT NULL DEFAULT '{}'"
            )


def _page_id_prefix_for_source_type(source_type: str) -> str | None:
    normalized = str(source_type or "").strip()
    if normalized == "wechat_db":
        return "wechat_db_"
    if normalized == "jwc_db":
        return "jwc_db_"
    return None
