"""
seu_campus_db.py

SQLite 封装类：根据《SQL 数据库结构设计-敲定版v1.md》实现。

功能：
1. 创建 / 删除 / 重置表格
2. 通用 insert / upsert / update / delete / fetch / count
3. 自动处理 JSON 字段：传入 list/dict 会自动 json.dumps；读取时可自动 json.loads
4. 自动维护 created_at / updated_at
5. 开启 SQLite 外键约束
6. 提供 numpy 向量与 BLOB 的辅助转换函数

使用：
    from seu_campus_db import SEUCampusDB

    with SEUCampusDB("seu_campus_assistant.db") as db:
        db.insert("users_table", {"uuid": "user_001", "nickname": "小明"})
        user = db.fetch_by_pk("users_table", "user_001")
        print(user)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence


class SEUCampusDB:
    """Campus Jarvis / SEU Campus Assistant SQLite 数据库管理类。"""

    # ============================================================
    # 表结构元信息
    # ============================================================

    TABLE_COLUMNS: dict[str, set[str]] = {
        "school_event_table": {
            "id",
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
            "created_at",
            "updated_at",
        },
        "tools_table": {
            "name",
            "website",
            "description",
        },
        "users_table": {
            "uuid",
            "nickname",
            "gender",
            "birthday",
            "school",
            "major",
            "enrollment_year",
            "student_level",
            "interest",
            "profile",
            "schedule",
        },
        "user_account_map": {
            "account",
            "user_id",
            "created_at",
            "updated_at",
        },
        "notification_table": {
            "id",
            "user_id",
            "type",
            "title",
            "content",
            "frequency",
            "weekday",
            "notify_date",
            "notify_times",
            "enabled",
            "created_at",
            "updated_at",
        },
        "plan_table": {
            "id",
            "user_id",
            "name",
            "type",
            "start_time",
            "end_time",
            "reminder_time",
            "status",
            "importance",
            "description",
            "created_at",
            "updated_at",
        },
        "context_table": {
            "user_id",
            "context",
        },
    }

    PRIMARY_KEYS: dict[str, str] = {
        "school_event_table": "id",
        "tools_table": "name",
        "users_table": "uuid",
        "user_account_map": "account",
        "notification_table": "id",
        "plan_table": "id",
        "context_table": "user_id",
    }

    JSON_FIELDS: dict[str, set[str]] = {
        "school_event_table": {"campus", "target_grade", "topics"},
        "users_table": {"interest", "schedule"},
        "notification_table": {"notify_times"},
        "context_table": {"context"},
    }

    DATETIME_FIELDS: set[str] = {
        "regis_start_time",
        "regis_end_time",
        "activity_start_time",
        "start_time",
        "end_time",
        "reminder_time",
        "created_at",
        "updated_at",
    }

    DATE_FIELDS: set[str] = {
        "birthday",
        "notify_date",
    }

    TIME_LIST_FIELDS: set[str] = {
        "notify_times",
    }

    AUTO_TIME_TABLES: set[str] = {
        "school_event_table",
        "user_account_map",
        "notification_table",
        "plan_table",
    }

    ENUM_FIELDS: dict[tuple[str, str], set[Any]] = {
        ("users_table", "student_level"): {"本", "硕", "博"},
        ("notification_table", "type"): {"news", "fixed"},
        ("notification_table", "frequency"): {"daily", "weekly", "once"},
        ("plan_table", "status"): {"todo", "doing", "done", "cancelled"},
    }

    def __init__(
        self,
        db_path: str = "seu_campus_assistant.db",
        *,
        auto_create: bool = True,
        timeout: float = 10.0,
    ):
        self.db_path = db_path
        self.timeout = timeout
        self.conn: Optional[sqlite3.Connection] = None

        self.connect()
        if auto_create:
            self.create_tables()
            self.create_indexes()

    # ============================================================
    # 连接管理
    # ============================================================

    def connect(self) -> None:
        """连接数据库，并开启外键。"""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path, timeout=self.timeout)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")

    def close(self) -> None:
        """关闭数据库连接。"""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "SEUCampusDB":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _require_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("数据库连接已经关闭")
        return self.conn

    # ============================================================
    # 建表 / 删表 / 重置
    # ============================================================

    def create_tables(self) -> None:
        """按照 md 文件中的设计创建全部表格。"""
        conn = self._require_conn()

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS school_event_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website TEXT,
                title TEXT,
                cleaned_document TEXT,
                summary TEXT,
                embedded_summary BLOB,
                regis_start_time TEXT,
                regis_end_time TEXT,
                activity_start_time TEXT,
                campus TEXT,
                target_grade TEXT,
                topics TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tools_table (
                name TEXT PRIMARY KEY UNIQUE,
                website TEXT,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS users_table (
                uuid TEXT PRIMARY KEY,
                nickname TEXT,
                gender TEXT,
                birthday TEXT,
                school TEXT,
                major TEXT,
                enrollment_year INTEGER,
                student_level TEXT CHECK(student_level IS NULL OR student_level IN ('本', '硕', '博')),
                interest TEXT,
                profile TEXT,
                schedule TEXT
            );

            CREATE TABLE IF NOT EXISTS user_account_map (
                account TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users_table(uuid) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notification_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                type TEXT CHECK(type IS NULL OR type IN ('news', 'fixed')),
                title TEXT,
                content TEXT,
                frequency TEXT CHECK(frequency IS NULL OR frequency IN ('daily', 'weekly', 'once')),
                weekday INTEGER CHECK(weekday IS NULL OR weekday BETWEEN 1 AND 7),
                notify_date TEXT,
                notify_times TEXT,
                enabled INTEGER DEFAULT 1 CHECK(enabled IN (0, 1)),
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users_table(uuid) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS plan_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                name TEXT,
                type TEXT,
                start_time TEXT,
                end_time TEXT,
                reminder_time TEXT,
                status TEXT CHECK(status IS NULL OR status IN ('todo', 'doing', 'done', 'cancelled')),
                importance INTEGER CHECK(importance IS NULL OR importance BETWEEN 1 AND 5),
                description TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users_table(uuid) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS context_table (
                user_id TEXT PRIMARY KEY,
                context TEXT,
                FOREIGN KEY(user_id) REFERENCES users_table(uuid) ON DELETE CASCADE
            );
            """
        )
        conn.commit()

    def create_indexes(self) -> None:
        """创建常用索引。"""
        conn = self._require_conn()
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_school_event_regis_end_time
                ON school_event_table(regis_end_time);

            CREATE INDEX IF NOT EXISTS idx_school_event_activity_start_time
                ON school_event_table(activity_start_time);

            CREATE INDEX IF NOT EXISTS idx_school_event_website
                ON school_event_table(website);

            CREATE INDEX IF NOT EXISTS idx_school_event_created_at
                ON school_event_table(created_at);

            CREATE INDEX IF NOT EXISTS idx_user_account_map_user_id
                ON user_account_map(user_id);

            CREATE INDEX IF NOT EXISTS idx_notification_user_id
                ON notification_table(user_id);

            CREATE INDEX IF NOT EXISTS idx_notification_frequency
                ON notification_table(frequency);

            CREATE INDEX IF NOT EXISTS idx_notification_enabled
                ON notification_table(enabled);

            CREATE INDEX IF NOT EXISTS idx_plan_user_id
                ON plan_table(user_id);

            CREATE INDEX IF NOT EXISTS idx_plan_user_status
                ON plan_table(user_id, status);

            CREATE INDEX IF NOT EXISTS idx_plan_end_time
                ON plan_table(end_time);
            """
        )
        conn.commit()

    def drop_tables(self) -> None:
        """删除全部表。注意：会清空数据。"""
        conn = self._require_conn()
        conn.executescript(
            """
            DROP TABLE IF EXISTS user_account_map;
            DROP TABLE IF EXISTS context_table;
            DROP TABLE IF EXISTS plan_table;
            DROP TABLE IF EXISTS notification_table;
            DROP TABLE IF EXISTS users_table;
            DROP TABLE IF EXISTS tools_table;
            DROP TABLE IF EXISTS school_event_table;
            """
        )
        conn.commit()

    def reset_database(self) -> None:
        """重置数据库：删表后重新建表。"""
        self.drop_tables()
        self.create_tables()
        self.create_indexes()

    # ============================================================
    # 通用执行接口
    # ============================================================

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
        *,
        commit: bool = True,
    ) -> sqlite3.Cursor:
        """执行单条 SQL。"""
        conn = self._require_conn()
        cur = conn.execute(sql, params or [])
        if commit:
            conn.commit()
        return cur

    def executemany(
        self,
        sql: str,
        seq_of_params: Iterable[Sequence[Any]],
        *,
        commit: bool = True,
    ) -> sqlite3.Cursor:
        """批量执行 SQL。"""
        conn = self._require_conn()
        cur = conn.executemany(sql, seq_of_params)
        if commit:
            conn.commit()
        return cur

    # ============================================================
    # 增 / 改 / 删 / 查
    # ============================================================

    def insert(
        self,
        table: str,
        data: dict[str, Any],
        *,
        ignore: bool = False,
    ) -> int:
        """
        插入一行数据。

        参数：
            table: 表名
            data: 字段字典
            ignore: 如果为 True，则使用 INSERT OR IGNORE

        返回：
            lastrowid。对于自增 id 表，通常就是新插入记录的 id。
        """
        self._validate_table(table)
        data = self._prepare_data(table, data, for_insert=True)

        if not data:
            raise ValueError("insert 的 data 不能为空")

        columns = list(data.keys())
        self._validate_columns(table, columns)

        placeholders = ", ".join(["?"] * len(columns))
        col_sql = ", ".join(columns)
        values = [data[col] for col in columns]

        insert_prefix = "INSERT OR IGNORE" if ignore else "INSERT"
        sql = f"{insert_prefix} INTO {table} ({col_sql}) VALUES ({placeholders})"

        cur = self.execute(sql, values)
        return int(cur.lastrowid)

    def upsert(
        self,
        table: str,
        data: dict[str, Any],
        *,
        conflict_columns: Sequence[str] | None = None,
    ) -> int:
        """
        插入或覆盖更新一行数据。

        说明：
        - 不使用 INSERT OR REPLACE，因为 OR REPLACE 会先删除旧行，可能触发外键级联。
        - 使用 SQLite 的 ON CONFLICT DO UPDATE。
        - school_event_table 的 website 可重复；没有 id 时请显式传入可用的 conflict_columns，或使用 insert 新增。
        """
        self._validate_table(table)
        data = self._prepare_data(table, data, for_insert=True)

        if not data:
            raise ValueError("upsert 的 data 不能为空")

        columns = list(data.keys())
        self._validate_columns(table, columns)

        if conflict_columns is None:
            conflict_columns = self._infer_conflict_columns(table, data)

        if not conflict_columns:
            raise ValueError("无法推断 conflict_columns，请显式传入")

        self._validate_columns(table, conflict_columns)

        placeholders = ", ".join(["?"] * len(columns))
        col_sql = ", ".join(columns)
        values = [data[col] for col in columns]
        conflict_sql = ", ".join(conflict_columns)

        update_cols = [col for col in columns if col not in conflict_columns]
        if not update_cols:
            # 没有可更新字段时，冲突则什么都不做
            sql = (
                f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
                f"ON CONFLICT({conflict_sql}) DO NOTHING"
            )
        else:
            update_sql = ", ".join([f"{col}=excluded.{col}" for col in update_cols])
            sql = (
                f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
                f"ON CONFLICT({conflict_sql}) DO UPDATE SET {update_sql}"
            )

        cur = self.execute(sql, values)
        return int(cur.lastrowid)

    def update(
        self,
        table: str,
        data: dict[str, Any],
        where: dict[str, Any] | str,
        params: Sequence[Any] | None = None,
    ) -> int:
        """
        更新数据。

        where 支持两种写法：
        1. dict 写法：
            db.update("plan_table", {"status": "done"}, {"id": 1})
            db.update("plan_table", {"status": "todo"}, {"end_time": (">", "2026-06-01 00:00:00")})

        2. 原生 SQL 条件写法：
            db.update("plan_table", {"status": "done"}, "id = ?", [1])
        """
        self._validate_table(table)
        data = self._prepare_data(table, data, for_insert=False)

        if not data:
            raise ValueError("update 的 data 不能为空")

        columns = list(data.keys())
        self._validate_columns(table, columns)

        # 自动维护 updated_at
        if table in self.AUTO_TIME_TABLES and "updated_at" in self.TABLE_COLUMNS[table] and "updated_at" not in data:
            data["updated_at"] = self.now_str()
            columns = list(data.keys())

        set_sql = ", ".join([f"{col} = ?" for col in columns])
        set_values = [data[col] for col in columns]

        where_sql, where_values = self._build_where(table, where, params)
        sql = f"UPDATE {table} SET {set_sql} {where_sql}"

        cur = self.execute(sql, set_values + where_values)
        return int(cur.rowcount)

    def delete(
        self,
        table: str,
        where: dict[str, Any] | str,
        params: Sequence[Any] | None = None,
    ) -> int:
        """
        删除数据。

        为了防止误删，where 不允许为空。
        """
        self._validate_table(table)
        where_sql, where_values = self._build_where(table, where, params)
        if not where_sql.strip():
            raise ValueError("delete 必须提供 where 条件，防止误删全表")

        sql = f"DELETE FROM {table} {where_sql}"
        cur = self.execute(sql, where_values)
        return int(cur.rowcount)

    def fetch_all(
        self,
        table: str,
        where: dict[str, Any] | str | None = None,
        params: Sequence[Any] | None = None,
        *,
        columns: Sequence[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        deserialize_json: bool = True,
    ) -> list[dict[str, Any]]:
        """查询多行数据，返回 list[dict]。"""
        self._validate_table(table)

        if columns is None:
            col_sql = "*"
        else:
            self._validate_columns(table, columns)
            col_sql = ", ".join(columns)

        where_sql, where_values = self._build_where(table, where, params)
        sql = f"SELECT {col_sql} FROM {table} {where_sql}"

        if order_by:
            sql += " " + self._build_order_by(table, order_by)

        if limit is not None:
            sql += " LIMIT ?"
            where_values.append(int(limit))

        if offset is not None:
            sql += " OFFSET ?"
            where_values.append(int(offset))

        cur = self.execute(sql, where_values, commit=False)
        rows = [dict(row) for row in cur.fetchall()]

        if deserialize_json:
            rows = [self._deserialize_json_fields(table, row) for row in rows]

        return rows

    def fetch_one(
        self,
        table: str,
        where: dict[str, Any] | str | None = None,
        params: Sequence[Any] | None = None,
        *,
        columns: Sequence[str] | None = None,
        order_by: str | None = None,
        deserialize_json: bool = True,
    ) -> Optional[dict[str, Any]]:
        """查询一行数据，查不到则返回 None。"""
        rows = self.fetch_all(
            table,
            where,
            params,
            columns=columns,
            order_by=order_by,
            limit=1,
            deserialize_json=deserialize_json,
        )
        return rows[0] if rows else None

    def count(
        self,
        table: str,
        where: dict[str, Any] | str | None = None,
        params: Sequence[Any] | None = None,
    ) -> int:
        """统计行数。"""
        self._validate_table(table)
        where_sql, where_values = self._build_where(table, where, params)
        cur = self.execute(f"SELECT COUNT(*) AS n FROM {table} {where_sql}", where_values, commit=False)
        row = cur.fetchone()
        return int(row["n"])

    # ============================================================
    # 主键快捷接口
    # ============================================================

    def fetch_by_pk(
        self,
        table: str,
        pk_value: Any,
        *,
        deserialize_json: bool = True,
    ) -> Optional[dict[str, Any]]:
        """按主键查询一行。"""
        pk = self.PRIMARY_KEYS[table]
        return self.fetch_one(table, {pk: pk_value}, deserialize_json=deserialize_json)

    def update_by_pk(self, table: str, pk_value: Any, data: dict[str, Any]) -> int:
        """按主键更新。"""
        pk = self.PRIMARY_KEYS[table]
        return self.update(table, data, {pk: pk_value})

    def delete_by_pk(self, table: str, pk_value: Any) -> int:
        """按主键删除。"""
        pk = self.PRIMARY_KEYS[table]
        return self.delete(table, {pk: pk_value})

    # ============================================================
    # 常用业务快捷接口
    # ============================================================

    def get_user(self, uuid: str) -> Optional[dict[str, Any]]:
        return self.fetch_by_pk("users_table", uuid)

    def list_user_plans(
        self,
        user_id: str,
        *,
        status: str | None = None,
        order_by: str = "end_time ASC",
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"user_id": user_id}
        if status is not None:
            where["status"] = status
        return self.fetch_all("plan_table", where, order_by=order_by)

    def list_user_notifications(
        self,
        user_id: str,
        *,
        enabled: bool | None = None,
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"user_id": user_id}
        if enabled is not None:
            where["enabled"] = int(bool(enabled))
        return self.fetch_all("notification_table", where, order_by="created_at DESC")

    def upsert_user_context(self, user_id: str, context: list[dict[str, str]] | dict[str, Any] | str) -> int:
        """插入或更新用户上下文。"""
        return self.upsert(
            "context_table",
            {"user_id": user_id, "context": context},
            conflict_columns=["user_id"],
        )

    def get_user_context(self, user_id: str) -> Any:
        row = self.fetch_by_pk("context_table", user_id)
        return None if row is None else row.get("context")

    # ============================================================
    # DataFrame 辅助接口
    # ============================================================

    def fetch_df(
        self,
        table: str,
        where: dict[str, Any] | str | None = None,
        params: Sequence[Any] | None = None,
        *,
        columns: Sequence[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        deserialize_json: bool = True,
    ):
        """
        查询并返回 pandas.DataFrame。

        需要提前安装 pandas：
            pip install pandas
        """
        import pandas as pd

        rows = self.fetch_all(
            table,
            where,
            params,
            columns=columns,
            order_by=order_by,
            limit=limit,
            offset=offset,
            deserialize_json=deserialize_json,
        )
        return pd.DataFrame(rows)

    # ============================================================
    # numpy 向量 BLOB 辅助接口
    # ============================================================

    @staticmethod
    def numpy_to_blob(arr: Any) -> bytes:
        """
        numpy array -> BLOB。

        示例：
            embedded_summary = SEUCampusDB.numpy_to_blob(np.array([...], dtype=np.float32))
        """
        return arr.tobytes()

    @staticmethod
    def blob_to_numpy(blob: bytes, *, dtype: str = "float32") -> Any:
        """
        BLOB -> numpy array。

        示例：
            vec = SEUCampusDB.blob_to_numpy(row["embedded_summary"])
        """
        import numpy as np

        return np.frombuffer(blob, dtype=dtype)

    # ============================================================
    # 内部工具函数
    # ============================================================

    @staticmethod
    def now_str() -> str:
        """当前时间字符串：YYYY-MM-DD HH:MM:SS。"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _validate_table(self, table: str) -> None:
        if table not in self.TABLE_COLUMNS:
            raise ValueError(f"未知表名：{table}")

    def _validate_columns(self, table: str, columns: Iterable[str]) -> None:
        allowed = self.TABLE_COLUMNS[table]
        for col in columns:
            if col not in allowed:
                raise ValueError(f"表 {table} 中不存在字段：{col}")

    def _prepare_data(self, table: str, data: dict[str, Any], *, for_insert: bool) -> dict[str, Any]:
        """写入前处理：校验字段、JSON 序列化、bool 转 int、自动时间。"""
        self._validate_table(table)
        data = dict(data)
        self._validate_columns(table, data.keys())

        # 自动 created_at / updated_at
        if for_insert and table in self.AUTO_TIME_TABLES:
            now = self.now_str()
            if "created_at" in self.TABLE_COLUMNS[table] and not data.get("created_at"):
                data["created_at"] = now
            if "updated_at" in self.TABLE_COLUMNS[table] and not data.get("updated_at"):
                data["updated_at"] = now

        # bool 转 SQLite INTEGER
        if table == "notification_table" and "enabled" in data and data["enabled"] is not None:
            data["enabled"] = int(bool(data["enabled"]))

        # JSON 字段：允许直接传 list/dict，自动 dumps
        json_fields = self.JSON_FIELDS.get(table, set())
        for field in json_fields:
            if field in data and data[field] is not None and not isinstance(data[field], (str, bytes)):
                data[field] = json.dumps(data[field], ensure_ascii=False)

        # 枚举校验
        for (t, field), allowed_values in self.ENUM_FIELDS.items():
            if t == table and field in data and data[field] is not None:
                if data[field] not in allowed_values:
                    raise ValueError(f"{table}.{field} 的值必须是 {sorted(allowed_values)}，当前为：{data[field]!r}")

        # importance 范围校验
        if table == "plan_table" and "importance" in data and data["importance"] is not None:
            value = int(data["importance"])
            if not (1 <= value <= 5):
                raise ValueError("plan_table.importance 必须在 1-5 之间")
            data["importance"] = value

        # weekday 范围校验
        if table == "notification_table" and "weekday" in data and data["weekday"] is not None:
            value = int(data["weekday"])
            if not (1 <= value <= 7):
                raise ValueError("notification_table.weekday 必须在 1-7 之间")
            data["weekday"] = value

        return data

    def _deserialize_json_fields(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        """读取后自动 json.loads。解析失败则保留原字符串。"""
        row = dict(row)
        json_fields = self.JSON_FIELDS.get(table, set())
        for field in json_fields:
            if field in row and isinstance(row[field], str):
                text = row[field].strip()
                if not text:
                    continue
                try:
                    row[field] = json.loads(text)
                except json.JSONDecodeError:
                    pass
        return row

    def _infer_conflict_columns(self, table: str, data: dict[str, Any]) -> list[str]:
        """根据表和数据推断 upsert 的冲突字段。"""
        if table == "school_event_table":
            if data.get("id") is not None:
                return ["id"]
            return []

        pk = self.PRIMARY_KEYS[table]
        if pk in data:
            return [pk]

        return []

    def _build_where(
        self,
        table: str,
        where: dict[str, Any] | str | None,
        params: Sequence[Any] | None = None,
    ) -> tuple[str, list[Any]]:
        """
        构造 WHERE 语句。

        dict 写法支持：
            {"id": 1}                         -> id = ?
            {"status": ["todo", "doing"]}   -> status IN (?, ?)
            {"end_time": (">=", "2026...")} -> end_time >= ?
            {"field": None}                   -> field IS NULL
        """
        if where is None:
            return "", []

        if isinstance(where, str):
            if where.strip():
                return "WHERE " + where.strip(), list(params or [])
            return "", []

        if not isinstance(where, dict):
            raise TypeError("where 只能是 dict、str 或 None")

        if not where:
            return "", []

        self._validate_columns(table, where.keys())

        clauses: list[str] = []
        values: list[Any] = []

        for col, value in where.items():
            if value is None:
                clauses.append(f"{col} IS NULL")
                continue

            # 操作符写法：{"end_time": (">=", "2026-06-01 00:00:00")}
            if (
                isinstance(value, tuple)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0].upper() in {"=", "!=", "<>", ">", ">=", "<", "<=", "LIKE"}
            ):
                op, val = value
                clauses.append(f"{col} {op} ?")
                values.append(val)
                continue

            # IN 写法：{"status": ["todo", "doing"]}
            if isinstance(value, (list, tuple, set)):
                items = list(value)
                if not items:
                    clauses.append("1 = 0")
                else:
                    placeholders = ", ".join(["?"] * len(items))
                    clauses.append(f"{col} IN ({placeholders})")
                    values.extend(items)
                continue

            clauses.append(f"{col} = ?")
            values.append(value)

        return "WHERE " + " AND ".join(clauses), values

    def _build_order_by(self, table: str, order_by: str) -> str:
        """
        简单校验 ORDER BY，防止明显的拼接风险。

        支持：
            "end_time ASC"
            "created_at DESC"
            "end_time ASC, importance DESC"
        """
        parts = [part.strip() for part in order_by.split(",")]
        clauses: list[str] = []

        for part in parts:
            tokens = part.split()
            if len(tokens) == 1:
                col = tokens[0]
                direction = ""
            elif len(tokens) == 2:
                col, direction = tokens
                direction = direction.upper()
                if direction not in {"ASC", "DESC"}:
                    raise ValueError(f"非法排序方向：{direction}")
            else:
                raise ValueError(f"非法 order_by：{order_by}")

            self._validate_columns(table, [col])
            clauses.append(f"{col} {direction}".strip())

        return "ORDER BY " + ", ".join(clauses)

    # ============================================================
    # 调试 / 元信息
    # ============================================================

    def list_tables(self) -> list[str]:
        """返回当前数据库中的表名。"""
        cur = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
            commit=False,
        )
        return [row["name"] for row in cur.fetchall()]

    def table_info(self, table: str) -> list[dict[str, Any]]:
        """返回表字段信息。"""
        self._validate_table(table)
        cur = self.execute(f"PRAGMA table_info({table})", commit=False)
        return [dict(row) for row in cur.fetchall()]


if __name__ == "__main__":
    # 一个最小自测示例
    with SEUCampusDB("seu_campus_assistant.db") as db:
        db.create_tables()

        db.upsert(
            "users_table",
            {
                "uuid": "user_001",
                "nickname": "小明",
                "student_level": "本",
                "enrollment_year": 2022,
                "interest": ["AI", "机器人", "数学建模"],
            },
            conflict_columns=["uuid"],
        )

        db.insert(
            "plan_table",
            {
                "user_id": "user_001",
                "name": "报名数学建模竞赛",
                "type": "competition",
                "start_time": "2026-06-01 00:00:00",
                "end_time": "2026-06-10 23:59:59",
                "reminder_time": "2026-06-09 20:00:00",
                "status": "todo",
                "importance": 5,
                "description": "完成队伍报名、材料提交和指导老师确认。",
            },
        )

        print(db.get_user("user_001"))
        print(db.list_user_plans("user_001"))
