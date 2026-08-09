import os
import pathlib
import re
from datetime import date
from itertools import combinations

import pandas as pd

DATA_DIR = pathlib.Path("data")
RECORDS_CSV = DATA_DIR / "records.csv"
ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"
ATHLETE_INDEX_CSV = DATA_DIR / "athlete_index.csv"
ATHLETE_INDEX_ENV = "SPLITS_ATHLETE_INDEX_CSV"
CLEAN_RECORDS_CSV = DATA_DIR / "clean_records.csv"
PLACEMENTS_CSV = DATA_DIR / "placements.csv"
YOUTH_SUMMARY_CSV = DATA_DIR / "youth_summary.csv"
OUTLIERS_CSV = DATA_DIR / "outliers.csv"
COVERAGE_CSV = DATA_DIR / "coverage.csv"
AGE_MATRIX_CSV = DATA_DIR / "age_matrix.csv"
BEST_HEAT_TIMES_CSV = DATA_DIR / "best_heat_times.csv"
SCHOOL_RAW_LIST_TXT = DATA_DIR / "school_raw_list.txt"
SCHOOL_ALIASES_CSV = DATA_DIR / "school_aliases.csv"
SCHOOL_AMBIGUOUS_CSV = DATA_DIR / "school_ambiguous.csv"
ID_MERGE_CANDIDATES_CSV = DATA_DIR / "id_merge_candidates.csv"
ID_MERGES_CSV = DATA_DIR / "id_merges.csv"
YEAR_RE = re.compile(r"(19|20)\d{2}")
DISTANCE_RE = re.compile(r"(500|1000|1500|2000|3000)M")
WINTER_GAME_ROUND_RE = re.compile(r"제\s*(\d+)\s*회")
LOWER_BOUNDS = {500: 40, 1000: 82, 1500: 128, 3000: 260}
OPEN_GENERAL_UPPER_BOUNDS = {500: 70, 1000: 140, 1500: 220}
LOWER_NEAR_MARGIN = 2.0
KNOWN_WINTER_ROUNDS = {88, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 103, 104, 105, 107}
SCHOOL_REGION_PREFIXES = [
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "강원특별자치도",
    "전북특별자치도",
    "제주특별자치도",
    "경기도",
    "강원도",
    "충청북도",
    "충청남도",
    "전라북도",
    "전라남도",
    "경상북도",
    "경상남도",
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
]
SCHOOL_REGION_PREFIXES = sorted(SCHOOL_REGION_PREFIXES, key=len, reverse=True)


def _norm_text(value):
    return str(value or "").strip()


def _split_pipe(value):
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def _to_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def load_athlete_index_df():
    candidate_paths = []
    env_path = _norm_text(os.environ.get(ATHLETE_INDEX_ENV))
    if env_path:
        candidate_paths.append(pathlib.Path(env_path).expanduser())
    candidate_paths.append(ATHLETE_INDEX_CSV)

    seen = set()
    for path in candidate_paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
            return df, path
    return pd.DataFrame(), None


def normalize_school_key(value):
    text = re.sub(r"\s+", "", _norm_text(value))
    if not text:
        return ""
    if text.endswith("초"):
        return text + "등학교"
    if text.endswith("중"):
        return text + "학교"
    if text.endswith("고"):
        return text + "등학교"
    if text.endswith("대"):
        return text + "학교"
    return text


def classify_school_group(normalized_key):
    text = _norm_text(normalized_key)
    if not text:
        return "기타"
    if text.endswith("초등학교"):
        return "초"
    if text.endswith("중학교"):
        return "중"
    if text.endswith("고등학교"):
        return "고"
    if text.endswith("대학교"):
        return "대"
    if any(token in text for token in ["시청", "도청", "군청", "구청", "실업", "공사", "은행", "협회", "연맹", "클럽", "체육회"]):
        return "실업"
    return "기타"


def strip_region_prefix(school_key):
    text = _norm_text(school_key)
    for prefix in SCHOOL_REGION_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            return text[len(prefix) :], prefix
    return text, ""


def collect_affiliation_counts(records_df, athlete_index_df):
    items = []
    if athlete_index_df is not None and not athlete_index_df.empty and "소속목록" in athlete_index_df.columns:
        for value in athlete_index_df["소속목록"].tolist():
            items.extend(_split_pipe(value))
    elif "소속" in records_df.columns:
        items.extend(_norm_text(v) for v in records_df["소속"].tolist() if _norm_text(v))
    if not items:
        return pd.Series(dtype="Int64")
    series = pd.Series(items, dtype=str)
    counts = series.value_counts().sort_values(ascending=False)
    return counts


