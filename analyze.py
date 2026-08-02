import pathlib
import re

import pandas as pd

DATA_DIR = pathlib.Path("data")
RECORDS_CSV = DATA_DIR / "records.csv"
ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"
CLEAN_RECORDS_CSV = DATA_DIR / "clean_records.csv"
PLACEMENTS_CSV = DATA_DIR / "placements.csv"
YOUTH_SUMMARY_CSV = DATA_DIR / "youth_summary.csv"
OUTLIERS_CSV = DATA_DIR / "outliers.csv"
COVERAGE_CSV = DATA_DIR / "coverage.csv"
AGE_MATRIX_CSV = DATA_DIR / "age_matrix.csv"
YEAR_RE = re.compile(r"(19|20)\d{2}")
DISTANCE_RE = re.compile(r"(500|1000|1500|2000|3000)M")
OUTLIER_BOUNDS = {
    500: {"초등": (42, 90), "중등이상": (40, 60)},
    1000: {"초등": (90, 180), "중등이상": (80, 120)},
    1500: {"초등": (140, 300), "중등이상": (130, 200)},
}

def parse_time_to_seconds(value):
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None

def parse_rank(value):
    match = re.search(r"\d+", str(value or "").strip())
    return int(match.group(0)) if match else None

def classify_school_level(category):
    text = str(category or "").strip()
    if not text:
        return None
    if text in {"여자부", "남자부"}:
        return "오픈"
    if "초등" in text:
        return "초등"
    if "중학" in text or "중등" in text:
        return "중등"
    if "고등" in text:
        return "고등"
    if "대학" in text:
        return "대학"
    if "일반" in text:
        return "일반"
    return None

def parse_event_detail(event_name):
    text = str(event_name or "").upper().replace(" ", "")
    match = DISTANCE_RE.search(text)
    return (int(match.group(1)) if match else None), ("S.F" in text or "SF" in text)

def classify_round(round_name):
    text = str(round_name or "").strip().replace(" ", "")
    if "채점종합" in text:
        return "채점종합"
    if text.startswith("결승B"):
        return "결승B"
    if text.startswith("결승"):
        return "결승"
    if "준준결승" in text:
        return "준준결승"
    if "준결승" in text:
        return "준결승"
    if "예선" in text:
        return "예선"
    return "기타"

def extract_meet_year(normalized_date, raw_date):
    for value in [normalized_date, raw_date]:
        text = str(value or "").strip()
        if not text:
            continue
        if len(text) >= 4 and text[:4].isdigit():
            year = int(text[:4])
            if 1900 <= year <= 2099:
                return year
        match = YEAR_RE.search(text)
        if match:
            return int(match.group(0))
    return None

def estimate_age(meet_year, birth_year):
    # 출생년도만 있어 생일 반영이 불가하며 1~2월 대회는 만 나이 대비 최대 1살 높게 추정될 수 있다.
    if pd.isna(meet_year) or pd.isna(birth_year):
        return None
    return int(meet_year) - int(birth_year)

def all_times(df):
    return df.copy()

def best_placement(df):
    group_cols = ["idNo", "이름", "대회명", "대회연도", "거리", "SF여부"]
    selected = []
    for _, group in df.groupby(group_cols, dropna=False, sort=False):
        pr = group["라운드종류"].map({"채점종합": 1, "결승": 2, "결승B": 2}).fillna(99)
        cand = group.assign(_priority=pr)
        cand = cand[cand["_priority"] < 99]
        if not cand.empty:
            selected.append(cand.sort_values("_priority").iloc[0])
    if not selected:
        return pd.DataFrame(columns=["이름", "대회연도", "나이_추정", "학령구간", "대회명", "거리", "순위", "결승구분", "기록_초"])
    placements = pd.DataFrame(selected).copy()
    placements["결승구분"] = placements["라운드종류"].map({"결승B": "B", "결승": "A", "채점종합": "종합"})
    placements["순위"] = placements["순위_정수"].astype("Int64")
    cols = ["이름", "대회연도", "나이_추정", "학령구간", "대회명", "거리", "순위", "결승구분", "기록_초"]
    return placements[cols].sort_values(["이름", "대회연도", "대회명", "거리"], na_position="last")

