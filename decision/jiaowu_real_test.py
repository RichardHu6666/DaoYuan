from __future__ import annotations

import asyncio
import contextlib
import json
import math
import shutil
import sqlite3
import struct
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .client_manager import ClientManager
from .config import DecisionConfig, load_config

DEFAULT_SOURCE_DB = "/root/rivermind-data/database/jiaowu.db"
DEFAULT_TARGET_DB = "/root/rivermind-data/database/jiaowu_decision_test.db"
DEFAULT_REPORT_DIR = "/root/decision/reports"
DEFAULT_JW_URL = "https://jw.seu.edu.cn"
DEFAULT_LIBRARY_URL = "https://lib.seu.edu.cn"
DEFAULT_CALENDAR_URL = "https://jwc.seu.edu.cn"
DEFAULT_EMBED_BATCH_SIZE = 32


def build_jiaowu_test_config(
    *,
    base_config: DecisionConfig | None = None,
    db_path: str = DEFAULT_TARGET_DB,
    db_helper_path: str | None = None,
) -> DecisionConfig:
    base = base_config or load_config()
    helper_path = db_helper_path or base.db_helper_path
    embedding_model = base.embedding_model if base.embedding_backend == "openai" else "text-embedding-3-small"
    return replace(
        base,
        db_path=db_path,
        db_helper_path=helper_path,
        embedding_backend="openai",
        embedding_model=embedding_model,
        embedding_dimensions=1024,
    )


