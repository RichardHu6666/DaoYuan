from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import queue
import re
import sqlite3
import sys
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path(
    os.environ.get(
        "CAMPUS_JARVIS_DB",
        "/root/rivermind-data/database/seu_campus_assistant.db",
    )
)
BOT_SERVICE_ROOT = Path(os.environ.get("CAMPUS_JARVIS_BOT_ROOT", "/root/nonebot2-v3"))

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from seu_campus_db_v3 import SEUCampusDB  # noqa: E402
from decision_bridge import decision_bridge  # noqa: E402


_BOT_SERVICES = None
_BOT_BRIDGE_ERROR = ""
MCP_SESSIONS: dict[str, queue.Queue[str]] = {}
DEFAULT_MCP_USER_ID = os.environ.get(
    "CAMPUS_JARVIS_DEFAULT_USER_ID",
    "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001",
)
RIZON_CUSTOM_AGENT_AK = os.environ.get("RIZON_CUSTOM_AGENT_AK", "campus-jarvis-demo-ak")
TOOLS_FIXTURE = (
    ("教务系统", "https://jw.seu.edu.cn", "成绩、选课、考试安排等官方入口"),
    ("图书馆", "https://lib.seu.edu.cn", "图书馆检索、借阅与馆藏查询入口"),
    ("校历", "https://jwc.seu.edu.cn", "校历与学期安排官方入口"),
)


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with SEUCampusDB(str(DB_PATH)):
        pass
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_account_map (
                account TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY(user_id) REFERENCES users_table(uuid) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_user_account_map_user_id
                ON user_account_map(user_id);

            CREATE TABLE IF NOT EXISTS web_context_table (
                user_id TEXT PRIMARY KEY,
                context TEXT,
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY(user_id) REFERENCES users_table(uuid) ON DELETE CASCADE
            );
            """
        )
        conn.commit()


def init_tools_fixture() -> None:
    with get_connection() as conn:
        for name, website, description in TOOLS_FIXTURE:
            conn.execute(
                """
                INSERT INTO tools_table (name, website, description)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    website = excluded.website,
                    description = excluded.description
                """,
                (name, website, description),
            )
        conn.commit()


def now_sql() -> str:
    return "datetime('now','localtime')"


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def is_time_sensitive_local_query(message: str) -> bool:
    text = message.strip().lower()
    today_words = ("\u4eca\u5929", "\u4eca\u65e5", "today")
    deadline_words = ("ddl", "deadline", "\u5f85\u529e", "\u622a\u6b62", "\u8ba1\u5212")
    schedule_words = ("\u8bfe\u8868", "\u8bfe\u7a0b", "\u4e0a\u8bfe", "schedule")
    if has_any(text, ("ddl", "deadline")):
        return True
    return has_any(text, today_words) and (has_any(text, deadline_words) or has_any(text, schedule_words))


def deadline_query_scope(message: str) -> str:
    text = message.strip().lower()
    if has_any(text, ("\u4eca\u5929", "\u4eca\u65e5", "today")):
        return "today"
    if has_any(text, ("\u8fd9\u5468", "\u672c\u5468", "\u8fd9\u4e2a\u661f\u671f", "\u672c\u661f\u671f", "this week")):
        return "week"
    return "upcoming"


def is_identity_query(message: str) -> bool:
    text = message.strip().lower()
    return has_any(
        text,
        (
            "\u6211\u662f\u8c01",
            "\u6211\u7684\u4fe1\u606f",
            "\u4e2a\u4eba\u4fe1\u606f",
            "\u6211\u7684\u8d26\u53f7",
            "\u6211\u662f\u54ea\u4e2a\u7528\u6237",
            "who am i",
            "profile",
        ),
    )


def extract_custom_agent_text(payload: dict, query_params: dict[str, list[str]] | None = None) -> str | None:
    query_params = query_params or {}
    for key in ("query", "q", "message", "text", "input", "prompt", "content"):
        value = (query_params.get(key) or [None])[0]
        text = clean_text(value)
        if text:
            return text
    for key in ("query", "q", "message", "text", "input", "prompt", "content"):
        text = clean_text(payload.get(key))
        if text:
            return text
    messages = payload.get("messages") or payload.get("conversation") or []
    if isinstance(messages, list):
        for item in reversed(messages):
            if not isinstance(item, dict):
                continue
            content = item.get("content") or item.get("text") or item.get("message")
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        parts.append(str(part.get("text") or part.get("content") or ""))
                    else:
                        parts.append(str(part))
                content = "\n".join(parts)
            text = clean_text(content)
            if text:
                return text
    return None


def extract_custom_agent_user_id(payload: dict, query_params: dict[str, list[str]] | None = None) -> str:
    query_params = query_params or {}
    for key in ("user_id", "userId", "uid"):
        text = clean_text((query_params.get(key) or [None])[0])
        if text:
            return text
    for key in ("user_id", "userId", "uid"):
        text = clean_text(payload.get(key))
        if text:
            return text
    return DEFAULT_MCP_USER_ID


def normalize_account(value: object) -> str:
    return (clean_text(value) or "").lower()


def validate_account(account: str) -> None:
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]{2,32}", account, re.UNICODE):
        raise ValueError("账号只能包含中文、字母、数字、下划线和短横线，长度 2-32。")


def clean_int(value: object, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_json(value: object, fallback):
    if value is None or value == "":
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def get_bot_services():
    """Lazy-load the QQ bot's intelligent dialogue services when available."""
    global _BOT_SERVICES
    global _BOT_BRIDGE_ERROR

    if _BOT_SERVICES is not None:
        return _BOT_SERVICES
    if _BOT_BRIDGE_ERROR:
        return None
    if not BOT_SERVICE_ROOT.exists():
        _BOT_BRIDGE_ERROR = f"bot service root not found: {BOT_SERVICE_ROOT}"
        return None

    try:
        if str(BOT_SERVICE_ROOT) not in sys.path:
            sys.path.insert(0, str(BOT_SERVICE_ROOT))
        # Keep web and bot dialogue on the same SQLite file without editing bot .env.
        os.environ["SEU_CAMPUS_DB_PATH"] = str(DB_PATH)
        from src.services import config as bot_config  # type: ignore

        bot_config.reload_from_env()
        from src.services.commands import settings_link  # type: ignore
        from src.services.db_access import ensure_user as bot_ensure_user  # type: ignore
        from src.services.db_access import get_db as bot_get_db  # type: ignore
        from src.services.llm import generate_reply, route_message  # type: ignore
        from src.services.rag import search_school_events  # type: ignore

        _BOT_SERVICES = {
            "ensure_user": bot_ensure_user,
            "get_db": bot_get_db,
            "generate_reply": generate_reply,
            "route_message": route_message,
            "search_school_events": search_school_events,
            "settings_link": settings_link,
        }
        return _BOT_SERVICES
    except Exception as exc:
        _BOT_BRIDGE_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def clean_json_array(value: object, fallback: list) -> list:
    if isinstance(value, list):
        return [item for item in value if str(item).strip()]
    parsed = parse_json(value, None)
    if isinstance(parsed, list):
        return [item for item in parsed if str(item).strip()]
    text = clean_text(value)
    if not text:
        return fallback
    return [part.strip() for part in re.split(r"[,，\n]", text) if part.strip()]


def normalize_time_list(value: object, fallback: list[str] | None = None) -> list[str]:
    fallback = fallback or ["08:30"]
    values = clean_json_array(value, fallback)
    result: list[str] = []
    for item in values:
        match = re.match(r"^(\d{1,2}):(\d{2})", str(item).strip())
        if not match:
            continue
        hour = min(max(int(match.group(1)), 0), 23)
        minute = min(max(int(match.group(2)), 0), 59)
        result.append(f"{hour:02d}:{minute:02d}")
    return sorted(set(result)) or fallback


def infer_student_level(grade: str | None) -> str | None:
    text = grade or ""
    if "博" in text:
        return "博"
    if "硕" in text or "研" in text:
        return "硕"
    if text:
        return "本"
    return None


def infer_enrollment_year(grade: str | None) -> int | None:
    match = re.search(r"(20\d{2})", grade or "")
    return int(match.group(1)) if match else None


def frontend_status(db_status: str | None) -> str:
    return {"todo": "pending", "doing": "pending", "done": "done", "cancelled": "cancelled"}.get(
        db_status or "todo", "pending"
    )


def db_status(frontend_value: str | None) -> str:
    return {"pending": "todo", "done": "done", "cancelled": "cancelled"}.get(frontend_value or "pending", "todo")


def frontend_frequency(db_frequency: str | None) -> str:
    return "date" if db_frequency == "once" else (db_frequency or "daily")


def db_frequency(frontend_value: str | None) -> str:
    return "once" if frontend_value == "date" else (frontend_value or "daily")


def notification_frontend_type(db_type: str | None) -> str:
    return "interest" if db_type == "news" else "custom"


def notification_db_type(frontend_type: str | None) -> str:
    return "news" if frontend_type == "interest" else "fixed"


def schedule_to_courses(schedule_value: object) -> list[dict]:
    schedule = parse_json(schedule_value, [])
    if isinstance(schedule, list):
        return schedule
    if isinstance(schedule, dict) and isinstance(schedule.get("courses"), list):
        return schedule["courses"]
    if isinstance(schedule, dict) and isinstance(schedule.get("schedule"), dict):
        courses: list[dict] = []
        for day, day_courses in schedule["schedule"].items():
            if not isinstance(day_courses, list):
                continue
            for item in day_courses:
                if isinstance(item, dict):
                    courses.append({"day_of_week": int(day), **item})
        return courses
    return []


def courses_to_schedule(courses_value: object) -> dict:
    courses = courses_value if isinstance(courses_value, list) else []
    grouped: dict[str, list[dict]] = {str(day): [] for day in range(1, 8)}
    for item in courses:
        if not isinstance(item, dict):
            continue
        course_name = clean_text(item.get("course_name"))
        if not course_name:
            continue
        day = min(max(clean_int(item.get("day_of_week"), 1) or 1, 1), 7)
        start_section = min(max(clean_int(item.get("start_section") or item.get("start_time"), 1) or 1, 1), 13)
        end_section = min(max(clean_int(item.get("end_section") or item.get("end_time"), start_section) or start_section, 1), 13)
        if end_section < start_section:
            end_section = start_section
        grouped[str(day)].append(
            {
                **item,
                "course_name": course_name,
                "day_of_week": str(day),
                "start_section": str(start_section),
                "end_section": str(end_section),
                "start_time": str(start_section),
                "end_time": str(end_section),
            }
        )
    return {"schedule": grouped}


def empty_bundle(user_id: str) -> dict:
    return {
        "user": {"user_id": user_id, "nickname": ""},
        "profile": {
            "user_id": user_id,
            "real_name": "",
            "gender": "",
            "birthday": "",
            "school": "东南大学",
            "campus": "",
            "college": "",
            "major": "",
            "grade": "",
            "interests": "[]",
            "goals": "[]",
            "preferences": "{}",
            "personal_description": "",
            "assistant_persona": "",
            "updated_at": "",
        },
        "deadlines": [],
        "courses": [],
        "push_settings": {
            "user_id": user_id,
            "content_preferences": "[]",
            "daily_ddl_enabled": 1,
            "push_frequency": "daily",
            "push_times": '["08:30"]',
            "quiet_hours_start": "",
            "quiet_hours_end": "",
            "deadline_lookahead_days": 7,
            "updated_at": "",
        },
    }


def ensure_user(conn: sqlite3.Connection, user_id: str | None) -> str:
    actual_user_id = clean_text(user_id)
    if not actual_user_id:
        raise ValueError("缺少用户标识 user_id，请从 /信息设置 链接进入。")
    conn.execute(
        """
        INSERT INTO users_table (uuid)
        VALUES (?)
        ON CONFLICT(uuid) DO NOTHING
        """,
        (actual_user_id,),
    )
    return actual_user_id


def ensure_optional_user(conn: sqlite3.Connection, user_id: str | None = None) -> str:
    actual_user_id = clean_text(user_id) or str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO users_table (uuid)
        VALUES (?)
        ON CONFLICT(uuid) DO NOTHING
        """,
        (actual_user_id,),
    )
    return actual_user_id


def account_for_user(conn: sqlite3.Connection, user_id: str) -> str:
    row = conn.execute("SELECT account FROM user_account_map WHERE user_id = ?", (user_id,)).fetchone()
    return row["account"] if row else ""


def build_identity_reply(conn: sqlite3.Connection, user_id: str) -> str:
    row = conn.execute("SELECT * FROM users_table WHERE uuid = ?", (user_id,)).fetchone()
    if not row:
        return "\u6211\u8fd8\u6ca1\u6709\u8bfb\u5230\u4f60\u7684\u7528\u6237\u4fe1\u606f\u3002"

    profile = parse_json(row["profile"], {})
    if not isinstance(profile, dict):
        profile = {}
    interests = parse_json(row["interest"], [])
    if not isinstance(interests, list):
        interests = []
    goals = profile.get("goals") if isinstance(profile.get("goals"), list) else []

    default_name = "\u6821\u56ed\u52a9\u624b\u7528\u6237"
    display_name = row["nickname"] or profile.get("real_name") or default_name
    lines = [f"\u4f60\u662f {display_name}\u3002"]
    school = row["school"] or profile.get("school")
    major = row["major"] or profile.get("major")
    campus = profile.get("campus")
    college = profile.get("college")
    grade = profile.get("grade")

    identity_parts = [
        str(school or ""),
        str(campus or ""),
        str(college or ""),
        str(grade or ""),
        str(major or ""),
    ]
    identity_text = "\uff0c".join(part for part in identity_parts if part)
    if identity_text:
        lines.append(f"\u8eab\u4efd\u4fe1\u606f\uff1a{identity_text}")
    if interests:
        lines.append("\u5174\u8da3\u65b9\u5411\uff1a" + "\u3001".join(str(item) for item in interests[:8]))
    if goals:
        lines.append("\u76ee\u6807\uff1a" + "\u3001".join(str(item) for item in goals[:5]))
    return "\n".join(lines)


def build_deadline_reply(conn: sqlite3.Connection, user_id: str, message: str) -> str:
    scope = deadline_query_scope(message)
    where = "WHERE user_id = ? AND status NOT IN ('done', 'cancelled')"
    params: list[object] = [user_id]
    title = "\u6700\u8fd1\u7684 DDL\uff1a"
    empty = "\u4f60\u73b0\u5728\u6ca1\u6709\u5f85\u529e\u8bb0\u5f55\u3002"

    if scope == "today":
        where += " AND date(end_time) = date('now','localtime')"
        title = "\u4eca\u5929\u7684 DDL\uff1a"
        empty = "\u4eca\u5929\u6ca1\u6709\u67e5\u5230 DDL\u3002"
    elif scope == "week":
        where += " AND date(end_time) BETWEEN date('now','localtime') AND date('now','localtime','+7 days')"
        title = "\u672a\u6765 7 \u5929\u7684 DDL\uff1a"
        empty = "\u672a\u6765 7 \u5929\u6ca1\u6709\u67e5\u5230 DDL\u3002"
    else:
        where += " AND (end_time IS NULL OR date(end_time) >= date('now','localtime'))"

    rows = conn.execute(
        f"""
        SELECT name, type, end_time, status, importance, description
        FROM plan_table
        {where}
        ORDER BY
            CASE WHEN end_time IS NULL THEN 1 ELSE 0 END,
            end_time ASC,
            importance ASC
        LIMIT 8
        """,
        params,
    ).fetchall()
    if not rows:
        return empty

    lines = [title]
    for row in rows:
        item_name = row["name"] or "\u672a\u547d\u540d"
        deadline = row["end_time"] or "\u672a\u8bbe\u7f6e"
        status = row["status"] or "todo"
        importance = row["importance"] or 3
        desc = row["description"] or ""
        line = f"- {item_name}\uff0c\u622a\u6b62 {deadline}\uff0c\u72b6\u6001 {status}\uff0c\u91cd\u8981\u5ea6 {importance}"
        if desc:
            line += f"\uff0c{desc}"
        lines.append(line)
    return "\n".join(lines)


def login_account(
    account_value: object,
    *,
    bind_user_id: str | None = None,
    legacy_user_id: str | None = None,
) -> dict:
    account = normalize_account(account_value)
    validate_account(account)

    with get_connection() as conn:
        row = conn.execute("SELECT user_id FROM user_account_map WHERE account = ?", (account,)).fetchone()
        requested_user_id = clean_text(bind_user_id)
        if row:
            if requested_user_id and requested_user_id != row["user_id"]:
                raise ValueError("该账号已经绑定过其他用户。请换一个账号，或联系管理员迁移绑定。")
            return load_user_bundle(row["user_id"])

        candidate_user_id = requested_user_id or clean_text(legacy_user_id)
        if candidate_user_id:
            mapped = conn.execute("SELECT account FROM user_account_map WHERE user_id = ?", (candidate_user_id,)).fetchone()
            if mapped:
                raise ValueError(f"这个用户已经绑定账号 {mapped['account']}，不能重复绑定。")
            user_id = ensure_optional_user(conn, candidate_user_id)
        else:
            user_id = ensure_optional_user(conn)

        conn.execute(
            """
            INSERT INTO user_account_map (account, user_id)
            VALUES (?, ?)
            """,
            (account, user_id),
        )

    return load_user_bundle(user_id)


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_count(conn: sqlite3.Connection, table_name: str) -> int | None:
    if not table_exists(conn, table_name):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def build_health_report() -> dict:
    core_tables = [
        "users_table",
        "user_account_map",
        "plan_table",
        "notification_table",
        "context_table",
        "web_context_table",
        "school_event_table",
        "tools_table",
    ]
    report = {
        "ok": True,
        "service": "Campus Jarvis user_info_update",
        "schema": "v3",
        "time": datetime.now().isoformat(timespec="seconds"),
        "paths": {
            "project_dir": str(PROJECT_DIR),
            "app_dir": str(BASE_DIR),
            "static_dir": str(STATIC_DIR),
            "db": str(DB_PATH),
        },
        "static": {
            "exists": STATIC_DIR.exists(),
            "index_exists": (STATIC_DIR / "index.html").exists(),
        },
        "bot_intelligence": {
            "root": str(BOT_SERVICE_ROOT),
            "available": False,
            "error": "",
        },
        "backend": {
            "name": "decision",
            "status": "degraded",
        },
        "database": {
            "exists": DB_PATH.exists(),
            "size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
            "connectable": False,
            "tables": {},
            "counts": {},
        },
    }
    try:
        with get_connection() as conn:
            report["database"]["connectable"] = True
            for table in core_tables:
                exists = table_exists(conn, table)
                report["database"]["tables"][table] = exists
                report["database"]["counts"][table] = table_count(conn, table) if exists else None

            missing_tables = [table for table, exists in report["database"]["tables"].items() if not exists]
            if missing_tables:
                report["ok"] = False
                report["database"]["missing_tables"] = missing_tables
            services = get_bot_services()
            report["bot_intelligence"]["available"] = services is not None
            report["bot_intelligence"]["error"] = _BOT_BRIDGE_ERROR
            report["backend"] = decision_bridge.status()
            if report["backend"]["status"] != "ready":
                report["ok"] = False
    except Exception as exc:  # health 必须把错误吐清楚，方便公网排障。
        report["ok"] = False
        report["database"]["error"] = str(exc)
    return report


def load_user_bundle(user_id: str | None = None) -> dict:
    with get_connection() as conn:
        actual_user_id = ensure_user(conn, user_id)
        user_row = row_to_dict(conn.execute("SELECT * FROM users_table WHERE uuid = ?", (actual_user_id,)).fetchone())
        bundle = empty_bundle(actual_user_id)
        bundle["account"] = account_for_user(conn, actual_user_id)
        if not user_row:
            bundle["web_context"] = load_web_context(conn, actual_user_id)
            return bundle

        profile_json = parse_json(user_row.get("profile"), {})
        if not isinstance(profile_json, dict):
            profile_json = {}

        bundle["user"] = {
            "user_id": actual_user_id,
            "nickname": user_row.get("nickname") or "",
        }
        bundle["profile"].update(
            {
                "user_id": actual_user_id,
                "real_name": profile_json.get("real_name", ""),
                "gender": user_row.get("gender") or "",
                "birthday": user_row.get("birthday") or "",
                "school": user_row.get("school") or "东南大学",
                "campus": profile_json.get("campus", ""),
                "college": profile_json.get("college", ""),
                "major": user_row.get("major") or "",
                "grade": profile_json.get("grade", ""),
                "interests": dump_json(parse_json(user_row.get("interest"), [])),
                "goals": dump_json(profile_json.get("goals", [])),
                "preferences": dump_json(profile_json.get("preferences", {})),
                "personal_description": profile_json.get("personal_description", ""),
                "assistant_persona": profile_json.get("assistant_persona", ""),
            }
        )
        bundle["courses"] = schedule_to_courses(user_row.get("schedule"))

        bundle["deadlines"] = [
            {
                "deadline_id": row["id"],
                "title": row["name"] or "",
                "description": row["description"] or "",
                "start_time": row["start_time"] or "",
                "deadline_time": row["end_time"] or "",
                "priority": row["importance"] or 3,
                "status": frontend_status(row["status"]),
                "category": row["type"] or "",
                "source_type": "manual",
                "source_ref": "",
            }
            for row in conn.execute(
                """
                SELECT *
                FROM plan_table
                WHERE user_id = ?
                ORDER BY end_time ASC, importance ASC, id ASC
                """,
                (actual_user_id,),
            ).fetchall()
        ]

        push_items = []
        all_times: list[str] = []
        for row in conn.execute(
            """
            SELECT *
            FROM notification_table
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (actual_user_id,),
        ).fetchall():
            times = normalize_time_list(row["notify_times"], ["08:30"])
            all_times.extend(times)
            push_items.append(
                {
                    "push_id": row["id"],
                    "type": notification_frontend_type(row["type"]),
                    "title": row["title"] or "",
                    "content": row["content"] or "",
                    "frequency": frontend_frequency(row["frequency"]),
                    "date": row["notify_date"] or "",
                    "weekdays": [row["weekday"]] if row["weekday"] else [],
                    "times": times,
                }
            )
        bundle["push_settings"] = {
            "user_id": actual_user_id,
            "content_preferences": dump_json(push_items),
            "daily_ddl_enabled": 1 if push_items else 0,
            "push_frequency": push_items[0]["frequency"] if push_items else "daily",
            "push_times": dump_json(sorted(set(all_times)) or ["08:30"]),
            "quiet_hours_start": "",
            "quiet_hours_end": "",
            "deadline_lookahead_days": 7,
            "updated_at": "",
        }
        web_context = load_web_context(conn, actual_user_id)
        if not web_context:
            web_context = get_shared_context_with_mirror(actual_user_id)
        bundle["web_context"] = web_context
        return bundle