def build_clean_records(records_df, athlete_df):
    athlete = athlete_df.copy()
    athlete["idNo"] = athlete["idNo"].astype(str).str.strip()
    athlete["출생년도"] = pd.to_numeric(athlete["출생년도"], errors="coerce").astype("Int64")
    athlete = athlete[["idNo", "이름", "출생년도"]].drop_duplicates(subset=["idNo"], keep="first")
    records = records_df.copy()
    records["idNo"] = records["idNo"].astype(str).str.strip()
    clean = records.merge(athlete, on="idNo", how="left")
    clean["대회연도"] = pd.Series([extract_meet_year(n, r) for n, r in zip(clean["일자_정규화"], clean["일자"])], dtype="Int64")
    clean["나이_추정"] = pd.Series([estimate_age(y, b) for y, b in zip(clean["대회연도"], clean["출생년도"])], dtype="Int64")
    clean["학령구간"] = clean["종별"].apply(classify_school_level)
    parsed = clean["세부종목"].apply(parse_event_detail)
    clean["거리"] = pd.Series([p[0] for p in parsed], dtype="Int64")
    clean["SF여부"] = [p[1] for p in parsed]
    clean["기록_초"] = pd.to_numeric(clean["기록"].apply(parse_time_to_seconds), errors="coerce")
    clean["라운드종류"] = clean["라운드"].apply(classify_round)
    clean["순위_정수"] = pd.Series(clean["순위"].apply(parse_rank), dtype="Int64")
    return clean

def detect_outliers(clean_df):
    reasons = {}
    reason_counts = {"하한미달": 0, "상한초과": 0, "결승이예선보다느림": 0}

    def add_reason(index, code, detail):
        item = reasons.setdefault(index, {"codes": set(), "details": set()})
        if code not in item["codes"]:
            reason_counts[code] += 1
        item["codes"].add(code)
        item["details"].add(detail)

    for idx, row in clean_df[clean_df["기록_초"].notna()].iterrows():
        distance = row["거리"]
        if pd.isna(distance):
            continue
        distance = int(distance)
        if distance not in OUTLIER_BOUNDS:
            continue
        level_key = "초등" if row["학령구간"] == "초등" else "중등이상"
        lower, upper = OUTLIER_BOUNDS[distance][level_key]
        value = float(row["기록_초"])
        if value < lower:
            add_reason(idx, "하한미달", f"{distance}M {level_key} 기준 하한미달({value:.3f} < {lower})")
        if value > upper:
            add_reason(idx, "상한초과", f"{distance}M {level_key} 기준 상한초과({value:.3f} > {upper})")
    groups = all_times(clean_df).groupby(["idNo", "대회명", "대회연도", "거리", "SF여부"], dropna=False)
    for _, group in groups:
        prelim = group[(group["라운드종류"] == "예선") & group["기록_초"].notna()]
        finals = group[group["라운드종류"].isin(["채점종합", "결승", "결승B"]) & group["기록_초"].notna()]
        if prelim.empty or finals.empty:
            continue
        prelim_best = prelim["기록_초"].min()
        for idx, row in finals.iterrows():
            if row["기록_초"] - prelim_best >= 3:
                add_reason(
                    idx,
                    "결승이예선보다느림",
                    f"결승이 예선보다 3초+ 느림(예선 {prelim_best:.3f}, 결승 {row['기록_초']:.3f})",
                )
    if not reasons:
        outliers = clean_df.iloc[0:0].copy()
        outliers["사유"] = pd.Series(dtype=str)
        outliers["이상치사유"] = pd.Series(dtype=str)
        return outliers, reason_counts
    outliers = clean_df.loc[sorted(reasons.keys())].copy()
    outliers["사유"] = [", ".join(sorted(reasons[idx]["codes"])) for idx in outliers.index]
    outliers["이상치사유"] = [", ".join(sorted(reasons[idx]["details"])) for idx in outliers.index]
    return outliers, reason_counts

def youth_data_reliability(sixth_grade_year):
    if pd.isna(sixth_grade_year):
        return None
    year = int(sixth_grade_year)
    if year >= 2014:
        return "high"
    if year >= 2012:
        return "medium"
    return "low"

def build_coverage(clean_df):
    year_known = clean_df[clean_df["대회연도"].notna()].copy()
    if year_known.empty:
        return pd.DataFrame(columns=["대회연도", "기록건수", "고유선수수", "고유대회수"])
    year_known["idNo_유효"] = year_known["idNo"].astype(str).str.strip().replace("", pd.NA)
    year_known["대회명_유효"] = year_known["대회명"].astype(str).str.strip().replace("", pd.NA)
    coverage = year_known.groupby("대회연도", dropna=False).agg(
        기록건수=("idNo", "size"), 고유선수수=("idNo_유효", "nunique"), 고유대회수=("대회명_유효", "nunique")
    ).reset_index().sort_values("대회연도")
    for col in ["대회연도", "기록건수", "고유선수수", "고유대회수"]:
        coverage[col] = coverage[col].astype("Int64")
    return coverage

