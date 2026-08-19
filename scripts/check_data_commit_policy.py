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
    "data/season_month_histogram.csv",
    "data/participation.csv",
    "data/season_activity_counts.csv",
    "data/class_transition_summary.csv",
    "data/gap_return_rates.csv",
    "data/record_stop_rule.csv",
    "data/cohort.csv",
    "data/cohort_stage_summary.csv",
    "data/retention_overall.csv",
    "data/retention_band.csv",
    "data/improvement_rate.csv",
    "data/reverse_distribution.csv",
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
PARTICIPATION_COLUMNS = [
    "익명키",
    "시즌",
    "출생연도",
    "성별",
    "학년",
    "단계",
    "종별_단계",
    "대회수",
    "경기수",
    "classCd목록",
    "오픈참가",
]
GAP_RETURN_RATE_COLUMNS = ["구간", "공백시즌수", "사례수", "복귀사례", "복귀율(%)", "관측부족제외수"]
RECORD_STOP_RULE_COLUMNS = [
    "기준식",
    "복귀율기준(%)",
    "분모기준",
    "확정n",
    "근거구간",
    "근거사례수",
    "근거복귀사례",
    "근거복귀율(%)",
    "근거문장",
]
COHORT_COLUMNS = [
    "익명키",
    "성별",
    "출생연도",
    "첫대회연도",
    "첫시즌",
    "첫학년",
    "마지막시즌",
    "기록중단기준n",
    "좌측절단",
    "도달_중등",
    "도달_고등",
    "도달_대학",
    "관측충분_중등",
    "관측충분_고등",
    "관측충분_대학",
    "분석대상_중등",
    "분석대상_고등",
    "분석대상_대학",
]
COHORT_STAGE_SUMMARY_COLUMNS = [
    "분석단계",
    "목표진입학년",
    "기록중단기준n",
    "관측판정식",
    "대상N",
    "남자N",
    "여자N",
    "이미도달N",
    "관측충분미도달N",
    "좌측절단제외N",
    "사용가능시즌범위",
    "N100미만",
    "신뢰한계문구",
]
RETENTION_OVERALL_COLUMNS = [
    "지표유형",
    "기준",
    "분리기준",
    "분리값",
    "학년",
    "전환구간",
    "잔존인원",
    "잔존율(%)",
    "신규진입인원",
    "다음학년진입인원",
    "학년이탈인원",
    "학년이탈률(%)",
    "도달단계",
    "도달인원",
    "도달률(%)",
    "대상인원",
    "병합의심률(%)",
    "관측시즌범위",
    "신뢰한계문구",
]
RETENTION_BAND_COLUMNS = [
    "기준유형",
    "성별",
    "구간수",
    "백분위구간",
    "구간정렬값",
    "병합규칙",
    "표본N",
    "중등대상N",
    "중등도달N",
    "중등도달률(%)",
    "중등도달CI하한(%)",
    "중등도달CI상한(%)",
    "고등대상N",
    "고등도달N",
    "고등도달률(%)",
    "고등도달CI하한(%)",
    "고등도달CI상한(%)",
    "대학일반대상N",
    "대학일반도달N",
    "대학일반도달률(%)",
    "대학일반도달CI하한(%)",
    "대학일반도달CI상한(%)",
    "기록대비방향일치_중등",
    "기록대비방향일치_고등",
    "기록대비방향일치_대학일반",
    "신뢰한계문구",
]
IMPROVEMENT_RATE_COLUMNS = [
    "지표유형",
    "성별",
    "거리",
    "학년",
    "백분위구간",
    "표본N",
    "향상폭_p25(초)",
    "향상폭_p50(초)",
    "향상폭_p75(초)",
    "평균향상폭(초)",
    "예측단계",
    "향상속도_AUC(%)",
    "백분위_AUC(%)",
    "예측력차이(AUC%p)",
    "신뢰한계문구",
]
REVERSE_DISTRIBUTION_COLUMNS = [
    "대상그룹",
    "지표",
    "구간",
    "대상N",
    "해당N",
    "비율(%)",
    "국가대표N",
    "7번방향일치",
    "신뢰한계문구",
]
COHORT_FLAG_COLUMNS = [
    "좌측절단",
    "도달_중등",
    "도달_고등",
    "도달_대학",
    "관측충분_중등",
    "관측충분_고등",
    "관측충분_대학",
    "분석대상_중등",
    "분석대상_고등",
    "분석대상_대학",
]
PARTICIPATION_FORBIDDEN_COLUMNS = {"idNo", "이름", "소속", "시도", "BIB", "레인"}
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


