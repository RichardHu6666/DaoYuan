from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def write_event(self, record: SchoolEventRecord) -> int:
        db = self._require_db()
        return int(db.insert("school_event_table", record.to_db_row()))

    def upsert_event(self, record: SchoolEventRecord) -> int:
        db = self._require_db()
        existing = self._find_existing_event(record)
        row = record.to_db_row()
        if existing is None:
            return int(db.insert("school_event_table", row))
        db.update_by_pk("school_event_table", existing["id"], row)
        return int(existing["id"])

    def _find_existing_event(self, record: SchoolEventRecord) -> dict | None:
        db = self._require_db()
        conn = getattr(db, "conn", None)
        if conn is None:
            return db.fetch_one(
                "school_event_table",
                {
                    "website": record.website,
                    "title": record.title,
                    "regis_start_time": record.regis_start_time,
                    "regis_end_time": record.regis_end_time,
                    "activity_start_time": record.activity_start_time,
                },
                deserialize_json=False,
            )

        filters = {
            "website": record.website,
            "title": record.title,
            "regis_start_time": record.regis_start_time,
            "regis_end_time": record.regis_end_time,
            "activity_start_time": record.activity_start_time,
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
