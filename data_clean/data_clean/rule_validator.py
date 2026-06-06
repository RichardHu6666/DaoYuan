from __future__ import annotations

import re
from datetime import datetime

from .models import OriginalBody, TempEvent


class RuleValidator:
    def validate(self, temp_event: TempEvent, original_body: OriginalBody) -> dict:
        original_text = original_body.original_text
        result = {
            "regis_start_time": self._appears(temp_event.regis_start_time, original_text),
            "regis_end_time": self._appears(temp_event.regis_end_time, original_text),
            "activity_start_time": self._appears(temp_event.activity_start_time, original_text),
        }
        provided_fields = [
            field
            for field, value in (
                ("regis_start_time", temp_event.regis_start_time),
                ("regis_end_time", temp_event.regis_end_time),
                ("activity_start_time", temp_event.activity_start_time),
            )
            if value
        ]
        result["rule_passed"] = all(result[field] for field in provided_fields)
        result["checked_fields"] = provided_fields
        return result

    def _appears(self, value: str | None, text: str) -> bool:
        if not value:
            return True
        return any(variant in text for variant in _time_variants(value))


def _time_variants(value: str) -> list[str]:
    text = _normalize_time_text(value)
    variants: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        normalized = _normalize_time_text(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            variants.append(normalized)

    add(text)
    add(text.replace(" ", ""))
    add(text.replace(":", "："))
    add(text.replace("：", ":"))

    parsed = _parse_datetime_like(text)
    if parsed is None:
        return variants

    add(parsed.strftime("%Y-%m-%d %H:%M:%S"))
    add(parsed.strftime("%Y-%m-%d %H:%M"))
    add(parsed.strftime("%Y/%m/%d %H:%M:%S"))
    add(parsed.strftime("%Y/%m/%d %H:%M"))
    add(parsed.strftime("%Y年%m月%d日 %H:%M:%S"))
    add(parsed.strftime("%Y年%m月%d日 %H:%M"))
    add(f"{parsed.year}年{parsed.month}月{parsed.day}日 {parsed:%H:%M}")
    add(f"{parsed.year}年{parsed.month}月{parsed.day}日{parsed:%H:%M}")
    add(parsed.strftime("%m月%d日 %H:%M"))
    add(f"{parsed.month}月{parsed.day}日 {parsed:%H:%M}")
    add(f"{parsed.month}月{parsed.day}日{parsed:%H:%M}")
    add(parsed.strftime("%Y年%m月%d日"))
    add(f"{parsed.year}年{parsed.month}月{parsed.day}日")
    add(parsed.strftime("%m月%d日"))
    add(f"{parsed.month}月{parsed.day}日")
    return variants


def _normalize_time_text(value: str) -> str:
    return str(value).strip().replace("\u3000", " ")


def _parse_datetime_like(value: str) -> datetime | None:
    text = _normalize_time_text(value).replace("：", ":")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y年%m月%d日 %H:%M:%S",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日%H:%M:%S",
        "%Y年%m月%d日%H:%M",
        "%Y年%m月%d日",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    match = re.fullmatch(
        r"(?:(?P<year>20\d{2})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})日(?:\s*(?P<hour>\d{1,2}):(?P<minute>\d{1,2})(?::(?P<second>\d{1,2}))?)?",
        text,
    )
    if match is None:
        return None

    year = int(match.group("year") or datetime.now().year)
    month = int(match.group("month"))
    day = int(match.group("day"))
    hour = int(match.group("hour") or 0)
    minute = int(match.group("minute") or 0)
    second = int(match.group("second") or 0)
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