def save_user(conn: sqlite3.Connection, user_id: str, payload: dict) -> None:
    user_payload = payload.get("user") or {}
    profile_payload = payload.get("profile") or {}
    courses_payload = payload.get("courses") or []

    interests = clean_json_array(profile_payload.get("interests"), [])
    goals = clean_json_array(profile_payload.get("goals"), [])
    grade = clean_text(profile_payload.get("grade"))
    profile_json = {
        "real_name": clean_text(profile_payload.get("real_name")) or "",
        "campus": clean_text(profile_payload.get("campus")) or "",
        "college": clean_text(profile_payload.get("college")) or "",
        "grade": grade or "",
        "goals": goals,
        "preferences": parse_json(profile_payload.get("preferences"), {}),
        "personal_description": clean_text(profile_payload.get("personal_description")) or "",
        "assistant_persona": clean_text(profile_payload.get("assistant_persona")) or "",
    }

    conn.execute(
        """
        UPDATE users_table
        SET nickname = ?,
            gender = ?,
            birthday = ?,
            school = ?,
            major = ?,
            enrollment_year = ?,
            student_level = ?,
            interest = ?,
            profile = ?,
            schedule = ?
        WHERE uuid = ?
        """,
        (
            clean_text(user_payload.get("nickname")),
            clean_text(profile_payload.get("gender")),
            clean_text(profile_payload.get("birthday")),
            clean_text(profile_payload.get("school")) or "东南大学",
            clean_text(profile_payload.get("major")),
            infer_enrollment_year(grade),
            infer_student_level(grade),
            dump_json(interests),
            dump_json(profile_json),
            dump_json(courses_to_schedule(courses_payload)),
            user_id,
        ),
    )


