from __future__ import annotations

import sqlite3
from typing import Iterable

from .models import AppPaths, JwcDbRecord, default_app_paths


class JwcDbLoader:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or default_app_paths()
        self.paths.ensure()

    def iter_records(self, *, limit: int | None = None, offset: int = 0) -> Iterable[JwcDbRecord]:
        query = (
            "SELECT id, website, title, cleaned_document "
            "FROM school_event_table "
            "ORDER BY id ASC"
        )
        params: list[int] = []
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        elif offset:
            query += " LIMIT -1 OFFSET ?"
            params.append(int(offset))

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        for row in rows:
            yield self._row_to_record(row)

    def load_by_record_id(self, record_id: int) -> JwcDbRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, website, title, cleaned_document
                FROM school_event_table
                WHERE id = ?
                """,
                (int(record_id),),
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else self._row_to_record(row)

    def load_by_page_id(self, page_id: str) -> JwcDbRecord | None:
        prefix = "jwc_db_"
        if not page_id.startswith(prefix):
            return None
        try:
            record_id = int(page_id[len(prefix) :])
        except ValueError:
            return None
        return self.load_by_record_id(record_id)

    def count_records(self) -> int:
        conn = self._connect()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM school_event_table").fetchone()[0])
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.paths.jwc_source_db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _row_to_record(self, row: sqlite3.Row) -> JwcDbRecord:
        return JwcDbRecord(
            record_id=int(row["id"]),
            website=str(row["website"] or "").strip(),
            title=str(row["title"] or "").strip(),
            cleaned_document=str(row["cleaned_document"] or "").strip(),
        )
