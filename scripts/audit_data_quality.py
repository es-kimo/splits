"""익명 통계 산출물의 품질을 점검합니다.

records_anon.csv / stats_distribution.csv / site/data/distribution.json 만 읽으므로
원천 데이터나 SALT 없이도 실행할 수 있습니다.

    python3 scripts/audit_data_quality.py
    python3 scripts/audit_data_quality.py --strict   # 경고도 실패로 처리
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyze import (  # noqa: E402
    DIST_RANK_COLS,
    DIST_TIME_COLS,
    INSUFFICIENT_TEXT,
    K_ANONYMITY_MIN,
    STATS_TIME_LOWER_BOUNDS,
)

DATA_DIR = Path("data")
RECORDS_ANON_CSV = DATA_DIR / "records_anon.csv"
STATS_DISTRIBUTION_CSV = DATA_DIR / "stats_distribution.csv"
DISTRIBUTION_JSON = Path("site/data/distribution.json")

ANON_KEY_RE = re.compile(r"^[0-9a-f]{12}$")
FORBIDDEN_COLUMNS = {"idNo", "이름", "소속", "시도", "BIB", "레인"}
VALID_CLASS_CD = {"1", "2", "3"}

# 도메인 상식 상한(초). 이보다 느리면 기록 파싱 오류를 의심한다.
TIME_UPPER_SANITY = {500: 200, 1000: 400, 1500: 600, 2000: 800, 3000: 1200}
# 세계기록 근사치(초). 이보다 빠르면 종목 오염이나 입력 오류다.
WORLD_RECORD_FLOOR = {500: 39.0, 1000: 80.0, 1500: 126.0, 2000: 170.0, 3000: 260.0}

TIME_PERCENTILES = [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95]


class Report:
    def __init__(self):
        self.results = []

    def add(self, section, name, status, detail=""):
        self.results.append((section, name, status, detail))

    def ok(self, section, name, detail=""):
        self.add(section, name, "PASS", detail)

    def warn(self, section, name, detail=""):
        self.add(section, name, "WARN", detail)

    def fail(self, section, name, detail=""):
        self.add(section, name, "FAIL", detail)

    def counts(self):
        summary = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for _, _, status, _ in self.results:
            summary[status] += 1
        return summary

    def render(self):
        marks = {"PASS": "[ok]  ", "WARN": "[warn]", "FAIL": "[FAIL]"}
        current = None
        lines = []
        for section, name, status, detail in self.results:
            if section != current:
                lines.append("")
                lines.append(f"## {section}")
                current = section
            line = f"  {marks[status]} {name}"
            if detail:
                line += f" — {detail}"
            lines.append(line)
        return "\n".join(lines)


def _read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {path}")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _numeric(series):
    return pd.to_numeric(series.replace(INSUFFICIENT_TEXT, pd.NA), errors="coerce")


def _public_rows(stats, count_col):
    return stats[stats[count_col].astype(str).str.strip() != INSUFFICIENT_TEXT].copy()


def check_schema(report, records, stats):
    section = "1. 스키마 및 개인정보"

    leaked = sorted(FORBIDDEN_COLUMNS.intersection(records.columns))
    if leaked:
        report.fail(section, "금지 컬럼 부재", f"발견: {', '.join(leaked)}")
    else:
        report.ok(section, "금지 컬럼 부재", "idNo/이름/소속/시도/BIB/레인 없음")

    bad_keys = records[~records["익명키"].astype(str).str.match(ANON_KEY_RE)]
    if len(bad_keys):
        report.fail(section, "익명키 형식", f"규격 위반 {len(bad_keys):,}행")
    else:
        unique_keys = records["익명키"].nunique()
        report.ok(section, "익명키 형식", f"12자리 hex, 고유 {unique_keys:,}개")

    bad_class = records[~records["classCd"].astype(str).isin(VALID_CLASS_CD)]
    if len(bad_class):
        report.fail(section, "classCd 도메인", f"허용 외 값 {len(bad_class):,}행")
    else:
        dist = records["classCd"].value_counts().to_dict()
        report.ok(section, "classCd 도메인", f"분포 {dist}")

    dup_cols = ["익명키", "대회명", "대회연도", "일자", "거리", "라운드", "순위", "기록_초"]
    dup = int(records.duplicated(subset=dup_cols).sum())
    if dup:
        report.warn(section, "중복 레코드", f"{dup:,}행이 동일 키로 중복")
    else:
        report.ok(section, "중복 레코드", "없음")

    key_cols = ["출생연도", "성별", "거리"]
    stats_dup = int(stats.duplicated(subset=key_cols).sum())
    if stats_dup:
        report.fail(section, "통계 키 유일성", f"중복 키 {stats_dup}건")
    else:
        report.ok(section, "통계 키 유일성", f"{len(stats):,}개 조합 모두 유일")


def check_k_anonymity(report, stats):
    section = "2. k-익명성"

    for label, count_col, metric_cols in (
        ("기록", "기록_인원수", DIST_TIME_COLS),
        ("순위", "순위_인원수", DIST_RANK_COLS),
    ):
        public = _public_rows(stats, count_col)
        counts = _numeric(public[count_col])
        violations = int((counts < K_ANONYMITY_MIN).sum())
        if violations:
            report.fail(section, f"{label} 통계 k>={K_ANONYMITY_MIN}", f"위반 {violations}건")
        else:
            report.ok(
                section,
                f"{label} 통계 k>={K_ANONYMITY_MIN}",
                f"공개 {len(public)}행, 최소 인원수 {int(counts.min()) if len(counts) else 0}",
            )

        masked = stats[stats[count_col].astype(str).str.strip() == INSUFFICIENT_TEXT]
        leaked = 0
        for col in metric_cols:
            leaked += int((masked[col].astype(str).str.strip() != INSUFFICIENT_TEXT).sum())
        if leaked:
            report.fail(section, f"{label} 마스킹 일관성", f"인원수는 가렸으나 지표가 노출된 셀 {leaked}개")
        else:
            report.ok(section, f"{label} 마스킹 일관성", f"비공개 {len(masked)}행 전부 마스킹")


def check_monotonicity(report, stats):
    section = "3. 분위수 단조성"

    public = _public_rows(stats, "기록_인원수")
    violations = []
    for _, row in public.iterrows():
        values = [float(row[col]) for col in DIST_TIME_COLS]
        if any(b < a for a, b in zip(values, values[1:])):
            violations.append(f"{row['출생연도']}/{row['성별']}/{row['거리']}m")
    if violations:
        report.fail(section, "기록 p05<=...<=p95", f"{len(violations)}건: {', '.join(violations[:3])}")
    else:
        report.ok(section, "기록 p05<=...<=p95", f"{len(public)}행 모두 단조 증가")

    public_rank = _public_rows(stats, "순위_인원수")
    rank_violations = []
    below_one = 0
    for _, row in public_rank.iterrows():
        values = [float(row[col]) for col in DIST_RANK_COLS]
        if any(b < a for a, b in zip(values, values[1:])):
            rank_violations.append(f"{row['출생연도']}/{row['성별']}/{row['거리']}m")
        if min(values) < 1:
            below_one += 1
    if rank_violations:
        report.fail(section, "순위 p25<=p50<=p75", f"{len(rank_violations)}건")
    else:
        report.ok(section, "순위 p25<=p50<=p75", f"{len(public_rank)}행 모두 단조 증가")

    if below_one:
        report.fail(section, "순위 하한(>=1)", f"{below_one}행이 1 미만")
    else:
        report.ok(section, "순위 하한(>=1)", "위반 없음")


def check_physical_plausibility(report, stats):
    section = "4. 물리적 타당성"

    public = _public_rows(stats, "기록_인원수")
    too_fast = []
    too_slow = []
    below_wr = []
    for _, row in public.iterrows():
        distance = int(row["거리"])
        fastest = float(row["기록_p05"])
        slowest = float(row["기록_p95"])
        label = f"{row['출생연도']}/{row['성별']}/{distance}m"
        if distance in STATS_TIME_LOWER_BOUNDS and fastest < STATS_TIME_LOWER_BOUNDS[distance]:
            too_fast.append(f"{label} p05={fastest}")
        if distance in WORLD_RECORD_FLOOR and fastest < WORLD_RECORD_FLOOR[distance]:
            below_wr.append(f"{label} p05={fastest}")
        if distance in TIME_UPPER_SANITY and slowest > TIME_UPPER_SANITY[distance]:
            too_slow.append(f"{label} p95={slowest}")

    if too_fast:
        report.fail(section, "이상치 하한 적용", f"{len(too_fast)}건: {', '.join(too_fast[:3])}")
    else:
        report.ok(section, "이상치 하한 적용", "하한 미만 기록이 통계에 남아있지 않음")

    if below_wr:
        report.warn(section, "세계기록 근사 하한", f"{len(below_wr)}건 의심: {', '.join(below_wr[:3])}")
    else:
        report.ok(section, "세계기록 근사 하한", "세계기록보다 빠른 분위수 없음")

    if too_slow:
        report.warn(section, "상식적 상한", f"{len(too_slow)}건: {', '.join(too_slow[:3])}")
    else:
        report.ok(section, "상식적 상한", "비현실적으로 느린 분위수 없음")


def check_cross_distance(report, stats):
    section = "5. 거리 간 정합성"

    public = _public_rows(stats, "기록_인원수")
    if public.empty:
        report.warn(section, "거리별 기록 순서", "공개 표본이 없어 검사 불가")
        return

    public = public.assign(
        거리=public["거리"].astype(int),
        p50=_numeric(public["기록_p50"]),
    )
    violations = []
    checked = 0
    for (birth, gender), group in public.groupby(["출생연도", "성별"]):
        by_distance = group.set_index("거리")["p50"].to_dict()
        distances = sorted(by_distance)
        for shorter, longer in zip(distances, distances[1:]):
            checked += 1
            if by_distance[shorter] >= by_distance[longer]:
                violations.append(f"{birth}/{gender} {shorter}m>={longer}m")
    if violations:
        report.warn(section, "짧은 거리가 더 빠름", f"{len(violations)}/{checked}쌍 위반: {', '.join(violations[:3])}")
    else:
        report.ok(section, "짧은 거리가 더 빠름", f"{checked}쌍 모두 정상")

    speeds = []
    for _, row in public.iterrows():
        distance = int(row["거리"])
        p50 = float(row["기록_p50"])
        if p50 > 0:
            speeds.append((distance / p50, f"{row['출생연도']}/{row['성별']}/{distance}m"))
    unrealistic = [label for speed, label in speeds if speed > 13.0 or speed < 2.5]
    if unrealistic:
        report.warn(section, "평균 속도(2.5~13 m/s)", f"{len(unrealistic)}건: {', '.join(unrealistic[:3])}")
    else:
        fastest = max(speeds)[0] if speeds else 0
        report.ok(section, "평균 속도(2.5~13 m/s)", f"최고 중앙값 속도 {fastest:.1f} m/s")


def check_known_signals(report, stats):
    """데이터가 실제 신호를 담고 있는지 확인한다. 알려진 사실을 재현하지 못하면 집계가 의심스럽다."""
    section = "6. 도메인 신호 재현"

    public = _public_rows(stats, "기록_인원수").assign(
        거리=lambda d: d["거리"].astype(int),
        출생연도=lambda d: d["출생연도"].astype(int),
        p50=lambda d: _numeric(d["기록_p50"]),
    )

    male_faster = 0
    female_faster = 0
    for (birth, distance), group in public.groupby(["출생연도", "거리"]):
        by_gender = group.set_index("성별")["p50"].to_dict()
        if "남" in by_gender and "여" in by_gender:
            if by_gender["남"] < by_gender["여"]:
                male_faster += 1
            else:
                female_faster += 1
    total_pairs = male_faster + female_faster
    if total_pairs == 0:
        report.warn(section, "성별 기록 차이", "비교 가능한 쌍이 없음")
    else:
        ratio = male_faster / total_pairs
        detail = f"남자가 빠른 비율 {ratio:.0%} ({male_faster}/{total_pairs})"
        if ratio >= 0.8:
            report.ok(section, "성별 기록 차이", detail)
        else:
            report.warn(section, "성별 기록 차이", detail + " — 기대치 80% 미만")

    growth_ok = 0
    growth_bad = 0
    for (gender, distance), group in public.groupby(["성별", "거리"]):
        youth = group[(group["출생연도"] >= 2006) & (group["출생연도"] <= 2018)]
        if len(youth) < 4:
            continue
        correlation = youth["출생연도"].corr(youth["p50"])
        if pd.isna(correlation):
            continue
        if correlation > 0:
            growth_ok += 1
        else:
            growth_bad += 1
    total_curves = growth_ok + growth_bad
    if total_curves == 0:
        report.warn(section, "성장 곡선(어릴수록 느림)", "검사 가능한 곡선이 없음")
    else:
        ratio = growth_ok / total_curves
        detail = f"기대 방향 {ratio:.0%} ({growth_ok}/{total_curves} 곡선)"
        if ratio >= 0.8:
            report.ok(section, "성장 곡선(어릴수록 느림)", detail)
        else:
            report.warn(section, "성장 곡선(어릴수록 느림)", detail + " — 기대치 80% 미만")


def check_stability(report, stats):
    section = "7. 표본 안정성"

    public = _public_rows(stats, "기록_인원수").assign(
        거리=lambda d: d["거리"].astype(int),
        출생연도=lambda d: d["출생연도"].astype(int),
        p50=lambda d: _numeric(d["기록_p50"]),
    )
    jumps = []
    for (gender, distance), group in public.groupby(["성별", "거리"]):
        ordered = group.sort_values("출생연도")
        rows = ordered[["출생연도", "p50"]].values.tolist()
        for (year_a, value_a), (year_b, value_b) in zip(rows, rows[1:]):
            if year_b - year_a != 1 or not value_a:
                continue
            change = abs(value_b - value_a) / value_a
            if change > 0.15:
                jumps.append(f"{gender}/{distance}m {year_a}->{year_b} {change:.0%}")
    if jumps:
        report.warn(section, "인접 출생연도 중앙값 급변(>15%)", f"{len(jumps)}건: {', '.join(jumps[:3])}")
    else:
        report.ok(section, "인접 출생연도 중앙값 급변(>15%)", "없음")

    counts = _numeric(_public_rows(stats, "기록_인원수")["기록_인원수"])
    if len(counts):
        thin = int((counts < 20).sum())
        report.ok(
            section,
            "공개 셀 표본 크기",
            f"중앙값 {int(counts.median())}명, 최대 {int(counts.max())}명, 20명 미만 {thin}개 셀",
        )


def check_consistency_with_json(report, stats):
    section = "8. 산출물 정합성"

    if not DISTRIBUTION_JSON.exists():
        report.warn(section, "distribution.json 존재", "파일 없음 — 사이트 산출물 미생성")
        return

    doc = json.loads(DISTRIBUTION_JSON.read_text(encoding="utf-8"))
    rows = doc.get("rows", [])
    if len(rows) != len(stats):
        report.fail(section, "행 수 일치", f"csv {len(stats)} vs json {len(rows)}")
    else:
        report.ok(section, "행 수 일치", f"{len(rows)}행")

    csv_keys = {(str(r["출생연도"]), r["성별"], str(r["거리"])) for _, r in stats.iterrows()}
    json_keys = {(str(r["birthYear"]), r["gender"], str(r["distance"])) for r in rows}
    if csv_keys != json_keys:
        missing = len(csv_keys - json_keys)
        extra = len(json_keys - csv_keys)
        report.fail(section, "키 집합 일치", f"csv에만 {missing}건, json에만 {extra}건")
    else:
        report.ok(section, "키 집합 일치", "동일")

    mismatch = 0
    csv_lookup = {
        (str(r["출생연도"]), r["성별"], str(r["거리"])): r for _, r in stats.iterrows()
    }
    for row in rows:
        key = (str(row["birthYear"]), row["gender"], str(row["distance"]))
        source = csv_lookup.get(key)
        if source is None:
            continue
        csv_value = str(source["기록_p50"]).strip()
        json_value = row.get("timeP50")
        if csv_value == INSUFFICIENT_TEXT:
            if json_value is not None:
                mismatch += 1
        elif json_value is None or abs(float(csv_value) - float(json_value)) > 1e-6:
            mismatch += 1
    if mismatch:
        report.fail(section, "지표 값 일치(p50 표본)", f"{mismatch}건 불일치")
    else:
        report.ok(section, "지표 값 일치(p50 표본)", "전부 일치")

    filters = doc.get("filters", {})
    if "schoolLevels" in filters:
        report.fail(section, "구 스키마 잔재", "filters.schoolLevels가 남아 있음")
    else:
        report.ok(section, "구 스키마 잔재", "학령구간 축 제거 확인")


def check_coverage(report, records, stats):
    section = "9. 커버리지 및 응답률"

    shorttrack = records[records["classCd"] == "2"]
    for column in ("출생연도", "거리", "성별", "기록_초"):
        blank = int((shorttrack[column].astype(str).str.strip() == "").sum())
        ratio = blank / len(shorttrack) if len(shorttrack) else 0
        detail = f"{blank:,}행 ({ratio:.1%})"
        if ratio > 0.10:
            report.warn(section, f"쇼트트랙 {column} 결측", detail)
        else:
            report.ok(section, f"쇼트트랙 {column} 결측", detail)

    time_public = len(_public_rows(stats, "기록_인원수"))
    rank_public = len(_public_rows(stats, "순위_인원수"))
    total = len(stats)
    report.ok(
        section,
        "공개 가능 조합 비율",
        f"기록 {time_public}/{total} ({time_public / total:.0%}), 순위 {rank_public}/{total} ({rank_public / total:.0%})",
    )

    exact = set()
    for _, row in stats.iterrows():
        if str(row["기록_인원수"]).strip() != INSUFFICIENT_TEXT:
            exact.add((int(row["출생연도"]), row["성별"], int(row["거리"])))
    all_keys = {(int(r["출생연도"]), r["성별"], int(r["거리"])) for _, r in stats.iterrows()}

    def answerable(key, window):
        birth, gender, distance = key
        return any((birth + offset, gender, distance) in exact for offset in range(-window, window + 1))

    for window in (0, 1, 2):
        answered = sum(1 for key in all_keys if answerable(key, window))
        label = "정확 매칭" if window == 0 else f"출생연도 ±{window} 폴백"
        report.ok(section, label, f"{answered}/{len(all_keys)} ({answered / len(all_keys):.0%})")

    youth = {key for key in all_keys if 2006 <= key[0] <= 2018}
    if youth:
        answered = sum(1 for key in youth if answerable(key, 2))
        report.ok(
            section,
            "학령기(2006~2018년생) ±2 응답률",
            f"{answered}/{len(youth)} ({answered / len(youth):.0%})",
        )


def check_row_generation_policy(report, records, stats):
    section = "10. 행 생성 정책"

    shorttrack = records[records["classCd"] == "2"].copy()
    observed = set()
    for _, row in shorttrack.iterrows():
        birth = str(row["출생연도"]).strip()
        gender = str(row["성별"]).strip()
        distance = str(row["거리"]).strip()
        if birth and gender and distance:
            observed.add((birth, gender, distance))

    stats_keys = {
        (str(r["출생연도"]).strip(), str(r["성별"]).strip(), str(r["거리"]).strip())
        for _, r in stats.iterrows()
    }
    phantom = stats_keys - observed
    if phantom:
        report.fail(section, "빈 조합 미생성", f"원천에 없는 조합 {len(phantom)}건")
    else:
        report.ok(section, "빈 조합 미생성", f"{len(stats_keys)}개 조합 모두 원천에 존재")

    both_insufficient = stats[
        (stats["기록_인원수"].astype(str).str.strip() == INSUFFICIENT_TEXT)
        & (stats["순위_인원수"].astype(str).str.strip() == INSUFFICIENT_TEXT)
    ]
    ratio = len(both_insufficient) / len(stats) if len(stats) else 0
    detail = f"{len(both_insufficient)}/{len(stats)} ({ratio:.0%})"
    if ratio > 0.6:
        report.warn(section, "양쪽 모두 비공개인 행", detail + " — 소비자 입장에서 잡음")
    else:
        report.ok(section, "양쪽 모두 비공개인 행", detail)


def main():
    parser = argparse.ArgumentParser(description="익명 통계 산출물 품질 점검")
    parser.add_argument("--strict", action="store_true", help="WARN도 실패로 처리")
    args = parser.parse_args()

    records = _read_csv(RECORDS_ANON_CSV)
    stats = _read_csv(STATS_DISTRIBUTION_CSV)

    report = Report()
    check_schema(report, records, stats)
    check_k_anonymity(report, stats)
    check_monotonicity(report, stats)
    check_physical_plausibility(report, stats)
    check_cross_distance(report, stats)
    check_known_signals(report, stats)
    check_stability(report, stats)
    check_consistency_with_json(report, stats)
    check_coverage(report, records, stats)
    check_row_generation_policy(report, records, stats)

    print("=" * 72)
    print("익명 통계 품질 점검")
    print("=" * 72)
    print(report.render())

    summary = report.counts()
    print()
    print("-" * 72)
    print(f"PASS {summary['PASS']} / WARN {summary['WARN']} / FAIL {summary['FAIL']}")

    if summary["FAIL"]:
        return 1
    if args.strict and summary["WARN"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