def save_plans(conn: sqlite3.Connection, user_id: str, payload: list[dict]) -> None:
    existing_ids = {
        row["id"] for row in conn.execute("SELECT id FROM plan_table WHERE user_id = ?", (user_id,)).fetchall()
    }
    kept_ids: set[int] = set()
    for item in payload:
        title = clean_text(item.get("title"))
        end_time = clean_text(item.get("deadline_time"))
        if not title and not end_time:
            continue
        if not title or not end_time:
            raise ValueError("每条待办都需要填写名称和结束时间。")

        plan_id = clean_int(item.get("deadline_id"))
        values = (
            title,
            clean_text(item.get("category")),
            clean_text(item.get("start_time")),
            end_time,
            None,
            db_status(clean_text(item.get("status"))),
            min(max(clean_int(item.get("priority"), 3) or 3, 1), 5),
            clean_text(item.get("description")),
        )

        if plan_id and plan_id in existing_ids:
            conn.execute(
                """
                UPDATE plan_table
                SET name = ?, type = ?, start_time = ?, end_time = ?, reminder_time = ?,
                    status = ?, importance = ?, description = ?, updated_at = datetime('now','localtime')
                WHERE id = ? AND user_id = ?
                """,
                (*values, plan_id, user_id),
            )
            kept_ids.add(plan_id)
        else:
            cursor = conn.execute(
                """
                INSERT INTO plan_table (
                    user_id, name, type, start_time, end_time,
                    reminder_time, status, importance, description,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))
                """,
                (user_id, *values),
            )
            kept_ids.add(int(cursor.lastrowid))

    stale_ids = existing_ids - kept_ids
    if stale_ids:
        placeholders = ",".join("?" for _ in stale_ids)
        conn.execute(
            f"DELETE FROM plan_table WHERE user_id = ? AND id IN ({placeholders})",
            (user_id, *stale_ids),
        )


