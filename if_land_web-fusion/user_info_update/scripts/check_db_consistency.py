from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_DIR / "seu_campus_assistant.db"


def print_section(title: str) -> None:
    print(f"\n## {title}")


def print_rows(
    rows: list[sqlite3.Row],
    empty_text: str,
    *,
    show_rows: bool = False,
    severity: str = "WARN",
) -> int:
    if not rows:
        print(f"[OK] {empty_text}")
        return 0
    print(f"[{severity}] 发现 {len(rows)} 条")
    if show_rows:
        for row in rows[:30]:
            print(dict(row))
        if len(rows) > 30:
            print(f"... 还有 {len(rows) - 30} 条未展示")
    return len(rows)


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        is not None
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Campus Jarvis SQLite UUID 直连一致性检查。默认只报告，不删除数据。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径")
    parser.add_argument("--show-rows", action="store_true", help="展示问题行，最多 30 条")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[FAIL] 数据库不存在：{db_path}")
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    failures = 0
    warnings = 0

    required_tables = [
        "users_table",
        "plan_table",
        "notification_table",
        "context_table",
    ]
    print_section("核心表")
    for table in required_tables:
        exists = table_exists(conn, table)
        print(f"[{'OK' if exists else 'FAIL'}] {table}")
        if not exists:
            failures += 1
    if failures:
        return 1

    print_section("UUID 外键")
    orphan_specs = [
        ("plan_table", "id"),
        ("notification_table", "id"),
        ("context_table", "user_id"),
    ]
    for table, id_col in orphan_specs:
        rows = conn.execute(
            f"""
            SELECT t.{id_col} AS row_id, t.user_id
            FROM {table} AS t
            LEFT JOIN users_table AS u ON u.uuid = t.user_id
            WHERE u.uuid IS NULL
            """
        ).fetchall()
        failures += print_rows(rows, f"{table} 没有孤儿数据", show_rows=args.show_rows, severity="FAIL")

    print_section("用户资料")
    rows = conn.execute(
        """
        SELECT u.uuid, u.nickname, u.school, u.major
        FROM users_table AS u
        LEFT JOIN plan_table AS p ON p.user_id = u.uuid
        LEFT JOIN notification_table AS n ON n.user_id = u.uuid
        LEFT JOIN context_table AS c ON c.user_id = u.uuid
        WHERE COALESCE(NULLIF(TRIM(u.nickname), ''), '') = ''
          AND COALESCE(NULLIF(TRIM(u.school), ''), '') = ''
          AND COALESCE(NULLIF(TRIM(u.major), ''), '') = ''
          AND p.user_id IS NULL
          AND n.user_id IS NULL
          AND c.user_id IS NULL
        GROUP BY u.uuid
        """
    ).fetchall()
    warnings += print_rows(rows, "没有发现明显空用户", show_rows=args.show_rows)

    print_section("历史冗余表")
    if table_exists(conn, "user_account_map"):
        print("[INFO] user_account_map 仍存在，但 UUID 直连网页不再读取或写入它。")
    else:
        print("[OK] 没有 user_account_map 历史表。")

    print_section("结论")
    if failures:
        print(f"[FAIL] 共发现 {failures} 个硬错误、{warnings} 个提醒项。脚本没有删除任何数据。")
        return 1
    if warnings:
        print(f"[WARN] UUID 外键满足要求，但有 {warnings} 个提醒项需要人工确认。脚本没有删除任何数据。")
        return 0
    print("[OK] UUID 直连数据关系满足要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
