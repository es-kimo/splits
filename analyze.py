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
YEAR_RE = re.compile(r"(19|20)\d{2}")
DISTANCE_RE = re.compile(r"(500|1000|1500|2000|3000)M")


def parse_time_to_seconds(value):
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
    except ValueError:
        return None
    return None


def parse_rank(value):
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\d+", text)
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
    distance = int(match.group(1)) if match else None
    is_sf = "S.F" in text or "SF" in text
    return distance, is_sf


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
    candidates = [normalized_date, raw_date]
    for value in candidates:
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
    selected_rows = []
    for _, group in df.groupby(group_cols, dropna=False, sort=False):
        priorities = group["라운드종류"].map({"채점종합": 1, "결승": 2, "결승B": 2}).fillna(99)
        candidates = group.assign(_priority=priorities)
        candidates = candidates[candidates["_priority"] < 99]
        if candidates.empty:
            continue
        selected_rows.append(candidates.sort_values(["_priority"]).iloc[0])
    if not selected_rows:
        return pd.DataFrame(
            columns=[
                "이름",
                "대회연도",
                "나이_추정",
                "학령구간",
                "대회명",
                "거리",
                "순위",
                "결승구분",
                "기록_초",
            ]
        )
    placements = pd.DataFrame(selected_rows).copy()
    placements["결승구분"] = placements["라운드종류"].map(
        {"결승B": "B", "결승": "A", "채점종합": "종합"}
    )
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
    clean["대회연도"] = [extract_meet_year(n, r) for n, r in zip(clean["일자_정규화"], clean["일자"])]
    clean["대회연도"] = pd.Series(clean["대회연도"], dtype="Int64")
    clean["나이_추정"] = [estimate_age(y, b) for y, b in zip(clean["대회연도"], clean["출생년도"])]
    clean["나이_추정"] = pd.Series(clean["나이_추정"], dtype="Int64")
    clean["학령구간"] = clean["종별"].apply(classify_school_level)
    parsed_events = clean["세부종목"].apply(parse_event_detail)
    clean["거리"] = pd.Series([p[0] for p in parsed_events], dtype="Int64")
    clean["SF여부"] = [p[1] for p in parsed_events]
    clean["기록_초"] = pd.to_numeric(clean["기록"].apply(parse_time_to_seconds), errors="coerce")
    clean["라운드종류"] = clean["라운드"].apply(classify_round)
    clean["순위_정수"] = pd.Series(clean["순위"].apply(parse_rank), dtype="Int64")
    return clean


def detect_outliers(clean_df):
    reasons = {}

    def add_reason(index, reason):
        reasons.setdefault(index, set()).add(reason)

    base = clean_df["기록_초"].notna()
    mask_500 = base & clean_df["거리"].eq(500) & ((clean_df["기록_초"] < 40) | (clean_df["기록_초"] > 60))
    mask_1000 = base & clean_df["거리"].eq(1000) & (clean_df["기록_초"] < 80)
    mask_1500 = base & clean_df["거리"].eq(1500) & (clean_df["기록_초"] < 130)
    for index in clean_df[mask_500].index:
        add_reason(index, "500M 기록 범위 이탈(<40 또는 >60)")
    for index in clean_df[mask_1000].index:
        add_reason(index, "1000M 80초 미만")
    for index in clean_df[mask_1500].index:
        add_reason(index, "1500M 130초 미만")

    grouped = all_times(clean_df).groupby(["idNo", "대회명", "대회연도", "거리", "SF여부"], dropna=False)
    for _, group in grouped:
        prelim = group[(group["라운드종류"] == "예선") & group["기록_초"].notna()]
        finals = group[group["라운드종류"].isin(["채점종합", "결승", "결승B"]) & group["기록_초"].notna()]
        if prelim.empty or finals.empty:
            continue
        prelim_best = prelim["기록_초"].min()
        for final_idx, final_row in finals.iterrows():
            if final_row["기록_초"] - prelim_best >= 3:
                add_reason(
                    final_idx,
                    f"결승이 예선보다 3초+ 느림(예선 {prelim_best:.3f}, 결승 {final_row['기록_초']:.3f})",
                )

    if not reasons:
        return clean_df.iloc[0:0].copy()
    outliers = clean_df.loc[sorted(reasons.keys())].copy()
    outliers["이상치사유"] = [", ".join(sorted(reasons[i])) for i in outliers.index]
    return outliers