def normalize_push_payload(push_payload: dict) -> list[dict]:
    items = parse_json(push_payload.get("content_preferences"), [])
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def save_notifications(conn: sqlite3.Connection, user_id: str, push_payload: dict) -> None:
    push_items = normalize_push_payload(push_payload)
    existing_ids = {
        row["id"] for row in conn.execute("SELECT id FROM notification_table WHERE user_id = ?", (user_id,)).fetchall()
    }
    kept_ids: set[int] = set()

    for item in push_items:
        title = clean_text(item.get("title"))
        content = clean_text(item.get("content"))
        if not title and not content:
            continue
        if not title:
            raise ValueError("每条推送都需要填写标题。")

        push_id = clean_int(item.get("push_id"))
        frequency = frontend_frequency(item.get("frequency"))
        db_freq = db_frequency(frequency)
        weekdays = clean_json_array(item.get("weekdays"), [])
        weekday = clean_int(weekdays[0]) if db_freq == "weekly" and weekdays else None
        notify_date = clean_text(item.get("date")) if db_freq == "once" else None
        times = normalize_time_list(item.get("times"), ["08:30"])
        values = (
            notification_db_type(item.get("type")),
            title,
            content,
            db_freq,
            weekday,
            notify_date,
            dump_json(times),
            1,
        )

        if push_id and push_id in existing_ids:
            conn.execute(
                """
                UPDATE notification_table
                SET type = ?, title = ?, content = ?, frequency = ?, weekday = ?,
                    notify_date = ?, notify_times = ?, enabled = ?, updated_at = datetime('now','localtime')
                WHERE id = ? AND user_id = ?
                """,
                (*values, push_id, user_id),
            )
            kept_ids.add(push_id)
        else:
            cursor = conn.execute(
                """
                INSERT INTO notification_table (
                    user_id, type, title, content, frequency,
                    weekday, notify_date, notify_times, enabled,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))
                """,
                (user_id, *values),
            )
            kept_ids.add(int(cursor.lastrowid))

    stale_ids = existing_ids - kept_ids
    if stale_ids:
        placeholders = ",".join("?" for _ in stale_ids)
        conn.execute(
            f"DELETE FROM notification_table WHERE user_id = ? AND id IN ({placeholders})",
            (user_id, *stale_ids),
        )


