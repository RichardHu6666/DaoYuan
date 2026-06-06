from __future__ import annotations

import os
from pathlib import Path

from .models import AppPaths, default_app_paths
from .state_store import StateStore
from .wechat_account_resolver import WechatAccountResolver
from .wechat_db_loader import WechatDbLoader


class WechatBatchResetService:
    def __init__(
        self,
        paths: AppPaths | None = None,
        resolver: WechatAccountResolver | None = None,
        loader: WechatDbLoader | None = None,
        state_store: StateStore | None = None,
    ):
        self.paths = paths or default_app_paths()
        self.paths.ensure()
        self.resolver = resolver or WechatAccountResolver(self.paths)
        self.loader = loader or WechatDbLoader(self.paths, resolver=self.resolver)
        self.state_store = state_store or StateStore(self.paths)

    def reset_batch(self, *, batch_file: str | Path, drop_main_db: bool = True) -> dict:
        page_ids = self._collect_page_ids(batch_file)
        deleted = self.state_store.cleanup_pages(page_ids)
        removed_files = self._cleanup_cached_files(page_ids)
        removed_db_files = self._cleanup_main_db() if drop_main_db else []
        return {
            "page_ids": len(page_ids),
            "deleted": deleted,
            "removed_cache_files": removed_files,
            "removed_main_db_files": removed_db_files,
        }

    def _collect_page_ids(self, batch_file: str | Path) -> list[str]:
        page_ids: list[str] = []
        for resolution in self.resolver.resolve_batch_file(batch_file):
            for record in self.loader.iter_account_records(account_dir=resolution.account_dir):
                page_ids.append(record.page_id)
        return page_ids

    def _cleanup_cached_files(self, page_ids: list[str]) -> int:
        removed = 0
        wechat_html_dir = self.paths.raw_cache_dir / "wechat_batch1"
        for page_id in page_ids:
            for path in (
                self.paths.raw_cache_dir / f"{page_id}.original.txt",
                wechat_html_dir / f"{page_id}.raw.html",
            ):
                if path.exists():
                    path.unlink()
                    removed += 1
        if wechat_html_dir.exists() and not any(wechat_html_dir.iterdir()):
            wechat_html_dir.rmdir()
        return removed

    def _cleanup_main_db(self) -> list[str]:
        removed: list[str] = []
        for suffix in ("", "-shm", "-wal"):
            path = Path(f"{self.paths.main_db_path}{suffix}")
            if path.exists():
                os.remove(path)
                removed.append(str(path))
        return removed