def build_age_matrix(placements_df, names):
    ages = list(range(7, 19))
    base = placements_df[
        placements_df["순위"].notna() & placements_df["나이_추정"].notna() & placements_df["나이_추정"].between(7, 18)
    ].copy()
    pivot = base.pivot_table(index="이름", columns="나이_추정", values="순위", aggfunc="min")
    pivot = pivot.reindex(index=sorted(names), columns=ages)
    matrix = pivot.reset_index()
    matrix.columns = ["이름"] + [str(age) for age in ages]
    for col in [str(age) for age in ages]:
        matrix[col] = matrix[col].apply(lambda x: "" if pd.isna(x) else int(x))
    return matrix

def summarize_youth(placements_df, clean_df, athlete_df):
    placement = placements_df.copy()
    athlete_base = athlete_df.copy()
    athlete_base["출생년도"] = pd.to_numeric(athlete_base["출생년도"], errors="coerce").astype("Int64")
    athlete_names = {n.strip() for n in athlete_base["이름"].astype(str).tolist() if n and str(n).strip()}
    birth_map = {name: int(group["출생년도"].iloc[0]) for name, group in athlete_base[athlete_base["출생년도"].notna()].groupby("이름")}
    record_names = {n.strip() for n in clean_df["이름"].astype(str).tolist() if n and str(n).strip()}
    rows = []
    for name in sorted(athlete_names | record_names):
        person_records = clean_df[clean_df["이름"] == name]
        person_placements = placement[placement["이름"] == name]
        first_year, first_age = None, None
        years = person_records["대회연도"].dropna()
        if not years.empty:
            first_year = int(years.min())
            ages = person_records[person_records["대회연도"] == first_year]["나이_추정"].dropna()
            if not ages.empty:
                first_age = int(ages.min())
        birth_values = person_records["출생년도"].dropna()
        birth_year = int(birth_values.iloc[0]) if not birth_values.empty else birth_map.get(name)
        sixth_grade_year = birth_year + 12 if birth_year is not None else None

        def level_stats(level):
            data = person_placements[(person_placements["학령구간"] == level) & person_placements["순위"].notna()]
            if data.empty:
                return None, None, 0
            return int(data["순위"].min()), int(data["순위"].max()), int(len(data))

        def age_ranks(age):
            ranks = person_placements[(person_placements["나이_추정"] == age) & person_placements["순위"].notna()]["순위"].astype(int).tolist()
            return ",".join(str(v) for v in ranks)

        elem_best, elem_worst, elem_count = level_stats("초등")
        mid_best, _, mid_count = level_stats("중등")
        high_best, _, high_count = level_stats("고등")
        rows.append({"이름": name, "최초_출전연도": first_year, "최초_출전나이": first_age, "초등부_최고순위": elem_best, "초등부_최저순위": elem_worst, "초등부_출전수": elem_count, "중등부_최고순위": mid_best, "중등부_출전수": mid_count, "고등부_최고순위": high_best, "고등부_출전수": high_count, "초등6학년_추정연도": sixth_grade_year, "유년기_데이터신뢰도": youth_data_reliability(sixth_grade_year), "나이10_순위목록": age_ranks(10), "나이12_순위목록": age_ranks(12), "나이14_순위목록": age_ranks(14)})
    summary = pd.DataFrame(rows)
    for col in ["최초_출전연도", "최초_출전나이", "초등부_최고순위", "초등부_최저순위", "초등부_출전수", "중등부_최고순위", "중등부_출전수", "고등부_최고순위", "고등부_출전수", "초등6학년_추정연도"]:
        summary[col] = pd.Series(summary[col], dtype="Int64")
    return summary.sort_values("이름")