def build_school_aliases_and_ambiguous(aff_counts):
    rows = []
    for raw, count in aff_counts.items():
        norm_key = normalize_school_key(raw)
        rows.append({"원본표기": raw, "정규화키": norm_key, "학교급": classify_school_group(norm_key), "출현횟수": int(count)})
    alias_df = pd.DataFrame(rows, columns=["원본표기", "정규화키", "학교급", "출현횟수"])
    if alias_df.empty:
        amb_df = pd.DataFrame(columns=["기준코어", "정규화키A", "정규화키B", "표기예시A", "표기예시B", "판정"])
        return alias_df, amb_df
    key_rep = (
        alias_df.sort_values(["출현횟수", "원본표기"], ascending=[False, True])
        .drop_duplicates(subset=["정규화키"], keep="first")[["정규화키", "원본표기"]]
        .set_index("정규화키")["원본표기"]
        .to_dict()
    )
    school_only = alias_df[alias_df["학교급"].isin(["초", "중", "고", "대"])].copy()
    keys = sorted(set(school_only["정규화키"].tolist()))
    core_groups = {}
    for key in keys:
        core, prefix = strip_region_prefix(key)
        core_groups.setdefault(core, []).append((key, prefix))
    ambiguous_rows = []
    for core, values in core_groups.items():
        if len(values) < 2:
            continue
        for (key_a, prefix_a), (key_b, prefix_b) in combinations(sorted(values), 2):
            if key_a == key_b:
                continue
            if not prefix_a and not prefix_b:
                continue
            ambiguous_rows.append(
                {
                    "기준코어": core,
                    "정규화키A": key_a,
                    "정규화키B": key_b,
                    "표기예시A": key_rep.get(key_a, key_a),
                    "표기예시B": key_rep.get(key_b, key_b),
                    "판정": "review",
                }
            )
    amb_df = pd.DataFrame(ambiguous_rows, columns=["기준코어", "정규화키A", "정규화키B", "표기예시A", "표기예시B", "판정"])
    if not amb_df.empty:
        amb_df = amb_df.drop_duplicates(subset=["정규화키A", "정규화키B"]).sort_values(["기준코어", "정규화키A", "정규화키B"])
    return alias_df.sort_values(["출현횟수", "원본표기"], ascending=[False, True]), amb_df


def build_id_profiles(records_df, athlete_df, athlete_index_df):
    profiles = {}

    def get_profile(id_no):
        if id_no not in profiles:
            profiles[id_no] = {
                "idNo": id_no,
                "names": set(),
                "genders": set(),
                "regions": set(),
                "categories": set(),
                "aff_raw": set(),
                "aff_norm": set(),
                "aff_core": set(),
                "record_rows": 0,
                "row_count_hint": 0,
            }
        return profiles[id_no]

    if athlete_index_df is not None and not athlete_index_df.empty:
        for _, row in athlete_index_df.iterrows():
            id_no = _norm_text(row.get("idNo"))
            if not id_no:
                continue
            item = get_profile(id_no)
            name = _norm_text(row.get("이름"))
            if name:
                item["names"].add(name)
            for gender in _split_pipe(row.get("성별")):
                item["genders"].add(gender)
            for category in _split_pipe(row.get("종별목록")):
                item["categories"].add(category)
            for aff in _split_pipe(row.get("소속목록")):
                item["aff_raw"].add(aff)
                norm_key = normalize_school_key(aff)
                if norm_key:
                    item["aff_norm"].add(norm_key)
                    item["aff_core"].add(strip_region_prefix(norm_key)[0])
            item["row_count_hint"] = max(item["row_count_hint"], _to_int(row.get("행수"), default=0))

    for _, row in athlete_df.iterrows():
        id_no = _norm_text(row.get("idNo"))
        if not id_no:
            continue
        item = get_profile(id_no)
        name = _norm_text(row.get("이름"))
        if name:
            item["names"].add(name)
        gender = _norm_text(row.get("성별"))
        if gender:
            item["genders"].add(gender)
        region = _norm_text(row.get("시도"))
        if region:
            item["regions"].add(region)
        category = _norm_text(row.get("종별"))
        if category:
            item["categories"].add(category)
        team = _norm_text(row.get("소속팀"))
        if team:
            item["aff_raw"].add(team)
            norm_key = normalize_school_key(team)
            if norm_key:
                item["aff_norm"].add(norm_key)
                item["aff_core"].add(strip_region_prefix(norm_key)[0])

    for _, row in records_df.iterrows():
        id_no = _norm_text(row.get("idNo"))
        if not id_no:
            continue
        item = get_profile(id_no)
        item["record_rows"] += 1
        category = _norm_text(row.get("종별"))
        if category:
            item["categories"].add(category)
        aff = _norm_text(row.get("소속"))
        if aff:
            item["aff_raw"].add(aff)
            norm_key = normalize_school_key(aff)
            if norm_key:
                item["aff_norm"].add(norm_key)
                item["aff_core"].add(strip_region_prefix(norm_key)[0])

    out = {}
    for id_no, item in profiles.items():
        name = sorted(item["names"])[0] if item["names"] else ""
        out[id_no] = {
            "idNo": id_no,
            "name": name,
            "genders": set(item["genders"]),
            "regions": set(item["regions"]),
            "categories": set(item["categories"]),
            "aff_norm": set(item["aff_norm"]),
            "aff_core": set(item["aff_core"]),
            "row_count": item["row_count_hint"] if item["row_count_hint"] > 0 else item["record_rows"],
            "record_rows": item["record_rows"],
        }
    return out


