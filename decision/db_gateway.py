from __future__ import annotations

import asyncio
import importlib.util
import threading
import time
from pathlib import Path
from typing import Any

from .config import DecisionConfig
from .models import EventRecord, ToolRecord


class DecisionDBGateway:
    USER_CACHE_TTL_SECONDS = 60.0

    def __init__(self, config: DecisionConfig):
        self.config = config
        self._db_cls = _load_db_class(Path(config.db_helper_path))
        self._cache_lock = threading.Lock()
        self._tools_cache: list[ToolRecord] | None = None
        self._user_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_user_sync, user_id)

    async def get_context(self, user_id: str) -> list[dict]:
        return await asyncio.to_thread(self._get_context_sync, user_id)

    async def save_context(self, user_id: str, context: list[dict]) -> None:
        await asyncio.to_thread(self._save_context_sync, user_id, context)

    async def get_tools(self) -> list[ToolRecord]:
        return await asyncio.to_thread(self._get_tools_sync)

    async def list_candidate_events(self, filters: dict[str, Any] | None = None) -> list[EventRecord]:
        return await asyncio.to_thread(self._list_candidate_events_sync, filters or {})

    async def get_events_by_ids(self, ids: list[int]) -> list[EventRecord]:
        return await asyncio.to_thread(self._get_events_by_ids_sync, ids)

    def _get_user_sync(self, user_id: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._user_cache.get(user_id)
            if cached is not None and cached[0] > now:
                return cached[1]
        with self._db_cls(self.config.db_path) as db:
            user = db.get_user(user_id)
        with self._cache_lock:
            self._user_cache[user_id] = (now + self.USER_CACHE_TTL_SECONDS, user)
        return user

    def _get_context_sync(self, user_id: str) -> list[dict]:
        with self._db_cls(self.config.db_path) as db:
            context = db.get_user_context(user_id)
        return context if isinstance(context, list) else []

    def _save_context_sync(self, user_id: str, context: list[dict]) -> None:
        with self._db_cls(self.config.db_path) as db:
            db.upsert_user_context(user_id, context)

    def _get_tools_sync(self) -> list[ToolRecord]:
        with self._cache_lock:
            if self._tools_cache is not None:
                return list(self._tools_cache)
        with self._db_cls(self.config.db_path) as db:
            rows = db.fetch_all("tools_table", order_by="name ASC")
        tools = [
            ToolRecord(
                name=str(row.get("name") or ""),
                website=str(row.get("website") or ""),
                description=str(row.get("description") or ""),
            )
            for row in rows
            if row.get("name") and row.get("website")
        ]
        with self._cache_lock:
            self._tools_cache = list(tools)
        return tools

    def _list_candidate_events_sync(self, filters: dict[str, Any]) -> list[EventRecord]:
        clauses = ["embedded_summary IS NOT NULL", "summary IS NOT NULL", "TRIM(summary) != ''"]
        params: list[Any] = []

        topics = [str(item) for item in filters.get("topics", []) if str(item).strip()]
        campus = [str(item) for item in filters.get("campus", []) if str(item).strip()]
        target_grade = [int(item) for item in filters.get("target_grade", []) if str(item).strip()]

        if topics:
            placeholders = ", ".join(["?"] * len(topics))
            clauses.append(
                f"EXISTS (SELECT 1 FROM json_each(COALESCE(topics, '[]')) WHERE value IN ({placeholders}))"
            )
            params.extend(topics)
        if campus:
            placeholders = ", ".join(["?"] * len(campus))
            clauses.append(
                f"EXISTS (SELECT 1 FROM json_each(COALESCE(campus, '[]')) WHERE value IN ({placeholders}))"
            )
            params.extend(campus)
        if target_grade:
            placeholders = ", ".join(["?"] * len(target_grade))
            clauses.append(
                f"EXISTS (SELECT 1 FROM json_each(COALESCE(target_grade, '[]')) WHERE CAST(value AS INTEGER) IN ({placeholders}))"
            )
            params.extend(target_grade)

        where = " AND ".join(clauses)
        columns = [
            "id",
            "title",
            "summary",
            "website",
            "regis_end_time",
            "activity_start_time",
            "campus",
            "topics",
            "target_grade",
            "embedded_summary",
            "cleaned_document",
        ]
        with self._db_cls(self.config.db_path) as db:
            rows = db.fetch_all(
                "school_event_table",
                where,
                params,
                columns=columns,
                order_by="updated_at DESC",
            )
        return [self._row_to_event(row) for row in rows]

    def _get_events_by_ids_sync(self, ids: list[int]) -> list[EventRecord]:
        normalized_ids = [int(item) for item in ids]
        if not normalized_ids:
            return []
        with self._db_cls(self.config.db_path) as db:
            rows = db.fetch_all(
                "school_event_table",
                {"id": normalized_ids},
                columns=[
                    "id",
                    "title",
                    "summary",
                    "website",
                    "regis_end_time",
                    "activity_start_time",
                    "campus",
                    "topics",
                    "target_grade",
                    "embedded_summary",
                    "cleaned_document",
                ],
            )
        by_id = {int(row["id"]): self._row_to_event(row) for row in rows}
        return [by_id[event_id] for event_id in normalized_ids if event_id in by_id]

    def _row_to_event(self, row: dict[str, Any]) -> EventRecord:
        return EventRecord(
            id=int(row["id"]),
            title=str(row.get("title") or ""),
            summary=str(row.get("summary") or ""),
            website=str(row.get("website") or ""),
            regis_end_time=row.get("regis_end_time"),
            activity_start_time=row.get("activity_start_time"),
            campus=list(row.get("campus") or []),
            topics=list(row.get("topics") or []),
            target_grade=[int(item) for item in (row.get("target_grade") or [])],
            embedded_summary=row.get("embedded_summary"),
            cleaned_document=row.get("cleaned_document"),
        )


def _load_db_class(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"DB helper not found: {path}")
    spec = importlib.util.spec_from_file_location("decision_seu_campus_db_v2", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load DB helper from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db_cls = getattr(module, "SEUCampusDB", None)
    if db_cls is None:
        raise AttributeError(f"`SEUCampusDB` not found in {path}")
    return db_cls