def save_user_bundle(payload: dict) -> dict:
    user_payload = payload.get("user") or {}
    profile_payload = payload.get("profile") or {}
    user_id = clean_text(payload.get("user_id") or user_payload.get("user_id") or profile_payload.get("user_id"))
    account = normalize_account(payload.get("account"))

    with get_connection() as conn:
        actual_user_id = ensure_user(conn, user_id)
        if account:
            validate_account(account)
            mapped_account = conn.execute("SELECT user_id FROM user_account_map WHERE account = ?", (account,)).fetchone()
            if mapped_account and mapped_account["user_id"] != actual_user_id:
                raise ValueError("该账号已经绑定过其他用户，不能通过保存操作改绑。")
            mapped_user = conn.execute("SELECT account FROM user_account_map WHERE user_id = ?", (actual_user_id,)).fetchone()
            if mapped_user and mapped_user["account"] != account:
                raise ValueError(f"这个用户已经绑定账号 {mapped_user['account']}，不能重复绑定。")
            conn.execute(
                """
                INSERT INTO user_account_map (account, user_id)
                VALUES (?, ?)
                ON CONFLICT(account) DO UPDATE SET
                    user_id = excluded.user_id,
                    updated_at = datetime('now','localtime')
                """,
                (account, actual_user_id),
            )
        save_user(conn, actual_user_id, payload)
        save_plans(conn, actual_user_id, payload.get("deadlines") or [])
        save_notifications(conn, actual_user_id, payload.get("push_settings") or {})

    return load_user_bundle(actual_user_id)


def load_web_context(conn: sqlite3.Connection, user_id: str) -> list[dict[str, str]]:
    row = conn.execute("SELECT context FROM web_context_table WHERE user_id = ?", (user_id,)).fetchone()
    context = parse_json(row["context"] if row else None, [])
    if not isinstance(context, list):
        return []
    return [
        {"role": str(item.get("role")), "content": str(item.get("content"))}
        for item in context
        if isinstance(item, dict) and item.get("role") and item.get("content")
    ]


def save_web_context(conn: sqlite3.Connection, user_id: str, context: list[dict[str, str]]) -> None:
    clipped = context[-40:]
    conn.execute(
        """
        INSERT INTO web_context_table (user_id, context, updated_at)
        VALUES (?, ?, datetime('now','localtime'))
        ON CONFLICT(user_id) DO UPDATE SET
            context = excluded.context,
            updated_at = excluded.updated_at
        """,
        (user_id, dump_json(clipped)),
    )


def sync_web_context_mirror(user_id: str, context: list[dict[str, str]]) -> list[dict[str, str]]:
    with get_connection() as conn:
        save_web_context(conn, user_id, context)
        conn.commit()
    return context[-40:]


def get_shared_context_with_mirror(user_id: str) -> list[dict[str, str]]:
    try:
        context = decision_bridge.get_shared_context(user_id)
    except Exception:
        return []
    return context[-40:]


def record_shared_fast_path_reply(user_id: str, message: str, reply: str) -> list[dict[str, str]]:
    try:
        context = decision_bridge.record_reply(user_id, message, reply)
    except Exception:
        with get_connection() as conn:
            context = load_web_context(conn, user_id)
            context.append({"role": "user", "content": message})
            context.append({"role": "assistant", "content": reply})
            save_web_context(conn, user_id, context)
            conn.commit()
            return context[-40:]
    return sync_web_context_mirror(user_id, context)


def format_brief_time(value: object) -> str:
    text = clean_text(value)
    if not text:
        return "未设置时间"
    return text.replace("T", " ")[:16]


def build_daily_brief(conn: sqlite3.Connection, user_id: str) -> str:
    user = conn.execute("SELECT * FROM users_table WHERE uuid = ?", (user_id,)).fetchone()
    nickname = user["nickname"] if user and user["nickname"] else "同学"
    schedule = parse_json(user["schedule"] if user else None, {})
    courses = schedule_to_courses(schedule)
    today_weekday = datetime.now().isoweekday()
    today_courses = [
        item
        for item in courses
        if clean_int(item.get("day_of_week"), 0) == today_weekday and clean_text(item.get("course_name"))
    ]
    today_courses.sort(key=lambda item: clean_int(item.get("start_section") or item.get("start_time"), 99) or 99)

    today_deadlines = conn.execute(
        """
        SELECT name, type, end_time, importance
        FROM plan_table
        WHERE user_id = ?
          AND status NOT IN ('done', 'cancelled')
          AND date(end_time) = date('now','localtime')
        ORDER BY end_time ASC, importance ASC
        LIMIT 5
        """,
        (user_id,),
    ).fetchall()
    upcoming_deadlines = conn.execute(
        """
        SELECT name, type, end_time, importance
        FROM plan_table
        WHERE user_id = ?
          AND status NOT IN ('done', 'cancelled')
          AND (end_time IS NULL OR date(end_time) >= date('now','localtime'))
        ORDER BY end_time ASC, importance ASC
        LIMIT 5
        """,
        (user_id,),
    ).fetchall()
    pushes = conn.execute(
        """
        SELECT title, content, frequency, notify_times
        FROM notification_table
        WHERE user_id = ? AND enabled = 1
        ORDER BY id DESC
        LIMIT 4
        """,
        (user_id,),
    ).fetchall()

    lines = [f"{nickname}，这是你的今日简报："]
    if today_deadlines:
        lines.append("\n今日必须关注：")
        for row in today_deadlines:
            lines.append(f"- {row['name'] or '未命名 DDL'}，截止 {format_brief_time(row['end_time'])}，重要度 {row['importance'] or 3}")
    elif upcoming_deadlines:
        first = upcoming_deadlines[0]
        lines.append(f"\n今天没有查到当天截止的 DDL。最近一项是：{first['name'] or '未命名 DDL'}，截止 {format_brief_time(first['end_time'])}。")
    else:
        lines.append("\n今天没有待办压力。可以补充 DDL，让 Jarvis 后续帮你盯时间。")

    if today_courses:
        lines.append("\n今日课程：")
        for item in today_courses[:5]:
            start = item.get("start_section") or item.get("start_time") or "?"
            end = item.get("end_section") or item.get("end_time") or "?"
            location = clean_text(item.get("location")) or "地点未填写"
            lines.append(f"- {item.get('course_name')}，{start}-{end} 节，{location}")
    else:
        lines.append("\n今天没有录入课程。")

    if pushes:
        lines.append("\n建议关注：")
        for row in pushes:
            times = "、".join(normalize_time_list(row["notify_times"], ["08:30"]))
            lines.append(f"- {row['title'] or '未命名推送'}，{times} 提醒")
    else:
        lines.append("\n你还没有配置推送偏好。建议先加“竞赛提醒”或“讲座推荐”。")

    if today_deadlines:
        lines.append("\n行动建议：先处理最近截止项，再看课程安排，最后补充推送偏好。")
    elif today_courses:
        lines.append("\n行动建议：今天以课程节奏为主，课后留 20 分钟整理新的 DDL。")
    else:
        lines.append("\n行动建议：今天适合补全个人画像和关注方向，让系统后续更像你的校园秘书。")
    return "\n".join(lines)


def bot_profile_complete(user: dict | None) -> bool:
    if not user:
        return False
    required = ("nickname", "school", "major", "student_level", "interest")
    return all(user.get(key) for key in required)


def needs_school_information(message: str) -> bool:
    text = message.lower()
    return any(
        keyword in text
        for keyword in [
            "竞赛",
            "比赛",
            "讲座",
            "活动",
            "通知",
            "报名",
            "科研",
            "近期",
            "最近",
            "适合我",
            "competition",
            "lecture",
            "event",
        ]
    )


