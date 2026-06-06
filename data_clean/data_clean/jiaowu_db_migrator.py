from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from .models import AppPaths, default_app_paths
from .sql_sink import SqlSink


TARGET_COLUMNS = (
    "website",
    "title",
    "cleaned_document",
    "summary",
    "embedded_summary",
    "regis_start_time",
    "regis_end_time",
    "activity_start_time",
    "campus",
    "target_grade",
    "topics",
)

DEFAULT_SOURCE_DB = Path("/root/rivermind-data/database/jiaowu.db")


class JiaowuDbMigrator:
    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        sql_sink: SqlSink | None = None,
        helper_path: str | Path | None = None,
    ):
        self.paths = paths or default_app_paths()
        self.paths.ensure()
        self.sql_sink = sql_sink or SqlSink(self.paths, helper_path=helper_path)

    def migrate(
        self,
        *,
        source_db: str | Path | None = None,
        limit: int | None = None,
        offset: int = 0,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        source_path = Path(source_db) if source_db else DEFAULT_SOURCE_DB
        source_path = source_path.expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"Source DB not found: {source_path}")

        try:
            if source_path.resolve() == self.paths.main_db_path.resolve():
                raise ValueError("Source DB and main DB must be different files.")
        except OSError:
            pass

        rows = self._load_rows(source_db=source_path, limit=limit, offset=offset)
        counts = {
            "stored": 0,
            "updated_or_upserted": 0,
            "failed": 0,
        }
        failures: list[dict] = []

        if progress_callback is not None:
            progress_callback(
                {
                    "event": "start",
                    "total": len(rows),
                    "skipped": 0,
                    "concurrency": 1,
                }
            )

        with self.sql_sink as sink:
            completed = 0
            for item in rows:
                source_record_id = int(item.pop("_source_record_id"))
                try:
                    record_id, status = sink.upsert_event_row_with_status(item)
                    counts[status] += 1
                    event = {
                        "event": "progress",
                        "completed": completed + 1,
                        "total": len(rows),
                        "status": status,
                        "page_id": "",
                        "record_id": record_id,
                        "source_record_id": source_record_id,
                        "counts": dict(counts),
                    }
                except Exception as exc:
                    counts["failed"] += 1
                    failures.append(
                        {
                            "source_record_id": source_record_id,
                            "website": item.get("website"),
                            "title": item.get("title"),
                            "error": str(exc),
                        }
                    )
                    event = {
                        "event": "progress",
                        "completed": completed + 1,
                        "total": len(rows),
                        "status": "failed",
                        "page_id": "",
                        "record_id": source_record_id,
                        "source_record_id": source_record_id,
                        "error": str(exc),
                        "counts": dict(counts),
                    }
                completed += 1
                if progress_callback is not None:
                    progress_callback(event)

        if progress_callback is not None:
            progress_callback(
                {
                    "event": "end",
                    "processed": len(rows),
                    "total": len(rows),
                    "skipped": 0,
                    "concurrency": 1,
                    "counts": dict(counts),
                }
            )

        return {
            "processed": len(rows),
            "counts": counts,
            "source_db": str(source_path),
            "main_db": str(self.paths.main_db_path),
            "failures": failures,
        }

    def _load_rows(self, *, source_db: Path, limit: int | None, offset: int) -> list[dict[str, object]]:
        conn = sqlite3.connect(str(source_db))
        conn.row_factory = sqlite3.Row
        try:
            columns = self._list_columns(conn)
            order_column = "id" if "id" in columns else "rowid"
            select_columns = [f"{order_column} AS _source_record_id"]
            select_columns.extend(column for column in TARGET_COLUMNS if column in columns)

            query = (
                f"SELECT {', '.join(select_columns)} "
                "FROM school_event_table "
                f"ORDER BY {order_column} ASC"
            )
            params: list[int] = []
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params.extend([int(limit), int(offset)])
            elif offset:
                query += " LIMIT -1 OFFSET ?"
                params.append(int(offset))

            fetched = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        rows: list[dict[str, object]] = []
        for row in fetched:
            payload: dict[str, object] = {"_source_record_id": row["_source_record_id"]}
            for column in TARGET_COLUMNS:
                payload[column] = row[column] if column in row.keys() else None
            rows.append(payload)
        return rows

    def _list_columns(self, conn: sqlite3.Connection) -> set[str]:
        tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if "school_event_table" not in tables:
            raise RuntimeError("Source DB does not contain `school_event_table`.")

        rows = conn.execute("PRAGMA table_info(school_event_table)").fetchall()
        return {str(row["name"]) for row in rows}
