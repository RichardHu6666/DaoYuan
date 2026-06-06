from __future__ import annotations

import json
import sqlite3

db_path = "/root/data_process/data_clean/runtime/process_state.sqlite3"

with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    temp_rows = [
        dict(row)
        for row in conn.execute(
            """
            select temp_id, page_id, attempt, temp_json, need_retry, retry_reason, created_at
            from temp_events
            where page_id = ?
            order by created_at desc, attempt desc
            limit 4
            """,
            ("smoke-jwc-html-1",),
        )
    ]
    validation_rows = [
        dict(row)
        for row in conn.execute(
            """
            select vc.validation_id, vc.temp_id, vc.rule_result_json, vc.semantic_result_json, vc.final_passed, vc.created_at
            from validation_checks vc
            join temp_events te on te.temp_id = vc.temp_id
            where te.page_id = ?
            order by vc.created_at desc
            limit 4
            """,
            ("smoke-jwc-html-1",),
        )
    ]

print(
    json.dumps(
        {
            "temp_events": temp_rows,
            "validation_checks": validation_rows,
        },
        ensure_ascii=False,
        indent=2,
    )
)
