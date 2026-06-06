from __future__ import annotations

import re
from datetime import datetime

from .deepseek_client import DeepSeekClient
from .models import AppPaths, JwcDbRecord, OriginalBody, RawPage, TempEvent, WechatDbArticleRecord, default_app_paths


class LLMExtractService:
    CAMPUS_KEYWORDS = ["九龙湖", "四牌楼", "丁家桥", "无锡", "苏州", "线上"]
    TOPIC_KEYWORDS = {
        "竞赛": ["竞赛", "比赛", "大赛"],
        "创新创业": ["创新创业", "创业", "创赛"],
        "讲座": ["讲座", "报告会", "学术报告"],
        "奖学金": ["奖学金", "评奖评优"],
        "志愿活动": ["志愿", "志愿服务"],
        "招生": ["招生", "报名"],
        "科研": ["科研", "课题", "项目申报"],
        "就业": ["就业", "招聘", "实习"],
    }

    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or default_app_paths()
        self.paths.ensure()
        self.prompt_path = self.paths.prompts_dir / "llm1_extract.txt"
        self.client = DeepSeekClient()

    def extract(
        self,
        *,
        raw_page: RawPage | JwcDbRecord | WechatDbArticleRecord,
        original_body: OriginalBody,
        attempt: int,
        feedback: dict | None = None,
    ) -> TempEvent:
        if self.client.is_available():
            return self._extract_remote(
                raw_page=raw_page,
                original_body=original_body,
                attempt=attempt,
                feedback=feedback,
            )
        return self._extract_fallback(
            raw_page=raw_page,
            original_body=original_body,
            attempt=attempt,
            feedback=feedback,
        )

    def _extract_remote(
        self,
        *,
        raw_page: RawPage | JwcDbRecord | WechatDbArticleRecord,
        original_body: OriginalBody,
        attempt: int,
        feedback: dict | None = None,
    ) -> TempEvent:
        system_prompt = self.prompt_path.read_text(encoding="utf-8")
        payload = {
            "page_id": raw_page.page_id,
            "title": raw_page.title,
            "source_url": raw_page.source_url,
            "attempt": attempt,
            "original_text": original_body.original_text,
            "feedback": feedback or {},
            "required_output_schema": {
                "website": "string",
                "title": "string",
                "cleaned_document": "string",
                "summary": "string",
                "regis_start_time": "string|null",
                "regis_end_time": "string|null",
                "activity_start_time": "string|null",
                "campus": ["string"],
                "target_grade": ["integer"],
                "topics": ["string"],
                "evidence": {
                    "regis_start_time": "string|null",
                    "regis_end_time": "string|null",
                    "activity_start_time": "string|null",
                },
                "need_retry": "boolean",
                "retry_reason": "string",
            },
        }
        response = self.client.chat_json(
            model=self.client.config.model_llm1,
            system_prompt=system_prompt,
            user_payload=payload,
            reasoning_effort="high",
            thinking_enabled=True,
        )
        return self._build_remote_temp_event(
            raw_page=raw_page,
            original_body=original_body,
            attempt=attempt,
            response=response,
        )

    def _build_remote_temp_event(
        self,
        *,
        raw_page: RawPage | JwcDbRecord | WechatDbArticleRecord,
        original_body: OriginalBody,
        attempt: int,
        response: dict,
    ) -> TempEvent:
        fallback_year = _default_year_from_raw_page(raw_page)
        regis_start_time = _normalize_time_value(response.get("regis_start_time"), fallback_year=fallback_year)
        regis_end_time = _normalize_time_value(response.get("regis_end_time"), fallback_year=fallback_year)
        activity_start_time = _normalize_time_value(response.get("activity_start_time"), fallback_year=fallback_year)
        evidence = _evidence_dict(response.get("evidence"))

        if _should_clear_registration_window(
            original_text=original_body.original_text,
            regis_start_time=regis_start_time,
            regis_end_time=regis_end_time,
            fallback_year=fallback_year,
        ):
            regis_start_time = None
            regis_end_time = None
            evidence["regis_start_time"] = None
            evidence["regis_end_time"] = None

        return TempEvent.create(
            page_id=raw_page.page_id,
            attempt=attempt,
            website=raw_page.source_url,
            title=str(response.get("title") or raw_page.title).strip(),
            cleaned_document=str(response.get("cleaned_document") or original_body.original_text).strip(),
            summary=str(response.get("summary") or self._build_summary(raw_page.title, original_body.original_text)).strip(),
            regis_start_time=regis_start_time,
            regis_end_time=regis_end_time,
            activity_start_time=activity_start_time,
            campus=_string_list(response.get("campus")),
            target_grade=_int_list(response.get("target_grade")),
            topics=_string_list(response.get("topics")),
            evidence=evidence,
            need_retry=bool(response.get("need_retry", False)),
            retry_reason=str(response.get("retry_reason") or ""),
        )

    def _extract_fallback(
        self,
        *,
        raw_page: RawPage | JwcDbRecord | WechatDbArticleRecord,
        original_body: OriginalBody,
        attempt: int,
        feedback: dict | None = None,
    ) -> TempEvent:
        text = original_body.original_text
        regis_start, regis_end, regis_evidence = self._extract_registration_window(text)
        activity_start, activity_evidence = self._extract_activity_time(text)
        if feedback:
            rejected = set(str(key) for key in feedback.get("rule_failed_fields", []))
            if "activity_start_time" in rejected:
                activity_start = None
                activity_evidence = None

        summary = self._build_summary(raw_page.title, text)
        return TempEvent.create(
            page_id=raw_page.page_id,
            attempt=attempt,
            website=raw_page.source_url,
            title=raw_page.title.strip(),
            cleaned_document=text,
            summary=summary,
            regis_start_time=regis_start,
            regis_end_time=regis_end,
            activity_start_time=activity_start,
            campus=self._extract_campus(raw_page.title, text),
            target_grade=self._extract_target_grade(raw_page.title, text),
            topics=self._extract_topics(raw_page.title, text),
            evidence={
                "regis_start_time": regis_evidence,
                "regis_end_time": regis_evidence,
                "activity_start_time": activity_evidence,
            },
            need_retry=False,
            retry_reason="",
        )

    def _build_summary(self, title: str, text: str) -> str:
        first = text.split("\n\n", 1)[0].strip()
        candidate = first if len(first) >= 20 else title
        return candidate[:180]

    def _extract_registration_window(self, text: str) -> tuple[str | None, str | None, str | None]:
        for line in text.splitlines():
            if not any(keyword in line for keyword in ("报名", "申报", "申请", "提交")):
                continue
            matches = list(_iter_date_matches(line))
            if not matches:
                continue
            start = _match_to_datetime(matches[0], default_end=False)
            end = _match_to_datetime(matches[1], default_end=True) if len(matches) > 1 else None
            if start or end:
                return start, end, line.strip()
        return None, None, None

    def _extract_activity_time(self, text: str) -> tuple[str | None, str | None]:
        for line in text.splitlines():
            if not any(keyword in line for keyword in ("活动时间", "比赛时间", "讲座时间", "会议时间", "举办时间")):
                continue
            matches = list(_iter_date_matches(line))
            if not matches:
                continue
            return _match_to_datetime(matches[0], default_end=False), line.strip()
        return None, None

    def _extract_campus(self, title: str, text: str) -> list[str]:
        combined = f"{title}\n{text}"
        return [keyword for keyword in self.CAMPUS_KEYWORDS if keyword in combined]

    def _extract_target_grade(self, title: str, text: str) -> list[int]:
        combined = f"{title}\n{text}"
        grades: set[int] = set()
        if any(keyword in combined for keyword in ("全校学生", "全体学生", "全体同学", "全校师生")):
            return [1, 2, 3, 4, 5, 6, 7]
        if any(keyword in combined for keyword in ("本科生", "本科")):
            grades.update({1, 2, 3, 4})
        if any(keyword in combined for keyword in ("研究生", "硕士", "博士")):
            grades.update({5, 6, 7})
        mapping = {"大一": 1, "大二": 2, "大三": 3, "大四": 4}
        for keyword, grade in mapping.items():
            if keyword in combined:
                grades.add(grade)
        return sorted(grades)

    def _extract_topics(self, title: str, text: str) -> list[str]:
        combined = f"{title}\n{text}"
        return [topic for topic, keywords in self.TOPIC_KEYWORDS.items() if any(keyword in combined for keyword in keywords)]


