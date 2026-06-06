from __future__ import annotations

import json
import sqlite3

db_path = "/root/data_process/data/data_clean/output/seu_campus_assistant.db"
query = """
select id, title, regis_start_time, regis_end_time, activity_start_time
from school_event_table
order by id
"""

with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    rows = [dict(row) for row in conn.execute(query)]

print(json.dumps(rows, ensure_ascii=False, indent=2))