def summarize_youth(placements_df, clean_df, athlete_df):
    placement = placements_df.copy()
    athlete_names = {name.strip() for name in athlete_df["이름"].astype(str).tolist() if name and str(name).strip()}
    record_names = {name.strip() for name in clean_df["이름"].astype(str).tolist() if name and str(name).strip()}
    names = athlete_names | record_names
    rows = []
    for name in sorted(names):
        person_records = clean_df[clean_df["이름"] == name]
        person_placements = placement[placement["이름"] == name]
        first_year = None
        first_age = None
        if not person_records.empty:
            year_values = person_records["대회연도"].dropna()
            if not year_values.empty:
                first_year = int(year_values.min())
                ages = person_records[person_records["대회연도"] == first_year]["나이_추정"].dropna()
                if not ages.empty:
                    first_age = int(ages.min())

        def level_stats(level):
            data = person_placements[(person_placements["학령구간"] == level) & person_placements["순위"].notna()]
            if data.empty:
                return None, None, 0
            return int(data["순위"].min()), int(data["순위"].max()), int(len(data))

        elem_best, elem_worst, elem_count = level_stats("초등")
        mid_best, _, mid_count = level_stats("중등")
        high_best, _, high_count = level_stats("고등")

        def age_ranks(age):
            rows_at_age = person_placements[
                (person_placements["나이_추정"] == age) & person_placements["순위"].notna()
            ]
            rank_values = rows_at_age["순위"].astype(int).tolist()
            return ",".join(str(v) for v in rank_values)

        rows.append(
            {
                "이름": name,
                "최초_출전연도": first_year,
                "최초_출전나이": first_age,
                "초등부_최고순위": elem_best,
                "초등부_최저순위": elem_worst,
                "초등부_출전수": elem_count,
                "중등부_최고순위": mid_best,
                "중등부_출전수": mid_count,
                "고등부_최고순위": high_best,
                "고등부_출전수": high_count,
                "나이10_순위목록": age_ranks(10),
                "나이12_순위목록": age_ranks(12),
                "나이14_순위목록": age_ranks(14),
            }
        )

    summary = pd.DataFrame(rows)
    int_cols = [
        "최초_출전연도",
        "최초_출전나이",
        "초등부_최고순위",
        "초등부_최저순위",
        "초등부_출전수",
        "중등부_최고순위",
        "중등부_출전수",
        "고등부_최고순위",
        "고등부_출전수",
    ]
    for col in int_cols:
        summary[col] = pd.Series(summary[col], dtype="Int64")
    return summary.sort_values("이름")


def print_console(summary_df, placements_df):
    print("이름 | 최초출전나이 | 초등부 최고·최저순위 | 출전수")
    for _, row in summary_df.iterrows():
        best = "-" if pd.isna(row["초등부_최고순위"]) else str(int(row["초등부_최고순위"]))
        worst = "-" if pd.isna(row["초등부_최저순위"]) else str(int(row["초등부_최저순위"]))
        first_age = "-" if pd.isna(row["최초_출전나이"]) else str(int(row["최초_출전나이"]))
        count = int(row["초등부_출전수"]) if not pd.isna(row["초등부_출전수"]) else 0
        print(f"{row['이름']} | {first_age} | {best}·{worst} | {count}")

    total = len(summary_df)
    outside_top10 = int((summary_df["초등부_최저순위"] > 10).fillna(False).sum())
    print(f"초등부에서 10위 밖 성적이 있었던 선수: {outside_top10}명 / 전체 {total}명")
    no_elementary = summary_df[summary_df["초등부_출전수"] == 0]["이름"].tolist()
    print(f"초등부 기록이 아예 없는 선수: [{', '.join(no_elementary)}]")

    age_data = placements_df[placements_df["순위"].notna() & placements_df["나이_추정"].notna()].copy()
    print("나이별 순위 분포 요약")
    for age in range(8, 15):
        ranks = age_data[age_data["나이_추정"] == age]["순위"].astype(int).tolist()
        if not ranks:
            print(f"{age}세: 없음")
            continue
        median = pd.Series(ranks).median()
        print(f"{age}세: 중앙값 {median:.1f}, 범위 {min(ranks)}~{max(ranks)}")


def main():
    if not RECORDS_CSV.exists() or not ATHLETE_INFO_CSV.exists():
        print("[error] data/records.csv 또는 data/athlete_info.csv 파일이 없습니다.")
        return

    records_df = pd.read_csv(RECORDS_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    athlete_df = pd.read_csv(ATHLETE_INFO_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    clean_df = build_clean_records(records_df, athlete_df)
    placements_df = best_placement(clean_df)
    summary_df = summarize_youth(placements_df, clean_df, athlete_df)
    outliers_df = detect_outliers(clean_df)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean_df.to_csv(CLEAN_RECORDS_CSV, index=False, encoding="utf-8-sig")
    placements_df.to_csv(PLACEMENTS_CSV, index=False, encoding="utf-8-sig")
    summary_df.to_csv(YOUTH_SUMMARY_CSV, index=False, encoding="utf-8-sig")
    outliers_df.to_csv(OUTLIERS_CSV, index=False, encoding="utf-8-sig")

    print_console(summary_df, placements_df)
    print(f"이상치 {len(outliers_df)}건 검출 (data/outliers.csv)")


if __name__ == "__main__":
    main()