def print_console(summary_df, placements_df):
    print("주의: 나이_추정은 대회연도-출생년도이며 만 나이보다 최대 1살 높습니다. 동계 대회(1~2월) 집중으로 다수 행에서 체계적으로 +1 편향이 생길 수 있습니다.")
    print("이름 | 최초출전나이 | 초등부 최고·최저순위 | 출전수")
    for _, row in summary_df.iterrows():
        best = "-" if pd.isna(row["초등부_최고순위"]) else str(int(row["초등부_최고순위"]))
        worst = "-" if pd.isna(row["초등부_최저순위"]) else str(int(row["초등부_최저순위"]))
        first_age = "-" if pd.isna(row["최초_출전나이"]) else str(int(row["최초_출전나이"]))
        count = int(row["초등부_출전수"]) if not pd.isna(row["초등부_출전수"]) else 0
        print(f"{row['이름']} | {first_age} | {best}·{worst} | {count}")
    total = len(summary_df)
    outside = int((summary_df["초등부_최저순위"] > 10).fillna(False).sum())
    overall_ratio = (outside / total * 100) if total else 0.0
    print(f"초등부에서 10위 밖 성적이 있었던 선수: {outside}명 / 전체 {total}명")
    print(f"초등부 10위 밖 경험 비율(전체): {outside}/{total} ({overall_ratio:.1f}%)")
    reliable = summary_df[summary_df["유년기_데이터신뢰도"].isin(["high", "medium"])]
    reliable_total = len(reliable)
    reliable_outside = int((reliable["초등부_최저순위"] > 10).fillna(False).sum())
    reliable_ratio = (reliable_outside / reliable_total * 100) if reliable_total else 0.0
    print(f"유년기 데이터 신뢰 가능(high/medium) 선수: {reliable_total}명")
    print(f"초등부 10위 밖 경험 비율(high/medium): {reliable_outside}/{reliable_total} ({reliable_ratio:.1f}%)")
    no_elementary = summary_df[summary_df["초등부_출전수"] == 0]["이름"].tolist()
    print(f"초등부 기록이 아예 없는 선수: [{', '.join(no_elementary)}]")
    age_data = placements_df[placements_df["순위"].notna() & placements_df["나이_추정"].notna()].copy()
    print("나이별 순위 분포 요약")
    for age in range(8, 15):
        age_rows = age_data[age_data["나이_추정"] == age]
        rank_count = len(age_rows)
        athlete_count = int(age_rows["이름"].nunique()) if rank_count else 0
        if rank_count == 0:
            print(f"{age}세: 성적 0건 / 선수 0명 / 없음")
        else:
            ranks = age_rows["순위"].astype(int).tolist()
            median = pd.Series(ranks).median()
            spread = f"중앙값 {median:.1f} / 범위 {min(ranks)}~{max(ranks)}"
            if athlete_count < 5:
                print(f"{age}세: 성적 {rank_count}건 / 선수 {athlete_count}명 / 표본 부족 ({spread})")
            else:
                print(f"{age}세: 성적 {rank_count}건 / 선수 {athlete_count}명 / {spread}")
    print("나이 구간별로 포함된 선수가 다르므로 나이 간 직접 비교는 부적절함")

def main():
    if not RECORDS_CSV.exists() or not ATHLETE_INFO_CSV.exists():
        print("[error] data/records.csv 또는 data/athlete_info.csv 파일이 없습니다.")
        return
    records_df = pd.read_csv(RECORDS_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    athlete_df = pd.read_csv(ATHLETE_INFO_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    clean_df = build_clean_records(records_df, athlete_df)
    placements_df = best_placement(clean_df)
    summary_df = summarize_youth(placements_df, clean_df, athlete_df)
    outliers_df, outlier_reason_counts = detect_outliers(clean_df)
    coverage_df = build_coverage(clean_df)
    age_matrix_df = build_age_matrix(placements_df, summary_df["이름"].astype(str).tolist())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean_df.to_csv(CLEAN_RECORDS_CSV, index=False, encoding="utf-8-sig")
    placements_df.to_csv(PLACEMENTS_CSV, index=False, encoding="utf-8-sig")
    summary_df.to_csv(YOUTH_SUMMARY_CSV, index=False, encoding="utf-8-sig")
    outliers_df.to_csv(OUTLIERS_CSV, index=False, encoding="utf-8-sig")
    coverage_df.to_csv(COVERAGE_CSV, index=False, encoding="utf-8-sig")
    age_matrix_df.to_csv(AGE_MATRIX_CSV, index=False, encoding="utf-8-sig")
    print_console(summary_df, placements_df)
    print(f"데이터 커버리지 저장 완료: data/coverage.csv ({int(coverage_df['대회연도'].min())}~{int(coverage_df['대회연도'].max())})" if not coverage_df.empty else "데이터 커버리지 저장 완료: data/coverage.csv (연도 정보 없음)")
    print(f"이상치 사유별 건수: 하한미달 {outlier_reason_counts['하한미달']}건 / 상한초과 {outlier_reason_counts['상한초과']}건 / 결승이예선보다느림 {outlier_reason_counts['결승이예선보다느림']}건")
    print(f"이상치 {len(outliers_df)}건 검출 (data/outliers.csv)")


if __name__ == "__main__":
    main()