def prepare_jiaowu_test_db(
    *,
    config: DecisionConfig | None = None,
    source_db: str = DEFAULT_SOURCE_DB,
    target_db: str = DEFAULT_TARGET_DB,
    force_rebuild_embeddings: bool = False,
    batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
) -> dict[str, Any]:
    cfg = build_jiaowu_test_config(base_config=config, db_path=target_db)
    source_path = Path(source_db)
    target_path = Path(target_db)
    if not source_path.exists():
        raise FileNotFoundError(f"Source DB not found: {source_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)

    with contextlib.closing(sqlite3.connect(target_path)) as conn:
        conn.row_factory = sqlite3.Row
        _seed_test_fixtures(conn)
        embedding_stats = _populate_embeddings(
            conn,
            cfg,
            force_rebuild_embeddings=force_rebuild_embeddings,
            batch_size=batch_size,
        )
        summary = _collect_db_summary(conn)

    return {
        "source_db": str(source_path),
        "target_db": str(target_path),
        "force_rebuild_embeddings": force_rebuild_embeddings,
        "embedding_backend": cfg.embedding_backend,
        "embedding_model": cfg.embedding_model,
        "embedding_dimensions": cfg.embedding_dimensions,
        "embedding_stats": embedding_stats,
        "db_summary": summary,
    }


def backfill_embeddings_in_db(
    *,
    config: DecisionConfig | None = None,
    db_path: str,
    force_rebuild_embeddings: bool = False,
    batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
) -> dict[str, Any]:
    cfg = config or load_config()
    target_path = Path(db_path)
    if not target_path.exists():
        raise FileNotFoundError(f"Target DB not found: {target_path}")

    runtime_cfg = replace(cfg, db_path=str(target_path))
    with contextlib.closing(sqlite3.connect(target_path)) as conn:
        conn.row_factory = sqlite3.Row
        embedding_stats = _populate_embeddings(
            conn,
            runtime_cfg,
            force_rebuild_embeddings=force_rebuild_embeddings,
            batch_size=batch_size,
        )
        summary = _collect_db_summary(conn)

    return {
        "db_path": str(target_path),
        "force_rebuild_embeddings": force_rebuild_embeddings,
        "embedding_backend": runtime_cfg.embedding_backend,
        "embedding_model": runtime_cfg.embedding_model,
        "embedding_dimensions": runtime_cfg.embedding_dimensions,
        "embedding_stats": embedding_stats,
        "db_summary": summary,
    }


async def run_jiaowu_t2t_suite(
    *,
    config: DecisionConfig | None = None,
    source_db: str = DEFAULT_SOURCE_DB,
    target_db: str = DEFAULT_TARGET_DB,
    report_dir: str = DEFAULT_REPORT_DIR,
    force_rebuild_embeddings: bool = False,
) -> dict[str, Any]:
    cfg = build_jiaowu_test_config(base_config=config, db_path=target_db)
    preparation: dict[str, Any] | None = None
    scenario_results: list[dict[str, Any]] = []
    manager_observations: dict[str, Any] = {}
    fatal_error: dict[str, Any] | None = None

    try:
        preparation = prepare_jiaowu_test_db(
            config=cfg,
            source_db=source_db,
            target_db=target_db,
            force_rebuild_embeddings=force_rebuild_embeddings,
        )
    except Exception as exc:
        fatal_error = _fatal_error("test-db preparation", exc)
    else:
        manager = ClientManager(config=cfg)
        try:
            first_client = await manager.get_client("test_user_full")
            same_client = await manager.get_client("test_user_full")
            manager_observations["same_user_session_reused"] = first_client is same_client
            scenario_results.append(await _run_tool_direct_scenario(manager))
            scenario_results.append(await _run_lecture_rag_scenario(manager))
            scenario_results.append(await _run_competition_rag_scenario(manager))
            scenario_results.append(await _run_sparse_profile_scenario(manager))
            scenario_results.append(await _run_multi_turn_context_scenario(manager))
            scenario_results.append(await _run_same_user_concurrency_scenario(manager))
            isolation_result, isolation_observations = await _run_multi_user_isolation_scenario(manager)
            scenario_results.append(isolation_result)
            manager_observations.update(isolation_observations)
            reload_result, reload_observations = await _run_release_and_reload_scenario(manager)
            scenario_results.append(reload_result)
            manager_observations.update(reload_observations)
        except Exception as exc:
            fatal_error = _fatal_error("client manager lifecycle", exc)
        finally:
            await manager.close()

    report = _build_suite_report(
        config=cfg,
        source_db=source_db,
        target_db=target_db,
        preparation=preparation,
        scenario_results=scenario_results,
        manager_observations=manager_observations,
        fatal_error=fatal_error,
    )
    return _write_suite_report(report, report_dir)


def _build_suite_report(
    *,
    config: DecisionConfig,
    source_db: str,
    target_db: str,
    preparation: dict[str, Any] | None,
    scenario_results: list[dict[str, Any]],
    manager_observations: dict[str, Any],
    fatal_error: dict[str, Any] | None,
) -> dict[str, Any]:
    prepared_summary = preparation["db_summary"] if preparation else None
    embedding_stats = preparation["embedding_stats"] if preparation else None
    summary = {
        "tool_direct_ok": _scenario_ok(scenario_results, "tool_direct"),
        "rag_ok": _scenario_ok(scenario_results, "lecture_rag") and _scenario_ok(scenario_results, "competition_rag"),
        "missing_profile_ok": _scenario_ok(scenario_results, "missing_profile"),
        "context_lifecycle_ok": _scenario_ok(scenario_results, "multi_turn_context")
        and _scenario_ok(scenario_results, "release_and_reload"),
        "client_manager_reuse_ok": bool(manager_observations.get("same_user_session_reused")),
        "client_manager_reload_ok": bool(manager_observations.get("reload_session_recreated")),
        "different_users_isolated_ok": bool(manager_observations.get("different_users_isolated")),
        "all_passed": bool(scenario_results) and all(item["passed"] for item in scenario_results) and fatal_error is None,
    }
    if fatal_error is not None:
        summary["fatal_failure_layer"] = fatal_error["failure_layer"]

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "environment": {
            "source_db": source_db,
            "target_db": target_db,
            "db_helper_path": config.db_helper_path,
            "llm_base_url": config.llm_base_url,
            "llm1_model": config.llm1_model,
            "llm2_model": config.llm2_model,
            "llm_api_key_configured": bool(config.llm_api_key),
            "embedding_backend": config.embedding_backend,
            "embedding_model": config.embedding_model,
            "embedding_dimensions": config.embedding_dimensions,
            "embedding_base_url": config.embedding_base_url,
            "embedding_api_key_configured": bool(config.embedding_api_key),
            "prepared_db_summary": prepared_summary,
            "embedding_stats": embedding_stats,
            "fixture_note": "school_event_table 来源于真实 jiaowu.db；tools/users/context/embedding 为测试夹具或测试期补齐。",
            "source_db_mode": "read-only source",
        },
        "scenarios": scenario_results,
        "summary": summary,
        "manager_observations": manager_observations,
    }
    if preparation is not None:
        report["preparation"] = preparation
    if fatal_error is not None:
        report["fatal_error"] = fatal_error
    return report


