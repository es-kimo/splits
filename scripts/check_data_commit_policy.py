#!/usr/bin/env python3
import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_DATA_FILES = {
    "data/README.md",
    "data/records_anon.csv",
    "data/public_figures.csv",
    "data/coverage.csv",
    "data/stats_distribution.csv",
    "data/stats_participation.csv",
    "data/meet_index_inf201.csv",
    "data/class_level_map.csv",
    "data/class_level_year_category_counts.csv",
    "data/class_level_ab_agreement_summary.csv",
    "data/class_level_ab_mismatch_types.csv",
    "data/class_level_year_readiness.csv",
}
FORBIDDEN_DATA_FILES = {
    "data/raw",
    "data/records.csv",
    "data/records_full.csv",
    "data/athlete_info.csv",
    "data/athlete_info_full.csv",
    "data/athlete_index.csv",
    "data/id_merge_candidates.csv",
    "data/id_merges.csv",
}
FORBIDDEN_DATA_PREFIXES = ("data/raw/",)
RECORDS_ANON_COLUMNS = [
    "toCd",
    "classCd",
    "대회명",
    "대회연도",
    "일자",
    "종별",
    "학령구간",
    "거리",
    "SF여부",
    "라운드",
    "라운드종류",
    "순위",
    "기록_초",
    "사유",
    "성별",
    "출생연도",
    "학년",
    "익명키",
]
RECORDS_ANON_FORBIDDEN_COLUMNS = {"idNo", "이름", "소속", "시도", "BIB", "레인"}
ANON_KEY_RE = re.compile(r"^[0-9a-f]{12}$")


def _run_git(repo_root, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(message)
    return result.stdout


def _list_paths(repo_root, mode):
    if mode == "tracked":
        output = _run_git(repo_root, "ls-files")
    else:
        output = _run_git(repo_root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


def _validate_paths(paths):
    errors = []
    for path in paths:
        name = Path(path).name
        if name == ".env" or name.startswith(".env."):
            errors.append(f"금지 파일이 추적/스테이징되었습니다: {path}")

        if path in FORBIDDEN_DATA_FILES or any(path.startswith(prefix) for prefix in FORBIDDEN_DATA_PREFIXES):
            errors.append(f"금지 데이터 파일이 추적/스테이징되었습니다: {path}")
            continue

        if path.startswith("data/") and path not in ALLOWED_DATA_FILES:
            errors.append(f"허용 목록 외 data 파일이 추적/스테이징되었습니다: {path}")
    return errors


def _validate_records_anon(repo_root):
    path = repo_root / "data" / "records_anon.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/records_anon.csv"]

    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/records_anon.csv가 비어 있습니다."]

        errors = []
        if header != RECORDS_ANON_COLUMNS:
            errors.append(f"data/records_anon.csv 헤더가 기대값과 다릅니다: {header}")
            return errors

        forbidden = RECORDS_ANON_FORBIDDEN_COLUMNS.intersection(header)
        if forbidden:
            errors.append(f"data/records_anon.csv에 금지 컬럼이 포함되었습니다: {', '.join(sorted(forbidden))}")
            return errors

        key_index = header.index("익명키")
        for row_no, row in enumerate(reader, start=2):
            if len(row) <= key_index:
                errors.append(f"data/records_anon.csv {row_no}행 익명키 컬럼이 누락되었습니다.")
                continue
            key = row[key_index].strip()
            if not ANON_KEY_RE.fullmatch(key):
                errors.append(f"data/records_anon.csv {row_no}행 익명키 형식이 올바르지 않습니다.")
        return errors


def main():
    parser = argparse.ArgumentParser(description="익명 데이터 커밋 정책 검증")
    parser.add_argument("--mode", choices=["tracked", "staged"], default="tracked")
    args = parser.parse_args()

    repo_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()
    )

    paths = _list_paths(repo_root, args.mode)
    errors = _validate_paths(paths)

    should_validate_records_anon = "data/records_anon.csv" in paths
    if should_validate_records_anon:
        errors.extend(_validate_records_anon(repo_root))

    if errors:
        print("[error] 익명 데이터 커밋 정책 위반:")
        for message in errors:
            print(f"- {message}")
        sys.exit(1)

    print(f"[ok] 익명 데이터 커밋 정책 검증 통과 ({args.mode})")


if __name__ == "__main__":
    main()
