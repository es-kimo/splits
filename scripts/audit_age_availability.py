#!/usr/bin/env python3
"""연령 모델 입력(출생연도/학령구간/성별) 가용성을 점검합니다.

기본 사용:
    python3 scripts/audit_age_availability.py
    python3 scripts/audit_age_availability.py --results /path/to/records_anon.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_RESULTS = Path("data/records_anon.csv")
DEFAULT_SHARED_RESULTS = Path("/Users/kihyun/orgs/personal/splits/data/records_anon.csv")
DEFAULT_OUT = Path("out/age_data_audit.md")


def _norm(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _pick_results(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_RESULTS and DEFAULT_SHARED_RESULTS.exists():
        return DEFAULT_SHARED_RESULTS
    raise FileNotFoundError(f"[error] records_anon.csv를 찾지 못했습니다: {path}")


def _to_int(value: str) -> int | None:
    text = _norm(value)
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return None


def run(results_path: Path) -> dict[str, object]:
    total_rows = 0
    present = Counter()
    unique_values: dict[str, Counter[str]] = {
        "학년": Counter(),
        "학령구간": Counter(),
        "종별": Counter(),
    }

    athlete_birth_years: dict[str, set[int]] = defaultdict(set)
    age_rows = Counter()
    age_athletes: dict[int, set[str]] = defaultdict(set)
    first_seen: dict[str, tuple[int, str, str]] = {}

    with results_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"익명키", "대회연도", "출생연도", "학년", "학령구간", "성별", "종별"}
        missing = sorted(required.difference(set(reader.fieldnames or [])))
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"[error] 필수 컬럼이 없습니다: {joined}")

        for row in reader:
            total_rows += 1
            athlete_id = _norm(row.get("익명키"))
            season_year = _to_int(_norm(row.get("대회연도")))
            birth_year = _to_int(_norm(row.get("출생연도")))
            grade = _norm(row.get("학년"))
            division = _norm(row.get("학령구간"))
            sex = _norm(row.get("성별"))
            category = _norm(row.get("종별"))

            if birth_year is not None:
                present["출생연도"] += 1
            if grade:
                present["학년"] += 1
                unique_values["학년"][grade] += 1
            if division:
                present["학령구간"] += 1
                unique_values["학령구간"][division] += 1
            if sex:
                present["성별"] += 1
            if category:
                unique_values["종별"][category] += 1

            if athlete_id and birth_year is not None:
                athlete_birth_years[athlete_id].add(birth_year)

            if season_year is not None and birth_year is not None:
                age = season_year - birth_year
                if 3 <= age <= 40:
                    age_rows[age] += 1
                    if athlete_id:
                        age_athletes[age].add(athlete_id)

            if athlete_id and season_year is not None:
                existing = first_seen.get(athlete_id)
                if existing is None or season_year < existing[0]:
                    first_seen[athlete_id] = (season_year, division, sex)

    total_athletes = len(first_seen)
    athletes_with_birth = sum(1 for years in athlete_birth_years.values() if years)
    athletes_conflicting_birth = sum(1 for years in athlete_birth_years.values() if len(years) > 1)
    debut_by_division_sex = Counter((division, sex) for _, division, sex in first_seen.values())

    return {
        "results_path": str(results_path),
        "total_rows": total_rows,
        "total_athletes": total_athletes,
        "present": dict(present),
        "grade_values": unique_values["학년"].most_common(20),
        "division_values": unique_values["학령구간"].most_common(20),
        "category_values": unique_values["종별"].most_common(20),
        "athletes_with_birth": athletes_with_birth,
        "athletes_conflicting_birth": athletes_conflicting_birth,
        "age_rows": {age: age_rows[age] for age in sorted(age_rows)},
        "age_athletes": {age: len(age_athletes[age]) for age in sorted(age_athletes)},
        "debut_by_division_sex": debut_by_division_sex.most_common(),
    }


def _pct(part: int, whole: int) -> str:
    if whole <= 0:
        return "0.00%"
    return f"{(part / whole) * 100.0:.2f}%"


def render_markdown(report: dict[str, object]) -> str:
    total_rows = int(report["total_rows"])
    total_athletes = int(report["total_athletes"])
    present = report["present"]
    athletes_with_birth = int(report["athletes_with_birth"])
    athletes_conflicting_birth = int(report["athletes_conflicting_birth"])
    age_rows = report["age_rows"]
    age_athletes = report["age_athletes"]
    debut_by_division_sex = report["debut_by_division_sex"]

    lines = [
        "# 연령 입력 데이터 가용성 감사",
        "",
        f"- 입력 파일: `{report['results_path']}`",
        f"- 총 행 수: {total_rows:,}",
        f"- 선수 수(익명키 기준): {total_athletes:,}",
        "",
        "## 핵심 커버리지",
        "",
        "| 항목 | 커버리지(행) | 비율 |",
        "| --- | ---: | ---: |",
        f"| 출생연도 | {int(present.get('출생연도', 0)):,} | {_pct(int(present.get('출생연도', 0)), total_rows)} |",
        f"| 학년 | {int(present.get('학년', 0)):,} | {_pct(int(present.get('학년', 0)), total_rows)} |",
        f"| 학령구간 | {int(present.get('학령구간', 0)):,} | {_pct(int(present.get('학령구간', 0)), total_rows)} |",
        f"| 성별 | {int(present.get('성별', 0)):,} | {_pct(int(present.get('성별', 0)), total_rows)} |",
        "",
        "## 출생연도 일관성",
        "",
        f"- 출생연도 보유 선수: {athletes_with_birth:,} / {total_athletes:,} ({_pct(athletes_with_birth, total_athletes)})",
        f"- 출생연도 충돌 선수: {athletes_conflicting_birth:,}",
        "",
        "## 연령 분포 (age=대회연도-출생연도, 3~40세)",
        "",
        "| age | 행 수 | 선수 수 |",
        "| ---: | ---: | ---: |",
    ]
    for age in sorted(age_rows):
        lines.append(f"| {age} | {int(age_rows[age]):,} | {int(age_athletes.get(age, 0)):,} |")

    lines.extend(
        [
            "",
            "## 데뷔 코호트 (부문×성별, 선수 수)",
            "",
            "| 학령구간 | 성별 | 선수 수 |",
            "| --- | --- | ---: |",
        ]
    )
    for (division, sex), count in debut_by_division_sex:
        lines.append(f"| {division or '(blank)'} | {sex or '(blank)'} | {count:,} |")

    lines.extend(
        [
            "",
            "## 학년 상위 값 (상위 20개)",
            "",
            "| 학년 | 행 수 |",
            "| --- | ---: |",
        ]
    )
    for grade, count in report["grade_values"]:
        lines.append(f"| {grade or '(blank)'} | {count:,} |")

    lines.extend(
        [
            "",
            "## 학령구간 분포 (상위 20개)",
            "",
            "| 학령구간 | 행 수 |",
            "| --- | ---: |",
        ]
    )
    for division, count in report["division_values"]:
        lines.append(f"| {division or '(blank)'} | {count:,} |")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="R-06 연령 입력 데이터 가용성 감사")
    parser.add_argument("--results", default=str(DEFAULT_RESULTS), help="records_anon.csv 경로")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="마크다운 출력 경로")
    args = parser.parse_args()

    results_path = _pick_results(Path(args.results).expanduser())
    report = run(results_path)
    markdown = render_markdown(report)

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"[ok] out={out_path}")


if __name__ == "__main__":
    main()
