from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_DIR / "seu_campus_assistant.db"
CORE_TABLES = [
    "users_table",
    "plan_table",
    "notification_table",
    "context_table",
]


def print_check(ok: bool, title: str, detail: str = "") -> bool:
    prefix = "PASS" if ok else "FAIL"
    print(f"[{prefix}] {title}" + (f" - {detail}" if detail else ""))
    return ok


def request_json(base_url: str, path: str, payload: dict | None = None) -> dict:
    url = base_url.rstrip("/") + path
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    with urlopen(request, timeout=8) as response:
        body = response.read().decode("utf-8")
        return json.loads(body or "{}")


def user_bundle_path(user_id: str) -> str:
    return "/api/user/bootstrap?" + urlencode({"user_id": user_id})


def check_http(base_url: str, user_id: str) -> bool:
    other_user_id = f"{user_id}-other"
    ok = True
    try:
        with urlopen(base_url.rstrip("/") + f"/?{urlencode({'user_id': user_id})}", timeout=8) as response:
            ok &= print_check(response.status == 200, "带 user_id 的首页可访问", f"HTTP {response.status}")
    except (HTTPError, URLError, TimeoutError) as exc:
        return print_check(False, "带 user_id 的首页可访问", str(exc))

    try:
        health = request_json(base_url, "/api/health")
        ok &= print_check(bool(health.get("ok")), "health 接口正常", f"schema={health.get('schema')}")
        tables = health.get("database", {}).get("tables", {})
        missing = [table for table in CORE_TABLES if not tables.get(table)]
        ok &= print_check(not missing, "health 核心表检查", f"missing={missing}" if missing else "核心表存在")
        ok &= print_check(
            "user_account_map" not in tables,
            "health 不再依赖账号映射表",
            "未暴露 user_account_map" if "user_account_map" not in tables else "仍包含 user_account_map",
        )
    except Exception as exc:
        ok &= print_check(False, "health 接口正常", str(exc))

    try:
        missing = request_json(base_url, "/api/user/bootstrap")
        ok &= print_check(not missing.get("ok"), "缺少 user_id 会被拒绝", str(missing.get("error") or ""))
    except HTTPError as exc:
        ok &= print_check(exc.code == 400, "缺少 user_id 会被拒绝", f"HTTP {exc.code}")
    except Exception as exc:
        ok &= print_check(False, "缺少 user_id 会被拒绝", str(exc))

    try:
        bundle = request_json(base_url, user_bundle_path(user_id))
        returned_user_id = bundle.get("user", {}).get("user_id")
        ok &= print_check(returned_user_id == user_id, "bootstrap 绑定指定 UUID", returned_user_id or "空")
    except Exception as exc:
        return ok & print_check(False, "bootstrap 绑定指定 UUID", str(exc))

    payload = {
        "user_id": user_id,
        "user": {"user_id": user_id, "nickname": "自检用户"},
        "profile": {
            "user_id": user_id,
            "school": "东南大学",
            "major": "软件工程",
            "interests": json.dumps(["自检"]),
            "goals": json.dumps(["验证 UUID 直连"]),
            "preferences": "{}",
        },
        "deadlines": [
            {
                "title": "UUID 直连自检",
                "deadline_time": "2026-06-10 20:00",
                "priority": 3,
                "status": "pending",
                "category": "self-check",
            }
        ],
        "courses": [
            {
                "course_name": "自检课程",
                "day_of_week": "1",
                "start_section": "1",
                "end_section": "2",
                "teacher": "系统",
                "location": "线上",
            }
        ],
        "push_settings": {
            "user_id": user_id,
            "content_preferences": json.dumps(
                [
                    {
                        "type": "custom",
                        "title": "自检推送",
                        "content": "验证 notification_table",
                        "frequency": "daily",
                        "times": ["08:30"],
                    }
                ],
                ensure_ascii=False,
            ),
        },
    }
    try:
        saved = request_json(base_url, "/api/user/save", payload)
        ok &= print_check(saved.get("user", {}).get("user_id") == user_id, "保存仍绑定同一 UUID")
        reloaded = request_json(base_url, user_bundle_path(user_id))
        ok &= print_check(reloaded.get("user", {}).get("nickname") == "自检用户", "重新读取可见已保存资料")
        isolated = request_json(base_url, user_bundle_path(other_user_id))
        ok &= print_check(isolated.get("user", {}).get("nickname") != "自检用户", "不同 UUID 不串数据")
    except Exception as exc:
        ok &= print_check(False, "保存和隔离验证", str(exc))
    return ok


def check_db(db_path: Path, user_id: str) -> bool:
    if not db_path.exists():
        return print_check(False, "SQLite 文件存在", str(db_path))

    ok = print_check(True, "SQLite 文件存在", str(db_path))
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        for table in CORE_TABLES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            ok &= print_check(bool(exists), f"表存在：{table}")

        row = conn.execute("SELECT uuid FROM users_table WHERE uuid=?", (user_id,)).fetchone()
        if row:
            ok &= print_check(True, f"自检 UUID 存在：{user_id}")
            for table in ["plan_table", "notification_table"]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (user_id,)).fetchone()[0]
                ok &= print_check(count > 0, f"{user_id} 在 {table} 有数据", str(count))
    except sqlite3.Error as exc:
        ok &= print_check(False, "SQLite 可查询", str(exc))
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Campus Jarvis UUID 直连网页自检")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="网页服务地址")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径")
    parser.add_argument("--user-id", default="self-check-user", help="用于自检的 UUID")
    parser.add_argument("--skip-http", action="store_true", help="只检查数据库")
    args = parser.parse_args()

    ok = check_db(Path(args.db), args.user_id)
    if not args.skip_http:
        ok = check_http(args.base_url, args.user_id) and ok
    print("\n结果：" + ("通过" if ok else "存在问题，请看 FAIL 项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