def build_record_index(records_df):
    per_id = {}
    for _, row in records_df.iterrows():
        id_no = _norm_text(row.get("idNo"))
        if not id_no:
            continue
        item = per_id.setdefault(id_no, {"timeline": {}, "meet_event_pairs": set()})
        meet = _norm_text(row.get("대회명"))
        event = _norm_text(row.get("세부종목"))
        date_key = _norm_text(row.get("일자_정규화")) or _norm_text(row.get("일자"))
        if meet or event:
            item["meet_event_pairs"].add((meet, event))
        if not date_key or not meet or not event:
            continue
        key = (date_key, meet, event)
        record_value = _norm_text(row.get("기록"))
        item["timeline"].setdefault(key, set()).add(record_value)
    return per_id


def evaluate_record_compatibility(record_index, id_a, id_b):
    data_a = record_index.get(id_a)
    data_b = record_index.get(id_b)
    if not data_a or not data_b:
        return {"state": "insufficient", "conflict": False}
    keys_a = set(data_a["timeline"].keys())
    keys_b = set(data_b["timeline"].keys())
    overlap = keys_a.intersection(keys_b)
    for key in overlap:
        val_a = {v for v in data_a["timeline"].get(key, set()) if v}
        val_b = {v for v in data_b["timeline"].get(key, set()) if v}
        if val_a and val_b and val_a.isdisjoint(val_b):
            return {"state": "conflict", "conflict": True}
    return {"state": "pass", "conflict": False}


