from __future__ import annotations

import re


JWC_CLEAN_RULE_VERSION = "jwc_db_v2"

_LIST_MARKER_RE = re.compile(r"^(?:附件\d+[:：]?|[（(]?\d+[）)]|[0-9]+[、.]|[一二三四五六七八九十]+[、.])")
_CONNECTOR_ONLY_RE = re.compile(r"^[和及与或、]+$")
_ATTACHMENT_LINE_RE = re.compile(r"^(?:附件\d*[:：]?\s*)?.+\.(?:pdf|doc|docx|xls|xlsx|zip|rar)$", re.IGNORECASE)


def normalize_jwc_cleaned_document(text: str) -> str:
    lines = _normalize_lines(text)
    merged = _merge_lines(lines)
    trimmed = _drop_trailing_attachments(merged)
    return "\n".join(trimmed).strip()


def normalize_cleaned_document(text: str) -> str:
    normalized = (
        str(text or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u3000", " ")
        .replace("\u00a0", " ")
        .replace("\ufeff", "")
        .replace("\u200b", "")
    )
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def normalize_optional_storage_text(text: str | None) -> str | None:
    normalized = normalize_cleaned_document("" if text is None else text)
    return normalized or None


def _normalize_lines(text: str) -> list[str]:
    normalized = (
        str(text or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u3000", " ")
        .replace("\u00a0", " ")
        .replace("\ufeff", "")
        .replace("\u200b", "")
    )
    normalized = re.sub(r"[ \t]+", " ", normalized)
    lines = [line.strip() for line in normalized.split("\n")]

    compact: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if compact and not previous_blank:
                compact.append("")
            previous_blank = True
            continue
        compact.append(line)
        previous_blank = False
    while compact and compact[-1] == "":
        compact.pop()
    return compact


def _merge_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if not line:
            if merged and merged[-1] != "":
                merged.append("")
            continue

        if not merged or merged[-1] == "":
            merged.append(line)
            continue

        previous = merged[-1]
        if _should_merge(previous, line):
            merged[-1] = _merge_pair(previous, line)
        else:
            merged.append(line)
    return merged


def _should_merge(previous: str, current: str) -> bool:
    if _CONNECTOR_ONLY_RE.fullmatch(current):
        return True
    if _LIST_MARKER_RE.match(current):
        return False
    if previous.endswith(("。", "！", "？", "；", ";")):
        return False
    if previous.endswith(("：", ":")):
        return False
    if len(previous) <= 2:
        return True
    if len(current) <= 2:
        return True
    if current.startswith(("，", "。", "；", "：", "）", ")", "】", "]")):
        return True
    if previous.endswith(("（", "(", "【", "[")):
        return True
    return not _looks_like_new_block(current)


def _looks_like_new_block(line: str) -> bool:
    if _LIST_MARKER_RE.match(line):
        return True
    if line.endswith(("：", ":")) and len(line) <= 20:
        return True
    return False


def _merge_pair(previous: str, current: str) -> str:
    if _CONNECTOR_ONLY_RE.fullmatch(current):
        return f"{previous}{current}"
    if previous.endswith(("（", "(", "【", "[")) or current.startswith(("）", ")", "】", "]", "，", "。", "；", "：")):
        return f"{previous}{current}"
    return f"{previous}{current}"


def _drop_trailing_attachments(lines: list[str]) -> list[str]:
    end = len(lines)
    while end > 0:
        line = lines[end - 1]
        if not line:
            end -= 1
            continue
        if _ATTACHMENT_LINE_RE.match(line):
            end -= 1
            continue
        break
    result = lines[:end]
    while result and result[-1] == "":
        result.pop()
    return result
