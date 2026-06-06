from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import AppPaths, WechatAccountResolution, default_app_paths


class WechatAccountResolutionError(RuntimeError):
    """Raised when a WeChat account identifier cannot be resolved uniquely."""


class WechatAccountResolver:
    PRIORITY_FIELDS = ("account_dir", "display_name", "alias", "input_name")

    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or default_app_paths()
        self.paths.ensure()
        self._cache: dict[str, WechatAccountResolution] = {}

    def resolve(self, identifier: str) -> WechatAccountResolution:
        key = str(identifier or "").strip()
        if not key:
            raise WechatAccountResolutionError("WeChat account identifier cannot be empty.")
        if key in self._cache:
            return self._cache[key]

        conn = self._connect()
        try:
            for field in self.PRIORITY_FIELDS:
                rows = conn.execute(
                    f"""
                    SELECT account_dir, display_name, alias, input_name, biz_key
                    FROM account_registry
                    WHERE {field} = ?
                    ORDER BY id ASC
                    """,
                    (key,),
                ).fetchall()
                if not rows:
                    continue
                if len(rows) > 1:
                    raise WechatAccountResolutionError(
                        f"Ambiguous WeChat account identifier `{key}` matched multiple rows by `{field}`."
                    )
                resolution = self._row_to_resolution(rows[0])
                self._cache[key] = resolution
                self._cache[resolution.account_dir] = resolution
                if resolution.display_name:
                    self._cache[resolution.display_name] = resolution
                if resolution.alias:
                    self._cache[resolution.alias] = resolution
                if resolution.input_name:
                    self._cache[resolution.input_name] = resolution
                return resolution
        finally:
            conn.close()

        raise WechatAccountResolutionError(f"WeChat account identifier `{key}` was not found in account_registry.")

    def resolve_batch_file(self, batch_file: str | Path) -> list[WechatAccountResolution]:
        path = self._resolve_path(batch_file)
        identifiers = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return [self.resolve(identifier) for identifier in identifiers]

    def resolve_by_biz_key(self, biz_key: str) -> WechatAccountResolution:
        key = str(biz_key or "").strip()
        if not key:
            raise WechatAccountResolutionError("WeChat biz_key cannot be empty.")
        cache_key = f"biz_key:{key}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT account_dir, display_name, alias, input_name, biz_key
                FROM account_registry
                WHERE biz_key = ?
                ORDER BY id ASC
                """,
                (key,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            raise WechatAccountResolutionError(f"WeChat biz_key `{key}` was not found in account_registry.")
        if len(rows) > 1:
            raise WechatAccountResolutionError(f"WeChat biz_key `{key}` matched multiple rows.")
        resolution = self._row_to_resolution(rows[0])
        self._cache[cache_key] = resolution
        return resolution

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.paths.wechat_control_db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _resolve_path(self, batch_file: str | Path) -> Path:
        path = Path(batch_file)
        if path.is_absolute():
            return path
        return (self.paths.repo_root / path).resolve()

    def _row_to_resolution(self, row: sqlite3.Row) -> WechatAccountResolution:
        return WechatAccountResolution(
            account_dir=str(row["account_dir"] or "").strip(),
            display_name=str(row["display_name"] or "").strip(),
            alias=_optional_str(row["alias"]),
            input_name=str(row["input_name"] or "").strip(),
            biz_key=str(row["biz_key"] or "").strip(),
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
