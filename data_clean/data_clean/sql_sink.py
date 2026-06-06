from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from .document_normalizer import normalize_optional_storage_text
from .models import AppPaths, SchoolEventRecord, default_app_paths


class SqlSink:
    def __init__(self, paths: AppPaths | None = None, helper_path: str | Path | None = None):
        self.paths = paths or default_app_paths()
        self.paths.ensure()
        self.helper_path = Path(helper_path) if helper_path else self._default_helper_path()
        self._db = None
        self._db_cls = self._load_db_class()

    def __enter__(self) -> "SqlSink":
        self._db = self._db_cls(str(self.paths.main_db_path))
        self._ensure_schema_ready()
        conn = getattr(self._db, "conn", None)
        if conn is not None:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout = 30000;")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def write_event(self, record: SchoolEventRecord) -> int:
        return self.write_event_row(record.to_db_row())

    def upsert_event(self, record: SchoolEventRecord) -> int:
        record_id, _ = self.upsert_event_row_with_status(record.to_db_row())
        return record_id

    def write_event_row(self, row: dict[str, object]) -> int:
        db = self._require_db()
        return int(db.insert("school_event_table", self._normalize_event_row(row)))

    def upsert_event_row(self, row: dict[str, object]) -> int:
        record_id, _ = self.upsert_event_row_with_status(row)
        return record_id

    def upsert_event_row_with_status(self, row: dict[str, object]) -> tuple[int, str]:
        db = self._require_db()
        normalized_row = self._normalize_event_row(row)
        existing = self._find_existing_event(normalized_row)
        if existing is None:
            return int(db.insert("school_event_table", normalized_row)), "stored"
        db.update_by_pk("school_event_table", existing["id"], normalized_row)
        return int(existing["id"]), "updated_or_upserted"

    def _find_existing_event(self, row: dict[str, object]) -> dict | None:
        db = self._require_db()
        conn = getattr(db, "conn", None)
        if conn is None:
            return db.fetch_one(
                "school_event_table",
                {
                    "website": row.get("website"),
                    "title": row.get("title"),
                    "regis_start_time": row.get("regis_start_time"),
                    "regis_end_time": row.get("regis_end_time"),
                    "activity_start_time": row.get("activity_start_time"),
                },
                deserialize_json=False,
            )

        filters = {
            "website": row.get("website"),
            "title": row.get("title"),
            "regis_start_time": row.get("regis_start_time"),
            "regis_end_time": row.get("regis_end_time"),
            "activity_start_time": row.get("activity_start_time"),
        }
        clauses: list[str] = []
        params: list[object] = []
        for column, value in filters.items():
            if value is None:
                clauses.append(f"{column} IS NULL")
            else:
                clauses.append(f"{column} = ?")
                params.append(value)

        query = (
            "SELECT id, website, title, regis_start_time, regis_end_time, activity_start_time "
            "FROM school_event_table "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY id ASC LIMIT 1"
        )
        row = conn.execute(query, params).fetchone()
        return None if row is None else dict(row)

    def _require_db(self):
        if self._db is None:
            raise RuntimeError("SqlSink must be used as a context manager.")
        return self._db

    def _ensure_schema_ready(self) -> None:
        db = self._require_db()
        create_tables = getattr(db, "create_tables", None)
        create_indexes = getattr(db, "create_indexes", None)
        if callable(create_tables):
            create_tables()
        if callable(create_indexes):
            create_indexes()

    def _normalize_event_row(self, row: dict[str, object]) -> dict[str, object]:
        normalized = dict(row)
        normalized["website"] = _normalize_scalar_text(normalized.get("website"))
        normalized["title"] = _normalize_scalar_text(normalized.get("title"))
        normalized["cleaned_document"] = normalize_optional_storage_text(
            _coerce_text(normalized.get("cleaned_document"))
        )
        normalized["summary"] = normalize_optional_storage_text(_coerce_text(normalized.get("summary")))
        for field in ("regis_start_time", "regis_end_time", "activity_start_time"):
            normalized[field] = _normalize_scalar_text(normalized.get(field))
        for field in ("campus", "target_grade", "topics"):
            normalized[field] = _normalize_jsonish_field(normalized.get(field))
        return normalized

    def _default_helper_path(self) -> Path:
        module_repo_root = Path(__file__).resolve().parents[2]
        candidates = [
            self.paths.repo_root / "data" / "seu_campus_db_v2.py",
            self.paths.repo_root / "seu_campus_db_v2.py",
            module_repo_root / "data" / "seu_campus_db_v2.py",
            module_repo_root / "seu_campus_db_v2.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise FileNotFoundError("Unable to locate `seu_campus_db_v2.py`.")

    def _load_db_class(self):
        module = _load_module(self.helper_path)
        db_cls = getattr(module, "SEUCampusDB", None)
        if db_cls is None:
            raise AttributeError(f"`SEUCampusDB` not found in {self.helper_path}")
        return db_cls


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("seu_campus_db_v2_dynamic", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coerce_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _normalize_scalar_text(value: object) -> str | None:
    text = _coerce_text(value).strip()
    return text or None


def _normalize_jsonish_field(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        return items or None

    text = _coerce_text(value).strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text

    if parsed in (None, "", [], {}):
        return None
    return parsed