def build_id_merge_tables(profiles, record_index):
    by_name = {}
    for id_no, profile in profiles.items():
        name = _norm_text(profile.get("name"))
        if not name:
            continue
        by_name.setdefault(name, []).append(id_no)

    candidate_rows = []
    today = date.today().isoformat()
    merge_rows = []

    for name, id_list in by_name.items():
        if len(id_list) < 2:
            continue
        for id_a, id_b in combinations(sorted(id_list), 2):
            a = profiles[id_a]
            b = profiles[id_b]
            shared_gender = sorted(a["genders"].intersection(b["genders"]))
            shared_region = sorted(a["regions"].intersection(b["regions"]))
            shared_aff = sorted(a["aff_norm"].intersection(b["aff_norm"]))
            shared_aff_core = sorted(a["aff_core"].intersection(b["aff_core"]))
            shared_category = sorted(a["categories"].intersection(b["categories"]))
            rec_eval = evaluate_record_compatibility(record_index, id_a, id_b)

            if a["row_count"] > b["row_count"]:
                primary, secondary = a, b
            elif a["row_count"] < b["row_count"]:
                primary, secondary = b, a
            else:
                primary, secondary = (a, b) if a["idNo"] <= b["idNo"] else (b, a)

            primary_rows = int(primary["row_count"])
            secondary_rows = int(secondary["row_count"])
            small_ratio_ok = primary_rows > 0 and secondary_rows <= 5 and (secondary_rows * 10) <= primary_rows

            primary_pairs = record_index.get(primary["idNo"], {}).get("meet_event_pairs", set())
            secondary_pairs = record_index.get(secondary["idNo"], {}).get("meet_event_pairs", set())
            pair_coverage_ok = bool(secondary_pairs) and secondary_pairs.issubset(primary_pairs)
            pair_coverage_exception_ok = (not pair_coverage_ok) and rec_eval["state"] == "pass" and secondary_rows <= 5

            primary_regions = sorted(primary["regions"])
            secondary_regions = sorted(secondary["regions"])
            region_inferred = (not shared_region) and bool(primary_regions) and not secondary_regions
            region_ok = bool(shared_region) or region_inferred
            aff_ok = bool(shared_aff) or bool(shared_aff_core)

            first_five_ok = bool(shared_gender) and region_ok and aff_ok and bool(shared_category)
            record_pass = rec_eval["state"] == "pass"
            if rec_eval["state"] == "conflict":
                verdict = "reject"
            elif first_five_ok and record_pass and small_ratio_ok and (pair_coverage_ok or pair_coverage_exception_ok):
                verdict = "auto_merge"
            elif first_five_ok and rec_eval["state"] in {"pass", "insufficient"}:
                verdict = "review"
            else:
                verdict = "reject"

            if shared_region:
                region_text = " | ".join(shared_region)
            elif region_inferred:
                region_text = " | ".join(primary_regions)
            else:
                region_text = ""
            if shared_aff:
                aff_text = " | ".join(shared_aff)
            elif shared_aff_core:
                aff_text = " | ".join(f"{v}(코어)" for v in shared_aff_core)
            else:
                aff_text = ""

            candidate_rows.append(
                {
                    "주idNo": primary["idNo"],
                    "부idNo": secondary["idNo"],
                    "이름": name,
                    "성별": " | ".join(shared_gender),
                    "시도": region_text,
                    "주행수": primary_rows,
                    "부행수": secondary_rows,
                    "일치소속": aff_text,
                    "기록충돌": "Y" if rec_eval["conflict"] else "N",
                    "판정": verdict,
                    "일치종별": " | ".join(shared_category),
                    "기록검증": rec_eval["state"],
                    "부행수비율(%)": round((secondary_rows / primary_rows * 100), 2) if primary_rows else None,
                    "부(대회,종목)포함": "Y" if pair_coverage_ok else "N",
                    "시도추정": "Y" if region_inferred else "N",
                    "포함예외적용": "Y" if pair_coverage_exception_ok else "N",
                }
            )

            if verdict == "auto_merge":
                reason_bits = [f"행수조건충족({secondary_rows}/{primary_rows})", "소속/종별/성별 일치", "기록충돌 없음"]
                if region_inferred:
                    reason_bits.append("시도는 주id 기준 추정")
                if pair_coverage_exception_ok:
                    reason_bits.append("부(대회,종목)포함 예외 적용")
                merge_rows.append(
                    {
                        "부idNo": secondary["idNo"],
                        "주idNo": primary["idNo"],
                        "확정일자": today,
                        "근거": ", ".join(reason_bits),
                    }
                )

    candidate_df = pd.DataFrame(
        candidate_rows,
        columns=[
            "주idNo",
            "부idNo",
            "이름",
            "성별",
            "시도",
            "주행수",
            "부행수",
            "일치소속",
            "기록충돌",
            "판정",
            "일치종별",
            "기록검증",
            "부행수비율(%)",
            "부(대회,종목)포함",
            "시도추정",
            "포함예외적용",
        ],
    )
    if not candidate_df.empty:
        candidate_df = candidate_df.sort_values(["판정", "이름", "주idNo", "부idNo"], ascending=[True, True, True, True])
    merge_df = pd.DataFrame(merge_rows, columns=["부idNo", "주idNo", "확정일자", "근거"])
    if not merge_df.empty:
        merge_df = merge_df.drop_duplicates(subset=["부idNo"], keep="first").sort_values(["주idNo", "부idNo"])
    return candidate_df, merge_df


