from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .models import AppPaths, WechatAccountResolution, WechatDbArticleRecord, default_app_paths
from .wechat_account_resolver import WechatAccountResolver


class WechatDbLoader:
    def __init__(
        self,
        paths: AppPaths | None = None,
        resolver: WechatAccountResolver | None = None,
    ):
        self.paths = paths or default_app_paths()
        self.paths.ensure()
        self.resolver = resolver or WechatAccountResolver(self.paths)

    def iter_account_records(
        self,
        *,
        account_identifier: str | None = None,
        account_dir: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Iterable[WechatDbArticleRecord]:
        resolution = self.resolve_account(account_identifier=account_identifier, account_dir=account_dir)
        query = (
            "SELECT id, title, article_url, content_html, content_text, publish_time "
            "FROM articles "
            "WHERE content_text IS NOT NULL AND TRIM(content_text) != '' "
            "ORDER BY id ASC"
        )
        params: list[int] = []
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        elif offset:
            query += " LIMIT -1 OFFSET ?"
            params.append(int(offset))

        conn = self._connect_account_db(resolution.account_dir)
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        for row in rows:
            yield self._row_to_record(resolution, row)

    def load_by_article_id(
        self,
        *,
        article_id: int,
        account_identifier: str | None = None,
        account_dir: str | None = None,
    ) -> WechatDbArticleRecord | None:
        resolution = self.resolve_account(account_identifier=account_identifier, account_dir=account_dir)
        conn = self._connect_account_db(resolution.account_dir)
        try:
            row = conn.execute(
                """
                SELECT id, title, article_url, content_html, content_text, publish_time
                FROM articles
                WHERE id = ?
                """,
                (int(article_id),),
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else self._row_to_record(resolution, row)

    def load_by_page_id(self, page_id: str) -> WechatDbArticleRecord | None:
        prefix = "wechat_db_"
        if not page_id.startswith(prefix):
            return None
        remainder = page_id[len(prefix) :]
        try:
            biz_key, article_id_text = remainder.rsplit("_", 1)
            article_id = int(article_id_text)
        except ValueError:
            return None
        resolution = self.resolver.resolve_by_biz_key(biz_key)
        return self.load_by_article_id(article_id=article_id, account_dir=resolution.account_dir)

    def resolve_account(
        self,
        *,
        account_identifier: str | None = None,
        account_dir: str | None = None,
    ) -> WechatAccountResolution:
        if bool(account_identifier) == bool(account_dir):
            raise ValueError("WechatDbLoader requires exactly one of `account_identifier` or `account_dir`.")
        identifier = account_dir if account_dir else account_identifier
        return self.resolver.resolve(str(identifier))

    def count_records(
        self,
        *,
        account_identifier: str | None = None,
        account_dir: str | None = None,
    ) -> int:
        resolution = self.resolve_account(account_identifier=account_identifier, account_dir=account_dir)
        conn = self._connect_account_db(resolution.account_dir)
        try:
            return int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM articles
                    WHERE content_text IS NOT NULL AND TRIM(content_text) != ''
                    """
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def _connect_account_db(self, account_dir: str) -> sqlite3.Connection:
        db_path = self.paths.wechat_accounts_root / account_dir / "account.sqlite3"
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _row_to_record(self, resolution: WechatAccountResolution, row: sqlite3.Row) -> WechatDbArticleRecord:
        return WechatDbArticleRecord(
            article_id=int(row["id"]),
            account_dir=resolution.account_dir,
            account_name=resolution.display_name,
            biz_key=resolution.biz_key,
            article_url=str(row["article_url"] or "").strip(),
            title=str(row["title"] or "").strip(),
            content_html=str(row["content_html"] or ""),
            content_text=str(row["content_text"] or "").strip(),
            publish_time=_optional_str(row["publish_time"]),
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