def _write_suite_report(report: dict[str, Any], report_dir: str) -> dict[str, Any]:
    report_dir_path = Path(report_dir)
    report_dir_path.mkdir(parents=True, exist_ok=True)
    json_path = report_dir_path / "jiaowu_t2t_report.json"
    md_path = report_dir_path / "jiaowu_t2t_report.md"
    report["report_paths"] = {
        "json": str(json_path),
        "markdown": str(md_path),
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_build_markdown_report(report), encoding="utf-8")
    return report


def _fatal_error(failure_layer: str, exc: Exception) -> dict[str, Any]:
    return {
        "failure_layer": failure_layer,
        "error": f"{type(exc).__name__}: {exc}",
    }


def _seed_test_fixtures(conn: sqlite3.Connection) -> None:
    tool_rows = [
        ("教务系统", DEFAULT_JW_URL, "成绩、课表与教务入口"),
        ("图书馆", DEFAULT_LIBRARY_URL, "图书馆馆藏与借阅入口"),
        ("校历", DEFAULT_CALENDAR_URL, "校历与学期安排入口"),
    ]
    conn.executemany(
        """
        INSERT INTO tools_table (name, website, description)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            website=excluded.website,
            description=excluded.description
        """,
        tool_rows,
    )

    user_rows = [
        (
            "test_user_full",
            "测试满画像用户",
            "计算机科学与工程学院",
            "计算机科学与技术",
            2024,
            "本",
            json.dumps(["讲座", "AI", "竞赛"], ensure_ascii=False),
            "偏好AI讲座与竞赛通知",
        ),
        (
            "test_user_sparse",
            "测试缺画像用户",
            None,
            None,
            None,
            None,
            json.dumps([], ensure_ascii=False),
            None,
        ),
    ]
    conn.executemany(
        """
        INSERT INTO users_table (
            uuid, nickname, school, major, enrollment_year, student_level, interest, profile
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uuid) DO UPDATE SET
            nickname=excluded.nickname,
            school=excluded.school,
            major=excluded.major,
            enrollment_year=excluded.enrollment_year,
            student_level=excluded.student_level,
            interest=excluded.interest,
            profile=excluded.profile
        """,
        user_rows,
    )

    context_rows = [
        ("test_user_full", json.dumps([], ensure_ascii=False)),
        ("test_user_sparse", json.dumps([], ensure_ascii=False)),
    ]
    conn.executemany(
        """
        INSERT INTO context_table (user_id, context)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            context=excluded.context
        """,
        context_rows,
    )
    conn.commit()


