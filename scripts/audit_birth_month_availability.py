#!/usr/bin/env python3
"""INF503 생월(생년월일) 정보 확보 가능성을 점검합니다.

사용 예:
    python3 scripts/audit_birth_month_availability.py
    python3 scripts/audit_birth_month_availability.py --data-dir /Users/kihyun/orgs/personal/splits/data
    python3 scripts/audit_birth_month_availability.py --json-out /tmp/birth_month_audit.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from html import unescape
from pathlib import Path

TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
CELL_RE = re.compile(r"<(th|td)[^>]*>(.*?)</(?:th|td)>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

YEAR_ONLY_RE = re.compile(r"^(19|20)\d{2}년$")
YEAR_DIGITS_RE = re.compile(r"^(19|20)\d{2}$")
YYYYMMDD_DIGITS_RE = re.compile(r"^(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$")
YEAR_MONTH_RE = re.compile(r"^(19|20)\d{2}[.\-/](0?[1-9]|1[0-2])(?:[.\-/](0?[1-9]|[12]\d|3[01]))?$")
YEAR_MONTH_KO_RE = re.compile(r"^(19|20)\d{2}\s*년\s*(0?[1-9]|1[0-2])\s*월(?:\s*(0?[1-9]|[12]\d|3[01])\s*일)?$")


def _clean_text(raw: str) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub("", unescape(raw or ""))).strip()


def _is_birth_key(key: str) -> bool:
    key_norm = SPACE_RE.sub("", key)
    return ("출생" in key_norm) or ("생년" in key_norm)


def _classify_birth_value(value: str) -> str:
    text = SPACE_RE.sub("", value)
    if text in {"", "년"}:
        return "empty_or_year_marker"
    if YEAR_ONLY_RE.fullmatch(text):
        return "year_only"
    if YEAR_MONTH_RE.fullmatch(text) or YEAR_MONTH_KO_RE.fullmatch(text) or YYYYMMDD_DIGITS_RE.fullmatch(text):
        return "month_or_day_present"
    if YEAR_DIGITS_RE.fullmatch(text):
        return "year_digits_only"
    return "other"


def _extract_key_value_pairs(html: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for tr_match in TR_RE.finditer(html):
        row_html = tr_match.group(1)
        cells = [_clean_text(cell_html) for _, cell_html in CELL_RE.findall(row_html)]
        for idx in range(0, len(cells) - 1, 2):
            key = cells[idx]
            value = cells[idx + 1]
            if key:
                pairs.append((key, value))
    return pairs


def _infer_pipeline_behavior(repo_root: Path) -> str:
    scrape_path = repo_root / "scrape.py"
    if not scrape_path.exists():
        return "unknown (scrape.py not found)"
    text = scrape_path.read_text(encoding="utf-8", errors="ignore")
    uses_birth_year_key = 'pairs.get("출생년도")' in text
    extracts_year_only = "BIRTH_YEAR_RE" in text and "birth_year = int(m.group(1))" in text
    if uses_birth_year_key and extracts_year_only:
        return "year_only_parser (출생년도에서 4자리 연도만 추출)"
    return "unknown (parser pattern not recognized)"


def run(data_dir: Path, sample_limit: int = 10) -> dict:
    inf503_dir = data_dir / "raw" / "inf503"
    if not inf503_dir.exists():
        raise FileNotFoundError(f"[error] INF503 캐시 디렉터리가 없습니다: {inf503_dir}")

    files = sorted(inf503_dir.glob("*.html"))
    if not files:
        raise FileNotFoundError(f"[error] INF503 HTML 파일이 없습니다: {inf503_dir}")

    field_counter: Counter[str] = Counter()
    format_counter: Counter[str] = Counter()
    month_examples: list[dict] = []
    other_examples: list[dict] = []
    files_with_birth_field = 0

    for path in files:
        html = path.read_text(encoding="utf-8", errors="ignore")
        pairs = _extract_key_value_pairs(html)
        birth_pairs = [(key, value) for key, value in pairs if _is_birth_key(key)]
        if not birth_pairs:
            continue
        files_with_birth_field += 1
        for key, value in birth_pairs:
            field_counter[key] += 1
            fmt = _classify_birth_value(value)
            format_counter[fmt] += 1
            if fmt == "month_or_day_present" and len(month_examples) < sample_limit:
                month_examples.append({"file": path.name, "field": key, "value": value})
            if fmt == "other" and len(other_examples) < sample_limit:
                other_examples.append({"file": path.name, "field": key, "value": value})

    repo_root = Path(__file__).resolve().parents[1]
    parser_behavior = _infer_pipeline_behavior(repo_root)
    month_available = format_counter.get("month_or_day_present", 0) > 0
    parser_drops_month = "year_only_parser" in parser_behavior

    return {
        "data_dir": str(data_dir),
        "inf503_dir": str(inf503_dir),
        "total_files": len(files),
        "files_with_birth_field": files_with_birth_field,
        "birth_field_names": dict(field_counter),
        "birth_value_formats": dict(format_counter),
        "birth_month_available": month_available,
        "month_or_day_examples": month_examples,
        "other_format_examples": other_examples,
        "pipeline_parser_behavior": parser_behavior,
        "pipeline_would_drop_month_if_present": parser_drops_month,
    }


def _print_report(result: dict) -> None:
    print(f"[audit] 대상 디렉터리: {result['inf503_dir']}")
    print(
        "[audit] 파일 수: {0:,} / 출생 필드 감지 파일: {1:,}".format(
            int(result["total_files"]), int(result["files_with_birth_field"])
        )
    )
    print(f"[audit] 출생 필드명 분포: {result['birth_field_names']}")
    print(f"[audit] 출생 값 형식 분포: {result['birth_value_formats']}")
    print(f"[audit] 생월/생일 노출 여부: {'YES' if result['birth_month_available'] else 'NO'}")
    print(f"[audit] 현재 파서 동작: {result['pipeline_parser_behavior']}")
    print(
        "[audit] 월/일이 노출될 경우 현재 파이프라인 누락 가능성: {0}".format(
            "YES" if result["pipeline_would_drop_month_if_present"] else "UNKNOWN"
        )
    )
    if result["month_or_day_examples"]:
        print("[audit] 생월/생일 패턴 샘플:")
        for item in result["month_or_day_examples"]:
            print("  - {file} | {field} | {value}".format(**item))
    if result["other_format_examples"]:
        print("[audit] 비표준 패턴 샘플:")
        for item in result["other_format_examples"]:
            print("  - {file} | {field} | {value}".format(**item))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="INF503 생월(생년월일) 확보 가능성 점검")
    parser.add_argument("--data-dir", default="data", help="수집 데이터 루트 (기본값: data)")
    parser.add_argument("--sample-limit", type=int, default=10, help="샘플 최대 건수 (기본값: 10)")
    parser.add_argument("--json-out", default="", help="JSON 리포트 저장 경로 (선택)")
    args = parser.parse_args(argv)

    try:
        result = run(Path(args.data_dir).expanduser(), sample_limit=max(1, int(args.sample_limit)))
    except Exception as exc:
        print(str(exc))
        return 1

    _print_report(result)
    if args.json_out:
        out_path = Path(args.json_out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[audit] JSON 저장: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