def _validate_participation(repo_root):
    path = repo_root / "data" / "participation.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/participation.csv"]

    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/participation.csv가 비어 있습니다."]

        errors = []
        if header != PARTICIPATION_COLUMNS:
            errors.append(f"data/participation.csv 헤더가 기대값과 다릅니다: {header}")
            return errors

        forbidden = PARTICIPATION_FORBIDDEN_COLUMNS.intersection(header)
        if forbidden:
            errors.append(f"data/participation.csv에 금지 컬럼이 포함되었습니다: {', '.join(sorted(forbidden))}")
            return errors

        key_index = header.index("익명키")
        open_index = header.index("오픈참가")
        for row_no, row in enumerate(reader, start=2):
            if len(row) <= key_index:
                errors.append(f"data/participation.csv {row_no}행 익명키 컬럼이 누락되었습니다.")
                continue
            key = row[key_index].strip()
            if not ANON_KEY_RE.fullmatch(key):
                errors.append(f"data/participation.csv {row_no}행 익명키 형식이 올바르지 않습니다.")
            if len(row) <= open_index:
                errors.append(f"data/participation.csv {row_no}행 오픈참가 컬럼이 누락되었습니다.")
                continue
            open_value = row[open_index].strip()
            if open_value not in {"Y", "N"}:
                errors.append(f"data/participation.csv {row_no}행 오픈참가 값은 Y/N 이어야 합니다.")
        return errors


def _validate_gap_return_rates(repo_root):
    path = repo_root / "data" / "gap_return_rates.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/gap_return_rates.csv"]
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/gap_return_rates.csv가 비어 있습니다."]
    if header != GAP_RETURN_RATE_COLUMNS:
        return [f"data/gap_return_rates.csv 헤더가 기대값과 다릅니다: {header}"]
    return []


def _validate_record_stop_rule(repo_root):
    path = repo_root / "data" / "record_stop_rule.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/record_stop_rule.csv"]
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/record_stop_rule.csv가 비어 있습니다."]
    if header != RECORD_STOP_RULE_COLUMNS:
        return [f"data/record_stop_rule.csv 헤더가 기대값과 다릅니다: {header}"]
    return []


def _validate_cohort(repo_root):
    path = repo_root / "data" / "cohort.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/cohort.csv"]
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/cohort.csv가 비어 있습니다."]
        errors = []
        if header != COHORT_COLUMNS:
            errors.append(f"data/cohort.csv 헤더가 기대값과 다릅니다: {header}")
            return errors
        forbidden = PARTICIPATION_FORBIDDEN_COLUMNS.intersection(header)
        if forbidden:
            errors.append(f"data/cohort.csv에 금지 컬럼이 포함되었습니다: {', '.join(sorted(forbidden))}")
            return errors
        key_index = header.index("익명키")
        flag_indexes = {name: header.index(name) for name in COHORT_FLAG_COLUMNS}
        for row_no, row in enumerate(reader, start=2):
            if len(row) <= key_index:
                errors.append(f"data/cohort.csv {row_no}행 익명키 컬럼이 누락되었습니다.")
                continue
            key = row[key_index].strip()
            if not ANON_KEY_RE.fullmatch(key):
                errors.append(f"data/cohort.csv {row_no}행 익명키 형식이 올바르지 않습니다.")
            for name, index in flag_indexes.items():
                if len(row) <= index:
                    errors.append(f"data/cohort.csv {row_no}행 {name} 컬럼이 누락되었습니다.")
                    continue
                flag = row[index].strip()
                if flag not in {"Y", "N"}:
                    errors.append(f"data/cohort.csv {row_no}행 {name} 값은 Y/N 이어야 합니다.")
        return errors