DATE_PATTERN = re.compile(
    (
        r"(?:(?P<year>20\d{2})\s*[年/-])?\s*"
        r"(?P<month>\d{1,2})\s*[月/-]\s*"
        r"(?P<day>\d{1,2})\s*日?"
        r"(?:\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{1,2})(?:[:：](?P<second>\d{1,2}))?)?"
    )
)


def _iter_date_matches(text: str):
    return DATE_PATTERN.finditer(text)


def _match_to_datetime(match: re.Match[str], *, default_end: bool) -> str | None:
    year = int(match.group("year") or datetime.now().year)
    month = int(match.group("month"))
    day = int(match.group("day"))
    hour = int(match.group("hour") or (23 if default_end else 0))
    minute = int(match.group("minute") or (59 if default_end else 0))
    second = int(match.group("second") or (59 if default_end else 0))
    try:
        value = datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _optional_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _default_year_from_raw_page(raw_page: RawPage | JwcDbRecord | WechatDbArticleRecord) -> int:
    for value in (raw_page.published_at, raw_page.fetched_at):
        if not value:
            continue
        match = re.search(r"(20\d{2})", str(value))
        if match:
            return int(match.group(1))
    return datetime.now().year


def _normalize_time_value(value, *, fallback_year: int) -> str | None:
    text = _optional_str(value)
    if text is None:
        return None
    text = text.replace("：", ":").strip()

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    for fmt in (
        "%Y年%m月%d日 %H:%M:%S",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日%H:%M:%S",
        "%Y年%m月%d日%H:%M",
        "%m月%d日 %H:%M:%S",
        "%m月%d日 %H:%M",
        "%m月%d日%H:%M:%S",
        "%m月%d日%H:%M",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            year = parsed.year if "%Y" in fmt else fallback_year
            return parsed.replace(year=year).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return text


def _should_clear_registration_window(
    *,
    original_text: str,
    regis_start_time: str | None,
    regis_end_time: str | None,
    fallback_year: int,
) -> bool:
    if not regis_start_time or not regis_end_time:
        return False

    head = original_text.split("\n一、", 1)[0]
    time_points: list[str] = []
    for match in re.finditer(r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{2})", head):
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        try:
            point = datetime(fallback_year, month, day, hour, minute, 0).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if point not in time_points:
            time_points.append(point)

    if len(time_points) < 4:
        return False
    return regis_start_time == time_points[0] and regis_end_time == time_points[-1]


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _int_list(value) -> list[int]:
    if not isinstance(value, list):
        return []
    items: list[int] = []
    for item in value:
        try:
            items.append(int(item))
        except (TypeError, ValueError):
            continue
    return items


def _evidence_dict(value) -> dict[str, str | None]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _optional_str(item) for key, item in value.items()}