def _populate_embeddings(
    conn: sqlite3.Connection,
    config: DecisionConfig,
    *,
    force_rebuild_embeddings: bool,
    batch_size: int,
) -> dict[str, Any]:
    if config.embedding_backend.strip().lower() != "openai":
        raise RuntimeError("jiaowu real-data preparation currently requires DECISION_EMBEDDING_BACKEND=openai.")
    if not config.embedding_api_key:
        raise RuntimeError("Missing embedding API key for jiaowu real-data preparation.")

    if force_rebuild_embeddings:
        rows = conn.execute(
            """
            SELECT id, summary
            FROM school_event_table
            WHERE summary IS NOT NULL AND TRIM(summary) != ''
            ORDER BY id ASC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, summary
            FROM school_event_table
            WHERE summary IS NOT NULL
              AND TRIM(summary) != ''
              AND embedded_summary IS NULL
            ORDER BY id ASC
            """
        ).fetchall()

    prepared = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        vectors = _embed_batch(config, [str(row["summary"]) for row in chunk])
        prepared += len(chunk)
        for row, vector in zip(chunk, vectors):
            conn.execute(
                """
                UPDATE school_event_table
                SET embedded_summary = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    _vector_to_blob(vector),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    int(row["id"]),
                ),
            )
        conn.commit()

    total_with_embedding = conn.execute(
        "SELECT COUNT(*) FROM school_event_table WHERE embedded_summary IS NOT NULL"
    ).fetchone()[0]
    total_events = conn.execute("SELECT COUNT(*) FROM school_event_table").fetchone()[0]
    return {
        "rows_selected": len(rows),
        "rows_prepared": prepared,
        "total_with_embedding": int(total_with_embedding),
        "total_events": int(total_events),
    }


def _embed_batch(config: DecisionConfig, texts: list[str]) -> list[list[float]]:
    with httpx.Client(timeout=config.request_timeout_seconds) as client:
        response = client.post(
            f"{config.embedding_base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {config.embedding_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.embedding_model,
                "input": texts,
                "dimensions": config.embedding_dimensions,
            },
        )
        response.raise_for_status()
        payload = response.json()

    data = payload.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise RuntimeError("Embedding API returned an unexpected payload length.")

    vectors: list[list[float]] = []
    for item in data:
        vector = item.get("embedding")
        if not isinstance(vector, list):
            raise RuntimeError("Embedding API returned a non-list vector.")
        vectors.append(_normalize_vector([float(value) for value in vector]))
    return vectors


def _normalize_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]


def _vector_to_blob(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _collect_db_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = {}
    for table in ("school_event_table", "tools_table", "users_table", "context_table"):
        counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    counts["event_with_embedding"] = int(
        conn.execute("SELECT COUNT(*) FROM school_event_table WHERE embedded_summary IS NOT NULL").fetchone()[0]
    )
    return counts


async def _run_tool_direct_scenario(manager: ClientManager) -> dict[str, Any]:
    return await _run_single_result_scenario(
        manager=manager,
        scenario_name="tool_direct",
        user_id="test_user_full",
        instruct="查成绩",
        evaluator=_evaluate_tool_direct_result,
    )


async def _run_lecture_rag_scenario(manager: ClientManager) -> dict[str, Any]:
    return await _run_single_result_scenario(
        manager=manager,
        scenario_name="lecture_rag",
        user_id="test_user_full",
        instruct="最近有什么讲座推荐？",
        evaluator=lambda result: _evaluate_rag_result(result, expected_keywords=["讲座"]),
    )


async def _run_competition_rag_scenario(manager: ClientManager) -> dict[str, Any]:
    return await _run_single_result_scenario(
        manager=manager,
        scenario_name="competition_rag",
        user_id="test_user_full",
        instruct="最近有哪些竞赛或比赛通知？",
        evaluator=lambda result: _evaluate_rag_result(result, expected_keywords=["竞赛", "比赛"]),
    )


async def _run_sparse_profile_scenario(manager: ClientManager) -> dict[str, Any]:
    return await _run_single_result_scenario(
        manager=manager,
        scenario_name="missing_profile",
        user_id="test_user_sparse",
        instruct="适合我的活动有哪些？",
        evaluator=lambda result: _evaluate_rag_result(result, require_missing_profile=True),
    )


async def _run_multi_turn_context_scenario(manager: ClientManager) -> dict[str, Any]:
    scenario = {
        "name": "multi_turn_context",
        "user_id": "test_user_full",
        "steps": [],
        "passed": False,
        "failure_layer": None,
        "error": None,
    }
    try:
        client = await manager.get_client("test_user_full")
        first = await client.respond_result("最近有什么讲座推荐？")
        second = await client.respond_result("报名截止时间呢？")
        scenario["steps"] = [_decision_result_dict(first), _decision_result_dict(second)]
        first_ok, first_failure_layer = _evaluate_rag_result(first, expected_keywords=["讲座"])
        if not first_ok:
            scenario["failure_layer"] = first_failure_layer
        else:
            second_ok, second_failure_layer = _evaluate_follow_up_result(second)
            scenario["passed"] = first_ok and second_ok
            if not second_ok:
                scenario["failure_layer"] = second_failure_layer
    except Exception as exc:
        scenario["error"] = f"{type(exc).__name__}: {exc}"
        scenario["failure_layer"] = "client session lifecycle"
    return scenario


async def _run_same_user_concurrency_scenario(manager: ClientManager) -> dict[str, Any]:
    scenario = {
        "name": "same_user_concurrency",
        "user_id": "test_user_full",
        "steps": [],
        "passed": False,
        "failure_layer": None,
        "error": None,
    }
    try:
        client = await manager.get_client("test_user_full")
        before_context_len = len(client.context)
        first, second = await asyncio.gather(
            client.respond_result("最近有什么讲座推荐？"),
            client.respond_result("最近有哪些竞赛通知？"),
        )
        after_context_len = len(client.context)
        scenario["steps"] = [_decision_result_dict(first), _decision_result_dict(second)]
        scenario["client_observations"] = {
            "before_context_len": before_context_len,
            "after_context_len": after_context_len,
        }
        first_ok, first_failure_layer = _evaluate_rag_result(first, expected_keywords=["讲座"])
        second_ok, second_failure_layer = _evaluate_rag_result(second, expected_keywords=["竞赛", "比赛"])
        if not first_ok:
            scenario["failure_layer"] = first_failure_layer
        elif not second_ok:
            scenario["failure_layer"] = second_failure_layer
        else:
            scenario["passed"] = after_context_len >= before_context_len + 4
            if not scenario["passed"]:
                scenario["failure_layer"] = "client session lifecycle"
    except Exception as exc:
        scenario["error"] = f"{type(exc).__name__}: {exc}"
        scenario["failure_layer"] = "client session lifecycle"
    return scenario


async def _run_multi_user_isolation_scenario(manager: ClientManager) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = {
        "name": "multi_user_isolation",
        "user_ids": ["test_user_full", "test_user_sparse"],
        "steps": [],
        "passed": False,
        "failure_layer": None,
        "error": None,
    }
    observations = {}
    try:
        full_client = await manager.get_client("test_user_full")
        sparse_client = await manager.get_client("test_user_sparse")
        observations["different_users_isolated"] = full_client is not sparse_client

        full_result, sparse_result = await asyncio.gather(
            full_client.respond_result("最近有什么讲座推荐？"),
            sparse_client.respond_result("适合我的活动有哪些？"),
        )
        scenario["steps"] = [_decision_result_dict(full_result), _decision_result_dict(sparse_result)]
        full_ok, full_failure_layer = _evaluate_rag_result(full_result, expected_keywords=["讲座"])
        sparse_ok, sparse_failure_layer = _evaluate_rag_result(sparse_result, require_missing_profile=True)
        if not full_ok:
            scenario["failure_layer"] = full_failure_layer
        elif not sparse_ok:
            scenario["failure_layer"] = sparse_failure_layer
        else:
            scenario["passed"] = observations["different_users_isolated"] and not full_result.missing_profile_fields
            if not scenario["passed"]:
                scenario["failure_layer"] = "client manager lifecycle"
    except Exception as exc:
        scenario["error"] = f"{type(exc).__name__}: {exc}"
        scenario["failure_layer"] = "client manager lifecycle"
    return scenario, observations


async def _run_release_and_reload_scenario(manager: ClientManager) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = {
        "name": "release_and_reload",
        "user_id": "test_user_full",
        "steps": [],
        "passed": False,
        "failure_layer": None,
        "error": None,
    }
    observations = {}
    try:
        client = await manager.get_client("test_user_full")
        initial = await client.respond_result("最近有什么讲座推荐？")
        client.last_time = time.monotonic() - (manager.config.idle_ttl_seconds + 5)
        await manager.release_idle_clients()
        observations["session_released"] = "test_user_full" not in manager.sessions
        flushed_context = await manager.gateway.get_context("test_user_full")
        observations["flushed_context_len"] = len(flushed_context or [])

        reloaded_client = await manager.get_client("test_user_full")
        observations["reload_session_recreated"] = reloaded_client is not client
        follow_up = await reloaded_client.respond_result("那报名截止时间呢？")
        scenario["steps"] = [_decision_result_dict(initial), _decision_result_dict(follow_up)]
        initial_ok, initial_failure_layer = _evaluate_rag_result(initial, expected_keywords=["讲座"])
        follow_up_ok, follow_up_failure_layer = _evaluate_follow_up_result(follow_up)
        if not initial_ok:
            scenario["failure_layer"] = initial_failure_layer
        elif not follow_up_ok:
            scenario["failure_layer"] = follow_up_failure_layer
        else:
            scenario["passed"] = (
                observations["session_released"]
                and observations["flushed_context_len"] > 0
                and observations["reload_session_recreated"]
            )
            if not scenario["passed"]:
                scenario["failure_layer"] = "client manager lifecycle"
    except Exception as exc:
        scenario["error"] = f"{type(exc).__name__}: {exc}"
        scenario["failure_layer"] = "client manager lifecycle"
    return scenario, observations


async def _run_single_result_scenario(
    *,
    manager: ClientManager,
    scenario_name: str,
    user_id: str,
    instruct: str,
    evaluator,
) -> dict[str, Any]:
    scenario = {
        "name": scenario_name,
        "user_id": user_id,
        "instruct": instruct,
        "steps": [],
        "passed": False,
        "failure_layer": None,
        "error": None,
    }
    try:
        client = await manager.get_client(user_id)
        result = await client.respond_result(instruct)
        scenario["steps"] = [_decision_result_dict(result)]
        scenario["passed"], scenario["failure_layer"] = evaluator(result)
    except Exception as exc:
        scenario["error"] = f"{type(exc).__name__}: {exc}"
        scenario["failure_layer"] = "client session lifecycle"
    return scenario


def _evaluate_tool_direct_result(result) -> tuple[bool, str | None]:
    if result.route != "tool_direct":
        return False, "tool routing"
    if DEFAULT_JW_URL not in result.response_text:
        return False, "tool routing"
    if result.trace.get("retrieved_topk"):
        return False, "tool routing"
    return True, None


def _evaluate_rag_result(
    result,
    *,
    expected_keywords: list[str] | None = None,
    require_missing_profile: bool = False,
) -> tuple[bool, str | None]:
    if result.route != "rag":
        return False, "llm1 route"
    if bool(result.trace.get("llm1_fallback")):
        return False, "llm1 route"
    if require_missing_profile and not result.missing_profile_fields:
        return False, "llm1 route"
    if not result.retrieved_event_ids:
        return False, "vector retrieval"
    if expected_keywords:
        titles = [str(item.get("title") or "") for item in result.trace.get("retrieved_topk", [])]
        if not any(any(keyword in title for keyword in expected_keywords) for title in titles):
            return False, "vector retrieval"
    if bool(result.trace.get("llm2_fallback")) or not result.response_text.strip():
        return False, "llm2 generation"
    return True, None


def _evaluate_follow_up_result(result) -> tuple[bool, str | None]:
    base_ok, failure_layer = _evaluate_rag_result(result)
    if not base_ok:
        return base_ok, failure_layer
    if int(result.trace.get("used_context_message_count") or 0) <= 0:
        return False, "client session lifecycle"
    return True, None


def _decision_result_dict(result) -> dict[str, Any]:
    return {
        "response_text": result.response_text,
        "route": result.route,
        "tool_name": getattr(result, "tool_name", None),
        "tool_url": getattr(result, "tool_url", None),
        "rewritten_query": getattr(result, "rewritten_query", None),
        "retrieved_event_ids": list(getattr(result, "retrieved_event_ids", []) or []),
        "missing_profile_fields": list(getattr(result, "missing_profile_fields", []) or []),
        "trace": dict(getattr(result, "trace", {}) or {}),
    }


def _scenario_ok(scenarios: list[dict[str, Any]], name: str) -> bool:
    for item in scenarios:
        if item.get("name") == name:
            return bool(item.get("passed"))
    return False


def _build_markdown_report(report: dict[str, Any]) -> str:
    env = report["environment"]
    prepared_summary = env.get("prepared_db_summary") or {}
    lines = [
        "# jiaowu.db T2T 决策测试报告",
        "",
        "## 环境摘要",
        "",
        f"- 生成时间：`{report.get('generated_at')}`",
        f"- 原始库：`{env['source_db']}`",
        f"- 测试库：`{env['target_db']}`",
        f"- 原始库模式：`{env['source_db_mode']}`",
        f"- LLM1：`{env['llm1_model']}`",
        f"- LLM2：`{env['llm2_model']}`",
        f"- LLM API Key 已配置：`{env['llm_api_key_configured']}`",
        f"- Embedding：`{env['embedding_model']}` (`{env['embedding_dimensions']}` 维)",
        f"- Embedding API Key 已配置：`{env['embedding_api_key_configured']}`",
        f"- 事件总数：`{prepared_summary.get('school_event_table')}`",
        f"- 已有 embedding：`{prepared_summary.get('event_with_embedding')}`",
        f"- tools/users/context 夹具：`{prepared_summary.get('tools_table')}` / `{prepared_summary.get('users_table')}` / `{prepared_summary.get('context_table')}`",
        f"- 说明：{env['fixture_note']}",
        "",
    ]

    if report.get("fatal_error"):
        lines.extend(
            [
                "## 致命失败",
                "",
                f"- failure_layer：`{report['fatal_error']['failure_layer']}`",
                f"- error：`{report['fatal_error']['error']}`",
                "",
            ]
        )

    lines.extend(
        [
            "## 场景结果",
            "",
        ]
    )

    for scenario in report["scenarios"]:
        lines.append(f"### {scenario['name']}")
        lines.append("")
        lines.append(f"- 通过：`{scenario['passed']}`")
        if scenario.get("user_id"):
            lines.append(f"- user_id：`{scenario['user_id']}`")
        if scenario.get("user_ids"):
            lines.append(f"- user_ids：`{', '.join(scenario['user_ids'])}`")
        if scenario.get("instruct"):
            lines.append(f"- instruct：`{scenario['instruct']}`")
        if scenario.get("failure_layer"):
            lines.append(f"- failure_layer：`{scenario['failure_layer']}`")
        if scenario.get("error"):
            lines.append(f"- error：`{scenario['error']}`")
        if scenario.get("client_observations"):
            lines.append(f"- client_observations：`{json.dumps(scenario['client_observations'], ensure_ascii=False)}`")
        lines.append("")
        for index, step in enumerate(scenario.get("steps", []), start=1):
            lines.append(f"- step {index} route：`{step['route']}`")
            lines.append(f"- step {index} rewritten_query：`{step['rewritten_query']}`")
            lines.append(f"- step {index} missing_profile_fields：`{step['missing_profile_fields']}`")
            lines.append(f"- step {index} retrieved_event_ids：`{step['retrieved_event_ids']}`")
            lines.append(f"- step {index} retrieved_topk：`{json.dumps(step['trace'].get('retrieved_topk', []), ensure_ascii=False)}`")
            lines.append(f"- step {index} response：{step['response_text']}")
        lines.append("")

    lines.extend(
        [
            "## 总结",
            "",
            f"- 工具直达可用：`{report['summary']['tool_direct_ok']}`",
            f"- RAG 可用：`{report['summary']['rag_ok']}`",
            f"- 缺画像兜底可用：`{report['summary']['missing_profile_ok']}`",
            f"- context 生命周期可用：`{report['summary']['context_lifecycle_ok']}`",
            f"- ClientManager 复用可用：`{report['summary']['client_manager_reuse_ok']}`",
            f"- ClientManager 重载可用：`{report['summary']['client_manager_reload_ok']}`",
            f"- 不同用户隔离可用：`{report['summary']['different_users_isolated_ok']}`",
            f"- 全部通过：`{report['summary']['all_passed']}`",
            "",
            "## 报告路径",
            "",
            f"- JSON：`{report['report_paths']['json']}`",
            f"- Markdown：`{report['report_paths']['markdown']}`",
        ]
    )
    return "\n".join(lines) + "\n"