async def build_bot_smart_reply(user_id: str, message: str, context: list[dict[str, str]]) -> str:
    services = get_bot_services()
    if services is None:
        raise RuntimeError(_BOT_BRIDGE_ERROR or "bot intelligent service unavailable")

    services["ensure_user"](user_id)
    with services["get_db"](auto_create=True) as db:
        user = db.get_user(user_id)
        tools = db.fetch_all("tools_table")

    decision = await services["route_message"](
        message,
        user=user,
        tools=tools,
    )

    if decision.kind == "tool" and decision.tool_name:
        tool = next((item for item in tools if item.get("name") == decision.tool_name), None)
        if tool:
            return await services["generate_reply"](
                user_input=message,
                user=user,
                context=context,
                tool=tool,
            )

    if decision.kind == "profile_missing" and not bot_profile_complete(user):
        return (
            "我还缺少你的基础信息，暂时不能给出足够个性化的回答。\n"
            f"请先完善信息设置：{services['settings_link'](user_id)}"
        )

    interests = user.get("interest") if user else ""
    profile = user.get("profile") if user else ""
    events = services["search_school_events"](
        f"{message}\n兴趣：{interests}\n画像：{profile}",
        top_k=3,
    )
    if not events and needs_school_information(message):
        return (
            "我已经接入了智能检索链路，但当前校园信息库里还没有可匹配的学校通知、竞赛或讲座数据。\n"
            "所以我现在不能负责任地编出“近期竞赛/讲座”列表。\n\n"
            "下一步需要把学校官网、学院通知、公众号文章、竞赛平台等数据导入 school_event_table，"
            "并生成可检索摘要或 embedding。导入后，你就可以直接问：近期我感兴趣的竞赛有哪些？"
        )
    return await services["generate_reply"](
        user_input=message,
        user=user,
        context=context,
        events=events,
    )


