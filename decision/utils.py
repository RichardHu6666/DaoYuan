from __future__ import annotations

from datetime import datetime


def now_utc() -> datetime:
    return datetime.utcnow()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def normalize_text(value: str) -> str:
    return " ".join(str(value).split())
