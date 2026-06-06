from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import AppPaths, RawPage, default_app_paths


class InputLoader:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or default_app_paths()
        self.paths.ensure()

    def iter_raw_pages(self, source: str | None = None, limit: int | None = None) -> Iterable[RawPage]:
        count = 0
        source_dirs = [self.paths.input_root / source] if source else [self.paths.input_root / name for name in ("wechat", "jwc", "open_web")]
        for source_dir in source_dirs:
            if not source_dir.exists():
                continue
            for path in sorted(source_dir.rglob("*.json")):
                yield self._load_raw_page_file(path)
                count += 1
                if limit is not None and count >= limit:
                    return

    def load_raw_page(self, input_file: str | Path) -> RawPage:
        return self._load_raw_page_file(Path(input_file))

    def load_by_page_id(self, page_id: str) -> RawPage | None:
        for source in ("wechat", "jwc", "open_web"):
            source_dir = self.paths.input_root / source
            if not source_dir.exists():
                continue
            for path in source_dir.rglob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if str(payload.get("page_id")) == page_id:
                    return RawPage.from_dict(payload)
        return None

    def _load_raw_page_file(self, path: Path) -> RawPage:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_page = RawPage.from_dict(payload)
        raw_html_path = Path(raw_page.raw_html_path)
        if not raw_html_path.is_absolute():
            raw_page.raw_html_path = str((self.paths.repo_root / raw_page.raw_html_path).resolve())
        return raw_page
