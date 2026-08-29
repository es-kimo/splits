from __future__ import annotations

import re
from datetime import date
from typing import Any

# Korean short-track season is treated as July -> next June.
SEASON_START_MONTH = 7
SEASON_END_MONTH = 6

_DATE_RE = re.compile(r"(?P<year>(?:19|20)\d{2})\D*(?P<month>\d{1,2})\D*(?P<day>\d{1,2})")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def parse_kst_date(value: Any) -> date | None:
    text = _norm(value)
    if not text:
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    try:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        return date(year, month, day)
    except ValueError:
        return None


def infer_season_year(date_value: Any, fallback_year: int | None = None) -> int | None:
    parsed = parse_kst_date(date_value)
    if parsed is None:
        return fallback_year
    if parsed.month >= SEASON_START_MONTH:
        return parsed.year
    return parsed.year - 1


def race_date_token(date_value: Any, fallback_year: int | None = None) -> str:
    parsed = parse_kst_date(date_value)
    if parsed is not None:
        return parsed.strftime("%Y%m%d")
    if fallback_year is None:
        return "00000000"
    return f"{int(fallback_year):04d}0101"

