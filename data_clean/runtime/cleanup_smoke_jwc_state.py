from __future__ import annotations

import os
import sqlite3
from pathlib import Path

PAGE_ID = "smoke-jwc-html-1"
EXPECTED_TITLE = "关于2026-2027学年暑期学校课程预选及重修（含及格重修）报名的通知"
MAIN_DB = "/root/data_process/data/data_clean/output/seu_campus_assistant.db"
SIDECAR_DB = "/root/data_process/data_clean/runtime/process_state.sqlite3"
RAW_CACHE_ROOT = Path("/root/data_process/data_clean/runtime/raw_cache").resolve()


def cleanup_main_db() -> None:
    with sqlite3.connect(MAIN_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = list(
            conn.execute(
                """
                select id, title
                from school_event_table
                where title = ?
                order by id
                """,
                (EXPECTED_TITLE,),
            )
        )
        for row in rows:
            if row["title"] != EXPECTED_TITLE:
                raise RuntimeError(f"Unexpected row while cleaning smoke records: {dict(row)}")
        conn.execute("delete from school_event_table where title = ?", (EXPECTED_TITLE,))
        conn.commit()


def cleanup_sidecar() -> None:
    with sqlite3.connect(SIDECAR_DB) as conn:
        conn.row_factory = sqlite3.Row
        raw_page = conn.execute(
            "select original_text_path from raw_pages where page_id = ?",
            (PAGE_ID,),
        ).fetchone()

        temp_ids = [
            row["temp_id"]
            for row in conn.execute("select temp_id from temp_events where page_id = ?", (PAGE_ID,))
        ]

        if raw_page and raw_page["original_text_path"]:
            path = Path(raw_page["original_text_path"]).resolve()
            if RAW_CACHE_ROOT in path.parents and path.exists():
                path.unlink()

        if temp_ids:
            placeholders = ",".join(["?"] * len(temp_ids))
            conn.execute(f"delete from validation_checks where temp_id in ({placeholders})", temp_ids)
            conn.execute(f"delete from dedupe_checks where temp_id in ({placeholders})", temp_ids)
            conn.execute(f"delete from manual_review_queue where temp_id in ({placeholders})", temp_ids)
            conn.execute(f"delete from temp_events where temp_id in ({placeholders})", temp_ids)

        conn.execute("delete from manual_review_queue where page_id = ?", (PAGE_ID,))
        conn.execute("delete from raw_pages where page_id = ?", (PAGE_ID,))
        conn.commit()


if __name__ == "__main__":
    cleanup_main_db()
    cleanup_sidecar()
    print("cleanup_done")