def build_web_reply(conn: sqlite3.Connection, user_id: str, message: str) -> str:
    text = message.strip().lower()
    if is_time_sensitive_local_query(message):
        rows = conn.execute(
            """
            SELECT name, type, end_time, status, importance
            FROM plan_table
            WHERE user_id = ?
              AND status NOT IN ('done', 'cancelled')
              AND date(end_time) = date('now','localtime')
            ORDER BY end_time ASC, importance ASC
            LIMIT 5
            """,
            (user_id,),
        ).fetchall()
        if rows:
            lines = ["今天的 DDL："]
            for row in rows:
                lines.append(
                    f"- {row['name'] or '未命名'}，截止 {row['end_time'] or '未设置'}，"
                    f"状态 {row['status'] or 'todo'}，重要度 {row['importance'] or 3}"
                )
            return "\n".join(lines)
        return "今天没有查到 DDL。"
    if any(keyword in text for keyword in ["简报", "早报", "今日安排", "今日计划"]):
        return build_daily_brief(conn, user_id)

    if any(keyword in text for keyword in ["我是谁", "我的信息", "个人信息", "profile", "用户"]):
        row = conn.execute("SELECT * FROM users_table WHERE uuid = ?", (user_id,)).fetchone()
        if not row:
            return "我还没有读到你的用户信息。你可以先去“基本信息”里保存一次。"
        account = account_for_user(conn, user_id) or "未绑定"
        interests = "、".join(str(item) for item in parse_json(row["interest"], [])) or "未填写"
        return (
            f"当前用户：{row['nickname'] or '未填写'}\n"
            f"网页账号：{account}\n"
            f"学校：{row['school'] or '未填写'}\n"
            f"专业：{row['major'] or '未填写'}\n"
            f"兴趣：{interests}\n"
            "如果你是从 QQ bot 跳转来的，这里和 QQ bot 共享同一份用户资料。"
        )

    if any(keyword in text for keyword in ["ddl", "待办", "计划", "deadline", "今天"]):
        today_only = "今天" in text
        where = "WHERE user_id = ? AND status NOT IN ('done', 'cancelled')"
        params: tuple[object, ...] = (user_id,)
        if today_only:
            where += " AND date(end_time) = date('now','localtime')"
        rows = conn.execute(
            f"""
            SELECT name, type, end_time, status, importance
            FROM plan_table
            {where}
            ORDER BY end_time ASC, importance ASC
            LIMIT 5
            """,
            params,
        ).fetchall()
        if not rows:
            return "今天没有查到 DDL。" if today_only else "你现在还没有待办记录。"
        lines = ["今天的 DDL：" if today_only else "最近的待办："]
        for row in rows:
            lines.append(
                f"- {row['name'] or '未命名'}，截止 {row['end_time'] or '未设置'}，状态 {row['status'] or 'todo'}，重要度 {row['importance'] or 3}"
            )
        return "\n".join(lines)

    if any(keyword in text for keyword in ["推送", "提醒", "notification"]):
        rows = conn.execute(
            """
            SELECT title, content, frequency, notify_times, enabled
            FROM notification_table
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (user_id,),
        ).fetchall()
        if not rows:
            return "你还没有配置推送。可以去“推送信息”里添加讲座、DDL 或竞赛提醒。"
        lines = ["你当前配置的推送有："]
        for row in rows:
            times = "、".join(normalize_time_list(row["notify_times"], ["08:30"]))
            enabled = "启用" if row["enabled"] else "停用"
            lines.append(f"- {row['title'] or '未命名'}：{row['content'] or '无内容'}，{row['frequency']}，{times}，{enabled}")
        return "\n".join(lines)

    if any(keyword in text for keyword in ["课", "课程", "课表", "schedule"]):
        user = conn.execute("SELECT schedule FROM users_table WHERE uuid = ?", (user_id,)).fetchone()
        schedule = parse_json(user["schedule"] if user else None, {})
        courses = schedule_to_courses(schedule)
        if not courses:
            return "你还没有录入课表。可以去“课表信息”里添加课程。"
        lines = ["我从共享用户资料里读到这些课程："]
        for item in courses[:6]:
            lines.append(
                f"- 周{item.get('day_of_week', '?')} {item.get('course_name', '未命名课程')} "
                f"{item.get('start_section') or item.get('start_time', '')}-{item.get('end_section') or item.get('end_time', '')}节 "
                f"{item.get('location') or ''}".strip()
            )
        return "\n".join(lines)

    return (
        "收到。网页聊天现在使用独立的 Web 会话上下文，但会读取和 QQ bot 同一份用户资料。\n"
        "你可以问：我是谁、今天有什么 DDL、有什么推送、我的课表。"
    )


def handle_chat(payload: dict) -> dict:
    user_id = clean_text(payload.get("user_id"))
    message = clean_text(payload.get("message"))
    if not message:
        raise ValueError("消息不能为空。")

    with get_connection() as conn:
        actual_user_id = ensure_user(conn, user_id)
        context = load_web_context(conn, actual_user_id)

    context.append({"role": "user", "content": message})
    if is_identity_query(message):
        with get_connection() as conn:
            reply = build_identity_reply(conn, actual_user_id)
        engine = "rule_identity"
    elif is_time_sensitive_local_query(message):
        with get_connection() as conn:
            reply = build_deadline_reply(conn, actual_user_id, message)
        engine = "rule_time_sensitive"
    else:
        try:
            reply = asyncio.run(build_bot_smart_reply(actual_user_id, message, context))
            engine = "bot_intelligent_service"
        except Exception as exc:
            with get_connection() as conn:
                reply = build_web_reply(conn, actual_user_id, message)
            engine = f"rule_fallback: {type(exc).__name__}: {exc}"

    context.append({"role": "assistant", "content": reply})
    with get_connection() as conn:
        save_web_context(conn, actual_user_id, context)
    return {"ok": True, "user_id": actual_user_id, "reply": reply, "context": context[-40:], "engine": engine}


def handle_daily_brief(payload: dict) -> dict:
    user_id = clean_text(payload.get("user_id"))
    with get_connection() as conn:
        actual_user_id = ensure_user(conn, user_id)
        context = load_web_context(conn, actual_user_id)
        brief = build_daily_brief(conn, actual_user_id)
        context.append({"role": "assistant", "content": brief})
        save_web_context(conn, actual_user_id, context)
        return {"ok": True, "user_id": actual_user_id, "brief": brief, "context": context[-40:]}


def handle_clear_chat(payload: dict) -> dict:
    user_id = clean_text(payload.get("user_id"))
    with get_connection() as conn:
        actual_user_id = ensure_user(conn, user_id)
        save_web_context(conn, actual_user_id, [])
        return {"ok": True, "user_id": actual_user_id, "context": []}


_ORIGINAL_BUILD_HEALTH_REPORT = build_health_report
_ORIGINAL_LOAD_USER_BUNDLE = load_user_bundle


def build_health_report() -> dict:
    report = _ORIGINAL_BUILD_HEALTH_REPORT()
    report["backend"] = decision_bridge.status()
    if report["backend"]["status"] != "ready":
        report["ok"] = False
    return report


def load_user_bundle(user_id: str | None = None) -> dict:
    bundle = _ORIGINAL_LOAD_USER_BUNDLE(user_id)
    actual_user_id = clean_text(
        bundle.get("user_id")
        or (bundle.get("user") or {}).get("user_id")
        or (bundle.get("profile") or {}).get("user_id")
        or user_id
    )
    if actual_user_id and not bundle.get("web_context"):
        shared_context = get_shared_context_with_mirror(actual_user_id)
        bundle["web_context"] = shared_context
        if shared_context:
            sync_web_context_mirror(actual_user_id, shared_context)
    return bundle


def handle_chat(payload: dict) -> dict:
    user_id = clean_text(payload.get("user_id"))
    message = clean_text(payload.get("message"))
    if not message:
        raise ValueError("消息不能为空。")

    with get_connection() as conn:
        actual_user_id = ensure_user(conn, user_id)

    if is_identity_query(message):
        with get_connection() as conn:
            reply = build_identity_reply(conn, actual_user_id)
        engine = "rule_identity"
        context = record_shared_fast_path_reply(actual_user_id, message, reply)
    elif is_time_sensitive_local_query(message):
        with get_connection() as conn:
            reply = build_deadline_reply(conn, actual_user_id, message)
        engine = "rule_time_sensitive"
        context = record_shared_fast_path_reply(actual_user_id, message, reply)
    else:
        result = decision_bridge.ask(actual_user_id, message)
        reply = result.reply
        engine = result.engine
        context = sync_web_context_mirror(actual_user_id, result.context)

    return {"ok": True, "user_id": actual_user_id, "reply": reply, "context": context[-40:], "engine": engine}


def handle_clear_chat(payload: dict) -> dict:
    user_id = clean_text(payload.get("user_id"))
    with get_connection() as conn:
        actual_user_id = ensure_user(conn, user_id)
    decision_bridge.clear_context(actual_user_id)
    with get_connection() as conn:
        save_web_context(conn, actual_user_id, [])
        conn.commit()
    return {"ok": True, "user_id": actual_user_id, "context": []}


def mcp_response(request_id, result=None, error=None) -> str | None:
    if request_id is None:
        return None
    payload = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result or {}
    return dump_json(payload)


def mcp_tool_schema() -> dict:
    return {
        "name": "ask_campus_jarvis",
        "description": "向 Campus Jarvis 提问，查询校园信息、竞赛讲座、DDL、课表、推送偏好和个人画像相关内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户的自然语言问题，例如：近期我感兴趣的竞赛有哪些？",
                },
                "user_id": {
                    "type": "string",
                    "description": "可选。Campus Jarvis 用户 UUID。不传时使用演示用户。",
                },
            },
            "required": ["query"],
        },
    }


def handle_mcp_rpc(message: dict) -> str | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if method == "initialize":
        return mcp_response(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "Campus Jarvis MCP", "version": "0.1.0"},
            },
        )

    if method in {"notifications/initialized", "ping"}:
        return mcp_response(request_id, {})

    if method == "tools/list":
        return mcp_response(request_id, {"tools": [mcp_tool_schema()]})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name != "ask_campus_jarvis":
            return mcp_response(
                request_id,
                error={"code": -32602, "message": f"未知工具：{name}"},
            )
        query = clean_text(arguments.get("query"))
        if not query:
            return mcp_response(
                request_id,
                error={"code": -32602, "message": "query 不能为空"},
            )
        user_id = clean_text(arguments.get("user_id")) or DEFAULT_MCP_USER_ID
        try:
            result = handle_chat({"user_id": user_id, "message": query})
            answer = result.get("reply") or "未生成回答。"
        except Exception as exc:
            answer = f"Campus Jarvis 暂时无法处理这个问题：{type(exc).__name__}: {exc}"
        return mcp_response(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": answer,
                    }
                ],
                "isError": False,
            },
        )

    return mcp_response(
        request_id,
        error={"code": -32601, "message": f"不支持的方法：{method}"},
    )


class AppHandler(BaseHTTPRequestHandler):
    server_version = "CampusJarvisUserInfo/1.7"
    protocol_version = "HTTP/1.1"

    @staticmethod
    def is_rokid_plugin_ask_path(path: str) -> bool:
        return (
            path == "/rokid/plugin/ask"
            or path.startswith("/rokid/plugin/ask/")
            or path == "/ask"
            or path.startswith("/ask/")
        )

    @staticmethod
    def is_rizon_custom_agent_path(path: str) -> bool:
        return path == "/rizon/custom-agent" or path.startswith("/rizon/custom-agent/")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/mcp/sse":
            self.handle_mcp_sse()
            return
        if self.is_rizon_custom_agent_path(parsed.path):
            self.handle_rizon_custom_agent_get(parsed)
            return
        if self.is_rokid_plugin_ask_path(parsed.path):
            self.handle_rokid_plugin_get(parsed)
            return
        if parsed.path == "/api/user/bootstrap":
            try:
                query = parse_qs(parsed.query)
                account = (query.get("account") or [None])[0]
                if account:
                    bundle = login_account(account)
                else:
                    bundle = load_user_bundle((query.get("user_id") or [None])[0])
                self.send_json({"ok": True, **bundle})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/health":
            self.send_json(build_health_report())
            return
        if self.static_file_exists(parsed.path):
            self.serve_static(parsed.path)
            return
        if parsed.path not in ("", "/") and not parsed.path.startswith("/static/"):
            self.handle_rizon_custom_agent_get(parsed)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/mcp/message":
            self.handle_mcp_message(parsed)
            return
        if self.is_rizon_custom_agent_path(parsed.path):
            self.handle_rizon_custom_agent_post(parsed)
            return
        if self.is_rokid_plugin_ask_path(parsed.path):
            self.handle_rokid_plugin_post()
            return
        if parsed.path == "/api/account/login":
            try:
                payload = self.read_json()
                self.send_json(
                    {
                        "ok": True,
                        **login_account(
                            payload.get("account"),
                            bind_user_id=payload.get("bind_user_id"),
                            legacy_user_id=payload.get("legacy_user_id"),
                        ),
                    }
                )
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/user/save":
            try:
                payload = self.read_json()
                bundle = save_user_bundle(payload)
                self.send_json({"ok": True, **bundle})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/chat":
            try:
                payload = self.read_json()
                self.send_json(handle_chat(payload))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/daily_brief":
            try:
                payload = self.read_json()
                self.send_json(handle_daily_brief(payload))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/chat/clear":
            try:
                payload = self.read_json()
                self.send_json(handle_clear_chat(payload))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return
        self.handle_rizon_custom_agent_post(parsed)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_mcp_sse(self) -> None:
        session_id = str(uuid.uuid4())
        messages: queue.Queue[str] = queue.Queue()
        MCP_SESSIONS[session_id] = messages
        endpoint = f"/mcp/message?session_id={session_id}"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def write_chunk(data: bytes) -> None:
            self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
            self.wfile.write(data)
            self.wfile.write(b"\r\n")
            self.wfile.flush()

        def write_event(event: str, data: str) -> None:
            payload = f"event: {event}\ndata: {data}\n\n".encode("utf-8")
            write_chunk(payload)

        try:
            write_chunk(((": " + " " * 65536 + "\n\n")).encode("utf-8"))
            write_event("endpoint", endpoint)
            while True:
                try:
                    message = messages.get(timeout=15)
                    write_event("message", message)
                except queue.Empty:
                    write_chunk(b": ping\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            MCP_SESSIONS.pop(session_id, None)

    def handle_mcp_message(self, parsed) -> None:
        query = parse_qs(parsed.query)
        session_id = (query.get("session_id") or [None])[0]
        messages = MCP_SESSIONS.get(session_id or "")
        if messages is None:
            self.send_json({"ok": False, "error": "MCP session 不存在或已断开。"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_json()
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return

        batch = payload if isinstance(payload, list) else [payload]
        for item in batch:
            if not isinstance(item, dict):
                continue
            response = handle_mcp_rpc(item)
            if response:
                messages.put(response)
        self.send_response(HTTPStatus.ACCEPTED)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def custom_agent_authorized(self, parsed) -> bool:
        query = parse_qs(parsed.query)
        provided = (
            clean_text(self.headers.get("Authorization"))
            or clean_text(self.headers.get("X-API-Key"))
            or clean_text(self.headers.get("X-AK"))
            or clean_text((query.get("ak") or query.get("api_key") or [None])[0])
        )
        if not provided:
            return True
        provided = provided.removeprefix("Bearer ").strip()
        return provided == RIZON_CUSTOM_AGENT_AK

    def send_custom_agent_reply(self, text: object, user_id: object) -> None:
        query = clean_text(text)
        if not query:
            self.send_json(
                {
                    "ok": False,
                    "error": "query/message/input 不能为空。",
                    "answer": "我没有收到有效问题。",
                    "text": "我没有收到有效问题。",
                },
                HTTPStatus.BAD_REQUEST,
            )
            return
        try:
            result = handle_chat({"user_id": clean_text(user_id) or DEFAULT_MCP_USER_ID, "message": query})
            answer = result.get("reply") or ""
            self.send_json(
                {
                    "ok": True,
                    "answer": answer,
                    "text": answer,
                    "content": answer,
                    "message": answer,
                    "engine": result.get("engine") or "",
                    "user_id": result.get("user_id") or clean_text(user_id) or DEFAULT_MCP_USER_ID,
                }
            )
        except Exception as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "answer": "Campus Jarvis 暂时无法处理这个问题。",
                    "text": "Campus Jarvis 暂时无法处理这个问题。",
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def handle_rizon_custom_agent_get(self, parsed) -> None:
        if not self.custom_agent_authorized(parsed):
            self.send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        query = parse_qs(parsed.query)
        text = extract_custom_agent_text({}, query)
        user_id = extract_custom_agent_user_id({}, query)
        if text:
            self.send_custom_agent_reply(text, user_id)
            return
        self.send_json(
            {
                "ok": True,
                "name": "Campus Jarvis",
                "description": "Campus Jarvis custom agent endpoint",
                "endpoint": "/rizon/custom-agent",
                "accepted_methods": ["GET", "POST"],
                "accepted_fields": ["query", "message", "text", "input", "prompt", "messages"],
            }
        )

    def handle_rizon_custom_agent_post(self, parsed) -> None:
        if not self.custom_agent_authorized(parsed):
            self.send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        query = parse_qs(parsed.query)
        try:
            payload = self.read_json()
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return
        text = extract_custom_agent_text(payload, query)
        user_id = extract_custom_agent_user_id(payload, query)
        self.send_custom_agent_reply(text, user_id)

    def handle_rokid_plugin_get(self, parsed) -> None:
        query = parse_qs(parsed.query)
        text = (query.get("query") or query.get("q") or [None])[0]
        user_id = (query.get("user_id") or [DEFAULT_MCP_USER_ID])[0]
        self.send_rokid_plugin_reply(text, user_id)

    def handle_rokid_plugin_post(self) -> None:
        try:
            payload = self.read_json()
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return
        text = payload.get("query") or payload.get("q") or payload.get("message") or payload.get("text")
        user_id = payload.get("user_id") or DEFAULT_MCP_USER_ID
        self.send_rokid_plugin_reply(text, user_id)

    def send_rokid_plugin_reply(self, text: object, user_id: object) -> None:
        query = clean_text(text)
        if not query:
            self.send_json({"ok": False, "error": "query 不能为空。"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = handle_chat({"user_id": clean_text(user_id) or DEFAULT_MCP_USER_ID, "message": query})
            self.send_json(
                {
                    "ok": True,
                    "answer": result.get("reply") or "",
                    "text": result.get("reply") or "",
                    "engine": result.get("engine") or "",
                }
            )
        except Exception as exc:
            self.send_json(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def static_file_exists(self, request_path: str) -> bool:
        if request_path in ("", "/"):
            return True
        if request_path == "/demo/register":
            return (STATIC_DIR / "demo-register.html").is_file()
        if request_path.startswith("/static/"):
            relative = request_path.removeprefix("/static/")
        else:
            relative = request_path.removeprefix("/")
        path = (STATIC_DIR / relative).resolve()
        return str(path).startswith(str(STATIC_DIR.resolve())) and path.is_file()

    def serve_static(self, request_path: str) -> None:
        if request_path in ("", "/"):
            relative = "index.html"
        elif request_path == "/demo/register":
            relative = "demo-register.html"
        elif request_path.startswith("/static/"):
            relative = request_path.removeprefix("/static/")
        else:
            relative = request_path.removeprefix("/")

        path = (STATIC_DIR / relative).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        else:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def run() -> None:
    init_db()
    init_tools_fixture()
    decision_bridge.start()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Campus Jarvis user settings page: http://{host}:{port}")
    print(f"SQLite database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        decision_bridge.close()
        server.server_close()


if __name__ == "__main__":
    run()