def _validate_cohort_stage_summary(repo_root):
    path = repo_root / "data" / "cohort_stage_summary.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/cohort_stage_summary.csv"]
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/cohort_stage_summary.csv가 비어 있습니다."]
    if header != COHORT_STAGE_SUMMARY_COLUMNS:
        return [f"data/cohort_stage_summary.csv 헤더가 기대값과 다릅니다: {header}"]
    return []


def _validate_retention_overall(repo_root):
    path = repo_root / "data" / "retention_overall.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/retention_overall.csv"]
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/retention_overall.csv가 비어 있습니다."]
    if header != RETENTION_OVERALL_COLUMNS:
        return [f"data/retention_overall.csv 헤더가 기대값과 다릅니다: {header}"]
    return []


def _validate_retention_band(repo_root):
    path = repo_root / "data" / "retention_band.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/retention_band.csv"]
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/retention_band.csv가 비어 있습니다."]
    if header != RETENTION_BAND_COLUMNS:
        return [f"data/retention_band.csv 헤더가 기대값과 다릅니다: {header}"]
    return []


def _validate_improvement_rate(repo_root):
    path = repo_root / "data" / "improvement_rate.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/improvement_rate.csv"]
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/improvement_rate.csv가 비어 있습니다."]
    if header != IMPROVEMENT_RATE_COLUMNS:
        return [f"data/improvement_rate.csv 헤더가 기대값과 다릅니다: {header}"]
    return []


def _validate_reverse_distribution(repo_root):
    path = repo_root / "data" / "reverse_distribution.csv"
    if not path.exists():
        return ["필수 파일이 없습니다: data/reverse_distribution.csv"]
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/reverse_distribution.csv가 비어 있습니다."]
    if header != REVERSE_DISTRIBUTION_COLUMNS:
        return [f"data/reverse_distribution.csv 헤더가 기대값과 다릅니다: {header}"]
    return []


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
    should_validate_participation = "data/participation.csv" in paths
    if should_validate_participation:
        errors.extend(_validate_participation(repo_root))
    should_validate_gap_return_rates = "data/gap_return_rates.csv" in paths
    if should_validate_gap_return_rates:
        errors.extend(_validate_gap_return_rates(repo_root))
    should_validate_record_stop_rule = "data/record_stop_rule.csv" in paths
    if should_validate_record_stop_rule:
        errors.extend(_validate_record_stop_rule(repo_root))
    should_validate_cohort = "data/cohort.csv" in paths
    if should_validate_cohort:
        errors.extend(_validate_cohort(repo_root))
    should_validate_cohort_summary = "data/cohort_stage_summary.csv" in paths
    if should_validate_cohort_summary:
        errors.extend(_validate_cohort_stage_summary(repo_root))
    should_validate_retention_overall = "data/retention_overall.csv" in paths
    if should_validate_retention_overall:
        errors.extend(_validate_retention_overall(repo_root))
    should_validate_retention_band = "data/retention_band.csv" in paths
    if should_validate_retention_band:
        errors.extend(_validate_retention_band(repo_root))
    should_validate_improvement_rate = "data/improvement_rate.csv" in paths
    if should_validate_improvement_rate:
        errors.extend(_validate_improvement_rate(repo_root))
    should_validate_reverse_distribution = "data/reverse_distribution.csv" in paths
    if should_validate_reverse_distribution:
        errors.extend(_validate_reverse_distribution(repo_root))

    if errors:
        print("[error] 익명 데이터 커밋 정책 위반:")
        for message in errors:
            print(f"- {message}")
        sys.exit(1)

    print(f"[ok] 익명 데이터 커밋 정책 검증 통과 ({args.mode})")


if __name__ == "__main__":
    main()