def build_merge_map(merge_df):
    mapping = {}
    if merge_df.empty:
        return mapping
    for _, row in merge_df.iterrows():
        sub_id = _norm_text(row.get("부idNo"))
        main_id = _norm_text(row.get("주idNo"))
        if sub_id and main_id and sub_id != main_id:
            mapping[sub_id] = main_id

    def resolve(target):
        seen = set()
        cur = target
        while cur in mapping and cur not in seen:
            seen.add(cur)
            cur = mapping[cur]
        return cur

    resolved = {}
    for sub_id in mapping:
        resolved[sub_id] = resolve(sub_id)
    return resolved


def apply_id_remap(df, mapping, id_col="idNo"):
    if not mapping or id_col not in df.columns:
        return df.copy()
    out = df.copy()
    out[id_col] = out[id_col].astype(str).str.strip().map(lambda v: mapping.get(v, v))
    return out
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
    candidate = df[df["라운드종류"].isin(["채점종합", "결승", "결승B"])].copy()
    selected = []
    for _, group in candidate.groupby(group_cols, dropna=False, sort=False):
        pr = group["라운드종류"].map({"채점종합": 1, "결승": 2, "결승B": 2}).fillna(99)
        cand = group.assign(_priority=pr)
        cand = cand[cand["_priority"] < 99]
        if not cand.empty:
            picked = cand.sort_values("_priority").iloc[0].copy()
            picked["원본행수"] = len(group)
            selected.append(picked)
    if not selected:
        return pd.DataFrame(
            columns=["idNo", "이름", "대회연도", "나이_추정", "학령구간", "대회명", "거리", "SF여부", "순위", "결승구분", "라운드종류", "원본행수", "기록_초"]
        )
    placements = pd.DataFrame(selected).copy()
    placements["결승구분"] = placements["라운드종류"].map({"결승B": "B", "결승": "A", "채점종합": "종합"})
    placements["순위"] = placements["순위_정수"].astype("Int64")
    placements["원본행수"] = pd.Series(placements["원본행수"], dtype="Int64")
    placements.attrs["records_rows"] = len(df)
    placements.attrs["candidate_rows"] = len(candidate)
    placements.attrs["grouped_rows"] = len(placements)
    cols = ["idNo", "이름", "대회연도", "나이_추정", "학령구간", "대회명", "거리", "SF여부", "순위", "결승구분", "라운드종류", "원본행수", "기록_초"]
    return placements[cols].sort_values(["이름", "idNo", "대회연도", "대회명", "거리", "SF여부"], na_position="last")

def infer_winter_game_year(meet_name):
    text = str(meet_name or "").strip()
    if "전국동계체육대회" not in text:
        return None, False
    match = WINTER_GAME_ROUND_RE.search(text)
    if not match:
        return None, False
    round_no = int(match.group(1))
    return round_no - 88 + 2007, round_no not in KNOWN_WINTER_ROUNDS

