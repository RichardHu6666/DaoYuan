from __future__ import annotations

import sqlite3

from .models import AppPaths, TempEvent, default_app_paths


class DedupeRecallService:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or default_app_paths()
        self.paths.ensure()

    def recall(self, temp_event: TempEvent) -> list[dict]:
        if not temp_event.regis_start_time or not self.paths.main_db_path.exists():
            return []
        conn = sqlite3.connect(self.paths.main_db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, website, title, cleaned_document, summary,
                       regis_start_time, regis_end_time, activity_start_time,
                       campus, target_grade, topics
                FROM school_event_table
                WHERE regis_start_time = ?
                ORDER BY id DESC
                """,
                (temp_event.regis_start_time,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
