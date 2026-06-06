from __future__ import annotations

import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from .models import AppPaths, OriginalBody, RawPage, default_app_paths


CLEAN_RULE_VERSION = "v1"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return "\n".join(self.parts)


class HtmlCleaner:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or default_app_paths()
        self.paths.ensure()

    def clean(self, raw_page: RawPage) -> OriginalBody:
        html_path = Path(raw_page.raw_html_path)
        html_text = html_path.read_text(encoding="utf-8", errors="ignore")
        cleaned = self._extract_text(html_text)
        content_hash = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()
        output_path = self.paths.raw_cache_dir / f"{raw_page.page_id}.original.txt"
        output_path.write_text(cleaned, encoding="utf-8")
        return OriginalBody(
            page_id=raw_page.page_id,
            original_text=cleaned,
            content_hash=content_hash,
            clean_rule_version=CLEAN_RULE_VERSION,
            original_text_path=str(output_path),
        )

    def _extract_text(self, html_text: str) -> str:
        text = re.sub(r"<script.*?</script>", "", html_text, flags=re.I | re.S)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.I | re.S)
        text = re.sub(r"<nav.*?</nav>", "", text, flags=re.I | re.S)
        text = re.sub(r"<footer.*?</footer>", "", text, flags=re.I | re.S)
        text = re.sub(r"<header.*?</header>", "", text, flags=re.I | re.S)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
        parser = _TextExtractor()
        parser.feed(text)
        output = parser.text()
        output = re.sub(r"[ \t\u3000]+", " ", output)
        output = re.sub(r"\n{3,}", "\n\n", output)
        return unescape(output).strip()