def build_clean_records(records_df, athlete_df):
    athlete = athlete_df.copy()
    athlete["idNo"] = athlete["idNo"].astype(str).str.strip()
    athlete["출생년도"] = pd.to_numeric(athlete["출생년도"], errors="coerce").astype("Int64")
    athlete = athlete[["idNo", "이름", "출생년도"]].drop_duplicates(subset=["idNo"], keep="first")
    records = records_df.copy()
    records["idNo"] = records["idNo"].astype(str).str.strip()
    clean = records.merge(athlete, on="idNo", how="left")
    clean["대회연도"] = pd.Series([extract_meet_year(n, r) for n, r in zip(clean["일자_정규화"], clean["일자"])], dtype="Int64")
    by_id_meet = clean.groupby(["idNo", "대회명"])["대회연도"].transform(lambda s: s.dropna().iloc[0] if not s.dropna().empty else pd.NA)
    by_meet = clean.groupby("대회명")["대회연도"].transform(lambda s: s.dropna().iloc[0] if not s.dropna().empty else pd.NA)
    clean["대회연도"] = clean["대회연도"].fillna(by_id_meet).fillna(by_meet)
    missing_idx = clean[clean["대회연도"].isna()].index
    out_of_known_rounds = 0
    for idx in missing_idx:
        guessed_year, is_unknown_round = infer_winter_game_year(clean.at[idx, "대회명"])
        if guessed_year is None:
            continue
        clean.at[idx, "대회연도"] = guessed_year
        if is_unknown_round:
            out_of_known_rounds += 1
    clean["대회연도"] = pd.Series(clean["대회연도"], dtype="Int64")
    clean.attrs["year_missing_after_restore"] = int(clean["대회연도"].isna().sum())
    clean.attrs["winter_round_fallback_unknown"] = out_of_known_rounds
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
    reason_counts = {"하한미달": 0, "상한초과": 0, "계측오류의심": 0}

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
        if distance not in LOWER_BOUNDS:
            continue
        value = float(row["기록_초"])
        lower = LOWER_BOUNDS[distance]
        if value < lower:
            add_reason(idx, "하한미달", f"{distance}M 하한미달({value:.3f} < {lower})")
        if row["학령구간"] in {"오픈", "일반"} and distance in OPEN_GENERAL_UPPER_BOUNDS:
            upper = OPEN_GENERAL_UPPER_BOUNDS[distance]
            if value > upper:
                add_reason(idx, "상한초과", f"{distance}M 상한초과({value:.3f} > {upper}, 오픈/일반 기준)")
    # 쇼트트랙은 착순/전술 종목이라 결승 기록이 예선보다 느린 현상이 정상적으로 빈번하다.
    # 따라서 '결승이 예선보다 느림' 규칙은 오탐이 커서 의도적으로 재도입하지 않는다.
    groups = all_times(clean_df).groupby(["idNo", "이름", "대회명", "거리"], dropna=False)
    for _, group in groups:
        if group["거리"].isna().all():
            continue
        distance = int(group["거리"].dropna().iloc[0])
        if distance not in LOWER_BOUNDS:
            continue
        qf = group[(group["라운드종류"] == "준준결승") & group["기록_초"].notna()]
        finals = group[group["라운드종류"].isin(["채점종합", "결승", "결승B"]) & group["기록_초"].notna()]
        if qf.empty or finals.empty:
            continue
        qf_idx = qf["기록_초"].idxmin()
        qf_best = float(qf.loc[qf_idx, "기록_초"])
        final_best = float(finals["기록_초"].min())
        lower = LOWER_BOUNDS[distance]
        if final_best - qf_best >= 5 and qf_best <= lower + LOWER_NEAR_MARGIN:
            add_reason(
                qf_idx,
                "계측오류의심",
                f"준준결승이 결승보다 5초+ 빠르고 하한 근접(준준결승 {qf_best:.3f}, 결승 {final_best:.3f}, 하한 {lower})",
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
def build_age_matrix(placements_df, athlete_df):
    ages = list(range(7, 19))
    roster = athlete_df.copy()
    roster["idNo"] = roster["idNo"].astype(str).str.strip()
    roster["이름"] = roster["이름"].astype(str).str.strip()
    roster = roster[(roster["idNo"] != "") & (roster["이름"] != "")][["idNo", "이름"]].drop_duplicates(subset=["idNo"], keep="first")
    roster = roster.sort_values(["이름", "idNo"])

    base = placements_df[placements_df["순위"].notna() & placements_df["나이_추정"].notna() & placements_df["나이_추정"].between(7, 18)].copy()
    base["idNo"] = base["idNo"].astype(str).str.strip()
    base["이름"] = base["이름"].astype(str).str.strip()
    base = base[(base["idNo"] != "") & (base["이름"] != "")]

    pivot = base.pivot_table(index=["idNo", "이름"], columns="나이_추정", values="순위", aggfunc="min").reindex(columns=ages)
    matrix = roster.merge(pivot.reset_index(), on=["idNo", "이름"], how="left")
    matrix = matrix[["idNo", "이름"] + ages]
    matrix.columns = ["idNo", "이름"] + [str(age) for age in ages]
    for col in [str(age) for age in ages]:
        matrix[col] = matrix[col].apply(lambda x: "" if pd.isna(x) else int(x))
    return matrix
def build_best_heat_times(clean_df):
    cols = ["이름", "출생년도", "나이_추정", "학령구간", "거리", "최고기록_초", "대회명", "일자"]
    heat = clean_df[(clean_df["라운드종류"] == "예선") & clean_df["기록_초"].notna() & clean_df["거리"].notna()].copy()
    if heat.empty:
        return pd.DataFrame(columns=cols)
    group_cols = ["이름", "출생년도", "나이_추정", "학령구간", "거리"]
    idx = heat.groupby(group_cols, dropna=False)["기록_초"].idxmin()
    best = heat.loc[idx, group_cols + ["기록_초", "대회명", "일자"]].copy()
    best = best.rename(columns={"기록_초": "최고기록_초"})
    return best[cols].sort_values(["이름", "나이_추정", "거리"], na_position="last")
def summarize_youth(placements_df, clean_df, athlete_df):
    placement = placements_df.copy()
    placement["idNo"] = placement["idNo"].astype(str).str.strip()
    athlete_base = athlete_df.copy()
    athlete_base["idNo"] = athlete_base["idNo"].astype(str).str.strip()
    athlete_base["이름"] = athlete_base["이름"].astype(str).str.strip()
    athlete_base["출생년도"] = pd.to_numeric(athlete_base["출생년도"], errors="coerce").astype("Int64")
    athlete_base = athlete_base[(athlete_base["idNo"] != "") & (athlete_base["이름"] != "")][["idNo", "이름", "출생년도"]].drop_duplicates(
        subset=["idNo"], keep="first"
    )

    clean = clean_df.copy()
    clean["idNo"] = clean["idNo"].astype(str).str.strip()
    clean["이름"] = clean["이름"].astype(str).str.strip()
    rows = []
    for _, athlete_row in athlete_base.sort_values(["이름", "idNo"]).iterrows():
        id_no = athlete_row["idNo"]
        name = athlete_row["이름"]
        person_records = clean[clean["idNo"] == id_no]
        person_placements = placement[placement["idNo"] == id_no]
        first_year, first_age = None, None
        years = person_records["대회연도"].dropna()
        if not years.empty:
            first_year = int(years.min())
            ages = person_records[person_records["대회연도"] == first_year]["나이_추정"].dropna()
            if not ages.empty:
                first_age = int(ages.min())
        birth_year = None if pd.isna(athlete_row["출생년도"]) else int(athlete_row["출생년도"])
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
        rows.append(
            {
                "idNo": id_no,
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
                "초등6학년_추정연도": sixth_grade_year,
                "유년기_데이터신뢰도": youth_data_reliability(sixth_grade_year),
                "나이10_순위목록": age_ranks(10),
                "나이12_순위목록": age_ranks(12),
                "나이14_순위목록": age_ranks(14),
            }
        )
    summary = pd.DataFrame(rows)
    for col in ["최초_출전연도", "최초_출전나이", "초등부_최고순위", "초등부_최저순위", "초등부_출전수", "중등부_최고순위", "중등부_출전수", "고등부_최고순위", "고등부_출전수", "초등6학년_추정연도"]:
        summary[col] = pd.Series(summary[col], dtype="Int64")
    return summary.sort_values(["이름", "idNo"])
def print_console(summary_df, placements_df):
    print("주의: 나이_추정은 대회연도-출생년도이며 만 나이보다 최대 1살 높습니다. 동계 대회(1~2월) 집중으로 다수 행에서 체계적으로 +1 편향이 생길 수 있습니다.")
    print("주의: 결승 기록은 전술 영향을 받으므로 성장 추이 분석에 부적합하다. 기록 기반 분석에는 예선(Heat) 기록만 사용할 것. 순위 기반 분석에는 기존대로 채점종합/결승을 사용한다.")
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
    athlete_index_df, athlete_index_path = load_athlete_index_df()

    aff_counts = collect_affiliation_counts(records_df, athlete_index_df)
    school_aliases_df, school_ambiguous_df = build_school_aliases_and_ambiguous(aff_counts)
    profiles = build_id_profiles(records_df, athlete_df, athlete_index_df)
    record_index = build_record_index(records_df)
    id_merge_candidates_df, id_merges_df = build_id_merge_tables(profiles, record_index)
    id_merge_map = build_merge_map(id_merges_df)

    records_merged_df = apply_id_remap(records_df, id_merge_map, id_col="idNo")
    athlete_merged_df = apply_id_remap(athlete_df, id_merge_map, id_col="idNo")

    clean_df = build_clean_records(records_merged_df, athlete_merged_df)
    placements_df = best_placement(clean_df)
    summary_df = summarize_youth(placements_df, clean_df, athlete_merged_df)
    outliers_df, outlier_reason_counts = detect_outliers(clean_df)
    coverage_df = build_coverage(clean_df)
    age_matrix_df = build_age_matrix(placements_df, athlete_merged_df)
    best_heat_df = build_best_heat_times(clean_df)
    dup_check = placements_df.groupby(["이름", "대회명", "거리", "SF여부"], dropna=False).size().reset_index(name="행수")
    dup_bad = dup_check[dup_check["행수"] >= 2]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    school_text = aff_counts.to_string() if not aff_counts.empty else "(소속 표기 없음)"
    SCHOOL_RAW_LIST_TXT.write_text(school_text + "\n", encoding="utf-8")
    school_aliases_df.to_csv(SCHOOL_ALIASES_CSV, index=False, encoding="utf-8-sig")
    school_ambiguous_df.to_csv(SCHOOL_AMBIGUOUS_CSV, index=False, encoding="utf-8-sig")
    id_merge_candidates_df.to_csv(ID_MERGE_CANDIDATES_CSV, index=False, encoding="utf-8-sig")
    id_merges_df.to_csv(ID_MERGES_CSV, index=False, encoding="utf-8-sig")
    clean_df.to_csv(CLEAN_RECORDS_CSV, index=False, encoding="utf-8-sig")
    placements_df.to_csv(PLACEMENTS_CSV, index=False, encoding="utf-8-sig")
    summary_df.to_csv(YOUTH_SUMMARY_CSV, index=False, encoding="utf-8-sig")
    outliers_df.to_csv(OUTLIERS_CSV, index=False, encoding="utf-8-sig")
    coverage_df.to_csv(COVERAGE_CSV, index=False, encoding="utf-8-sig")
    age_matrix_df.to_csv(AGE_MATRIX_CSV, index=False, encoding="utf-8-sig")
    best_heat_df.to_csv(BEST_HEAT_TIMES_CSV, index=False, encoding="utf-8-sig")
    print_console(summary_df, placements_df)
    print(
        "records {0} → 성적행 후보 {1} → (선수,대회,거리,SF여부) 그룹핑 후 {2}".format(
            placements_df.attrs.get("records_rows", len(clean_df)),
            placements_df.attrs.get("candidate_rows", 0),
            placements_df.attrs.get("grouped_rows", len(placements_df)),
        )
    )
    print(f"검증: (이름, 대회명, 거리, SF여부) 2행 이상 조합 {len(dup_bad)}건")
    if not dup_bad.empty:
        print(dup_bad[["이름", "대회명", "거리", "SF여부", "행수"]].to_string(index=False))
    print(f"대회연도 복원 후 결측 행수: {clean_df.attrs.get('year_missing_after_restore', 0)}행")
    if clean_df.attrs.get("winter_round_fallback_unknown", 0):
        print(f"전국동계체전 회차 복원(목록 외 회차): {clean_df.attrs.get('winter_round_fallback_unknown', 0)}행")
    print(f"데이터 커버리지 저장 완료: data/coverage.csv ({int(coverage_df['대회연도'].min())}~{int(coverage_df['대회연도'].max())})" if not coverage_df.empty else "데이터 커버리지 저장 완료: data/coverage.csv (연도 정보 없음)")
    print("이상치 사유별 건수: 하한미달 {0}건 / 상한초과 {1}건 / 계측오류의심 {2}건".format(outlier_reason_counts["하한미달"], outlier_reason_counts["상한초과"], outlier_reason_counts["계측오류의심"]))
    print(f"이상치 {len(outliers_df)}건 검출 (data/outliers.csv)")
    review_count = 0 if id_merge_candidates_df.empty else int((id_merge_candidates_df["판정"] == "review").sum())
    auto_count = 0 if id_merges_df.empty else len(id_merges_df)
    print(f"학교 표기 목록 저장 완료: {SCHOOL_RAW_LIST_TXT}")
    if athlete_index_path is None:
        print(f"선수 인덱스 입력: 미사용 (환경변수 {ATHLETE_INDEX_ENV} 또는 {ATHLETE_INDEX_CSV} 파일 없음)")
    else:
        print(f"선수 인덱스 입력: {athlete_index_path}")
    print(f"학교 정규화 사전 저장 완료: {SCHOOL_ALIASES_CSV} ({len(school_aliases_df)}행)")
    print(f"지역 접두 모호 케이스 저장 완료: {SCHOOL_AMBIGUOUS_CSV} ({len(school_ambiguous_df)}행)")
    print(f"id 병합 후보 저장 완료: {ID_MERGE_CANDIDATES_CSV} ({len(id_merge_candidates_df)}행)")
    print(f"id 확정 병합 저장 완료: {ID_MERGES_CSV} ({auto_count}건)")
    print(f"id 병합 review 건수: {review_count}건")
if __name__ == "__main__":
    main()
