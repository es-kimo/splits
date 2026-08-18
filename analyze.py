import hashlib
import os
import pathlib
import re
from datetime import date
from itertools import combinations

import pandas as pd

DATA_DIR = pathlib.Path("data")
RECORDS_CSV = DATA_DIR / "records.csv"
ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"
RECORDS_FULL_CSV = DATA_DIR / "records_full.csv"
ATHLETE_INFO_FULL_CSV = DATA_DIR / "athlete_info_full.csv"
RECORDS_ANON_CSV = DATA_DIR / "records_anon.csv"
ATHLETE_INDEX_CSV = DATA_DIR / "athlete_index.csv"
ATHLETE_INDEX_ENV = "SPLITS_ATHLETE_INDEX_CSV"
CLEAN_RECORDS_CSV = DATA_DIR / "clean_records.csv"
PLACEMENTS_CSV = DATA_DIR / "placements.csv"
YOUTH_SUMMARY_CSV = DATA_DIR / "youth_summary.csv"
OUTLIERS_CSV = DATA_DIR / "outliers.csv"
COVERAGE_CSV = DATA_DIR / "coverage.csv"
AGE_MATRIX_CSV = DATA_DIR / "age_matrix.csv"
BEST_HEAT_TIMES_CSV = DATA_DIR / "best_heat_times.csv"
STATS_DISTRIBUTION_CSV = DATA_DIR / "stats_distribution.csv"
STATS_PARTICIPATION_CSV = DATA_DIR / "stats_participation.csv"
SEASON_MONTH_HISTOGRAM_CSV = DATA_DIR / "season_month_histogram.csv"
PARTICIPATION_CSV = DATA_DIR / "participation.csv"
SEASON_ACTIVITY_COUNTS_CSV = DATA_DIR / "season_activity_counts.csv"
CLASS_TRANSITION_SUMMARY_CSV = DATA_DIR / "class_transition_summary.csv"
GAP_RETURN_RATES_CSV = DATA_DIR / "gap_return_rates.csv"
RECORD_STOP_RULE_CSV = DATA_DIR / "record_stop_rule.csv"
SCHOOL_RAW_LIST_TXT = DATA_DIR / "school_raw_list.txt"
SCHOOL_ALIASES_CSV = DATA_DIR / "school_aliases.csv"
SCHOOL_AMBIGUOUS_CSV = DATA_DIR / "school_ambiguous.csv"
ID_MERGE_CANDIDATES_CSV = DATA_DIR / "id_merge_candidates.csv"
ID_MERGES_CSV = DATA_DIR / "id_merges.csv"
CLASS_LEVEL_MAP_CSV = DATA_DIR / "class_level_map.csv"
CLASS_LEVEL_YEAR_CATEGORY_COUNTS_CSV = DATA_DIR / "class_level_year_category_counts.csv"
CLASS_LEVEL_AB_AGREEMENT_SUMMARY_CSV = DATA_DIR / "class_level_ab_agreement_summary.csv"
CLASS_LEVEL_AB_MISMATCH_TYPES_CSV = DATA_DIR / "class_level_ab_mismatch_types.csv"
CLASS_LEVEL_YEAR_READINESS_CSV = DATA_DIR / "class_level_year_readiness.csv"
ID_MERGE_COLUMNS = ["부idNo", "주idNo", "확정일자", "근거"]
YEAR_RE = re.compile(r"(19|20)\d{2}")
DISTANCE_RE = re.compile(r"(500|1000|1500|2000|3000)M")
WINTER_GAME_ROUND_RE = re.compile(r"제\s*(\d+)\s*회")
DATE_MONTH_RE = re.compile(r"^(?:19|20)\d{2}-(\d{2})-\d{2}$")
DATE_MONTH_DOTTED_RE = re.compile(r"^(?:19|20)\d{2}[./](\d{1,2})[./]\d{1,2}$")
CATEGORY_NORMALIZE_RE = re.compile(r"[\s\-_/·.]+")
ANON_KEY_RE = re.compile(r"^[0-9a-f]{12}$")
LOWER_BOUNDS = {500: 40, 1000: 82, 1500: 128, 3000: 260}
OPEN_GENERAL_UPPER_BOUNDS = {500: 70, 1000: 140, 1500: 220}
LOWER_NEAR_MARGIN = 2.0
# 통계 집계 전용 하한. 종목 오염(스피드스케이팅) 제거 후에도 남는 입력 오류만 보수적으로 제거한다.
# 상한은 두지 않는다. 초등 저학년이 500m를 90초에 타는 것은 정상이다.
STATS_TIME_LOWER_BOUNDS = {500: 30, 1000: 60, 1500: 100, 2000: 140, 3000: 210}
SPEED_CLASS_CD = "1"
SHORTTRACK_CLASS_CD = "2"
FIGURE_CLASS_CD = "3"
HEAT_GROUP_ROUND_RE = re.compile(r"^\d+조$")
SPEED_MEET_NAME_TOKEN = "스피드"
SHORTTRACK_MEET_NAME_TOKEN = "쇼트트랙"
KNOWN_WINTER_ROUNDS = {88, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 103, 104, 105, 107}
K_ANONYMITY_MIN = 10
INSUFFICIENT_TEXT = "데이터 부족"
SEASON_START_MONTH = 7
SCHOOL_LEVEL_STAGES = ["초등", "중등", "고등", "대학·일반"]
SCHOOL_LEVEL_OPEN = "오픈"
SCHOOL_LEVEL_EXCLUDED = "분석제외"
SCHOOL_LEVEL_ORDER = {stage: idx for idx, stage in enumerate(SCHOOL_LEVEL_STAGES)}
READINESS_MIN_COMPARABLE_ROWS = 500
READINESS_MIN_AGREEMENT_PCT = 90.0
READINESS_MAX_BIRTH_MISSING_PCT = 10.0
FORBIDDEN_OUTPUT_COLUMNS = {"idNo", "이름", "소속", "시도"}
FORBIDDEN_ANON_COLUMNS = {"idNo", "이름", "소속", "시도", "BIB", "레인"}
RECORDS_ANON_REQUIRED_COLUMNS = [
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
DIST_GROUP_COLS = ["출생연도", "성별", "거리"]
DIST_TIME_QUANTILES = [0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
DIST_TIME_COLS = ["기록_p05", "기록_p10", "기록_p20", "기록_p30", "기록_p40", "기록_p50", "기록_p60", "기록_p70", "기록_p80", "기록_p90", "기록_p95"]
DIST_RANK_QUANTILES = [0.25, 0.50, 0.75]
DIST_RANK_COLS = ["순위_p25", "순위_p50", "순위_p75"]
DIST_OUTPUT_COLS = (
    ["출생연도", "성별", "거리", "기록_인원수"] + DIST_TIME_COLS + ["순위_인원수"] + DIST_RANK_COLS
)
PART_OUTPUT_COLS = ["출생연도", "성별", "최초출전나이_p25", "최초출전나이_p50", "최초출전나이_p75", "초등부출전수_p50", "인원수"]
SEASON_MONTH_HISTOGRAM_COLS = ["월", "월라벨", "시즌구간", "대회수", "대회비율(%)"]
PARTICIPATION_OUTPUT_COLS = [
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
SEASON_ACTIVITY_OUTPUT_COLS = ["시즌", "활동선수수"]
CLASS_TRANSITION_OUTPUT_COLS = [
    "시즌",
    "활동선수수",
    "쇼트트랙전용수",
    "스피드전용수",
    "병행수",
    "전환수",
    "기타수",
    "쇼트트랙중단수",
    "빙상중단수",
]
GAP_RETURN_RATE_OUTPUT_COLS = ["구간", "공백시즌수", "사례수", "복귀사례", "복귀율(%)", "관측부족제외수"]
RECORD_STOP_RULE_OUTPUT_COLS = [
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
GAP_RETURN_SEGMENTS = [("전체", None), ("6→7", 6), ("9→10", 9), ("12→13", 12)]
GAP_RETURN_BUCKETS = [("1", 1), ("2", 2), ("3", 3), ("4+", 4)]
RECORD_STOP_RULE_TEXT = "n시즌 연속 미출전 = 기록 중단"
RECORD_STOP_MAX_RETURN_RATE_PCT = 20.0
RECORD_STOP_MIN_CASES = 100
CLASS_LEVEL_MAP_COLS = ["종별", "종별정규화키", "단계_A", "A_판정규칙", "분석포함", "행수", "최초연도", "최신연도"]
CLASS_LEVEL_YEAR_CATEGORY_COLS = ["대회연도", "종별", "단계_A", "행수"]
CLASS_LEVEL_AGREEMENT_COLS = [
    "전체행수",
    "오픈행수",
    "오픈비율(%)",
    "오픈행_출생연도기반판정가능행수",
    "오픈행_출생연도기반판정가능비율(%)",
    "출생연도결측행수",
    "출생연도결측비율(%)",
    "종별폴백행수",
    "종별폴백비율(%)",
    "비교가능행수",
    "일치행수",
    "일치율(%)",
    "불일치행수",
    "단계분석_권장시작연도",
    "기준_최소비교행수",
    "기준_최소일치율(%)",
    "기준_최대출생연도결측비율(%)",
]
CLASS_LEVEL_MISMATCH_COLS = ["불일치유형", "건수", "비율(%)"]
CLASS_LEVEL_YEAR_READINESS_COLS = [
    "대회연도",
    "전체행수",
    "비교가능행수",
    "일치행수",
    "일치율(%)",
    "오픈비율(%)",
    "출생연도결측비율(%)",
    "단계분석사용가능",
    "판정사유",
]
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
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


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
    merge_df = pd.DataFrame(merge_rows, columns=ID_MERGE_COLUMNS)
    if not merge_df.empty:
        merge_df = merge_df.drop_duplicates(subset=["부idNo"], keep="first").sort_values(["주idNo", "부idNo"])
    return candidate_df, merge_df


def load_existing_id_merges():
    if not ID_MERGES_CSV.exists():
        return pd.DataFrame(columns=ID_MERGE_COLUMNS)
    existing = pd.read_csv(ID_MERGES_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    for col in ID_MERGE_COLUMNS:
        if col not in existing.columns:
            existing[col] = ""
    existing = existing[ID_MERGE_COLUMNS].copy()
    existing["부idNo"] = existing["부idNo"].map(_norm_text)
    existing["주idNo"] = existing["주idNo"].map(_norm_text)
    existing = existing[(existing["부idNo"] != "") & (existing["주idNo"] != "") & (existing["부idNo"] != existing["주idNo"])].copy()
    if existing.empty:
        return pd.DataFrame(columns=ID_MERGE_COLUMNS)
    return existing.drop_duplicates(subset=["부idNo"], keep="first")


def merge_id_merges(existing_df, auto_df):
    merged_by_sub = {}
    conflicts = 0

    for _, row in existing_df.iterrows():
        sub_id = _norm_text(row.get("부idNo"))
        main_id = _norm_text(row.get("주idNo"))
        if not sub_id or not main_id or sub_id == main_id:
            continue
        merged_by_sub[sub_id] = {
            "부idNo": sub_id,
            "주idNo": main_id,
            "확정일자": _norm_text(row.get("확정일자")),
            "근거": _norm_text(row.get("근거")),
        }

    added_auto = 0
    for _, row in auto_df.iterrows():
        sub_id = _norm_text(row.get("부idNo"))
        main_id = _norm_text(row.get("주idNo"))
        if not sub_id or not main_id or sub_id == main_id:
            continue
        if sub_id in merged_by_sub:
            if merged_by_sub[sub_id]["주idNo"] != main_id:
                conflicts += 1
            continue
        merged_by_sub[sub_id] = {
            "부idNo": sub_id,
            "주idNo": main_id,
            "확정일자": _norm_text(row.get("확정일자")),
            "근거": _norm_text(row.get("근거")),
        }
        added_auto += 1

    if not merged_by_sub:
        merged_df = pd.DataFrame(columns=ID_MERGE_COLUMNS)
    else:
        merged_df = pd.DataFrame(merged_by_sub.values(), columns=ID_MERGE_COLUMNS).sort_values(["주idNo", "부idNo"])
    stats = {
        "existing_count": int(len(existing_df)),
        "auto_count": int(len(auto_df)),
        "added_auto": int(added_auto),
        "conflict_skipped": int(conflicts),
        "total_count": int(len(merged_df)),
    }
    return merged_df, stats


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

def _to_int_or_none(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def normalize_category_key(category):
    text = _norm_text(category).upper()
    if not text:
        return ""
    return CATEGORY_NORMALIZE_RE.sub("", text)


def classify_school_level_from_category(category):
    key = normalize_category_key(category)
    if not key:
        return {"categoryKey": key, "stage": SCHOOL_LEVEL_EXCLUDED, "rule": "빈종별"}
    if key in {"남자부", "여자부", "MEN", "WOMEN"}:
        return {"categoryKey": key, "stage": SCHOOL_LEVEL_OPEN, "rule": "오픈종별"}
    if "유치" in key:
        return {"categoryKey": key, "stage": SCHOOL_LEVEL_EXCLUDED, "rule": "유치부"}
    if "초등" in key or "12세이하" in key:
        return {"categoryKey": key, "stage": "초등", "rule": "초등키워드"}
    if "중학" in key or "중등" in key or "주니어" in key:
        return {"categoryKey": key, "stage": "중등", "rule": "중등키워드"}
    if "고등" in key or "고교" in key or "남고부" in key or "여고부" in key:
        return {"categoryKey": key, "stage": "고등", "rule": "고등키워드"}
    if any(token in key for token in ["대학", "일반", "실업", "동호인"]):
        return {"categoryKey": key, "stage": "대학·일반", "rule": "대학일반키워드"}
    return {"categoryKey": key, "stage": SCHOOL_LEVEL_EXCLUDED, "rule": "기타미분류"}


def _extract_month_from_date(normalized_date, raw_date):
    for value in [normalized_date, raw_date]:
        text = _norm_text(value)
        if not text:
            continue
        match = DATE_MONTH_RE.match(text)
        if match:
            month = int(match.group(1))
            if 1 <= month <= 12:
                return month
        match = DATE_MONTH_DOTTED_RE.match(text)
        if match:
            month = int(match.group(1))
            if 1 <= month <= 12:
                return month
    return None


def infer_season_start_year(meet_year, normalized_date="", raw_date=""):
    year = _to_int_or_none(meet_year)
    if year is None:
        return None
    month = _extract_month_from_date(normalized_date, raw_date)
    if month is None:
        return year
    return year if month >= SEASON_START_MONTH else year - 1


def calculate_school_grade(season_start_year, birth_year):
    season_year = _to_int_or_none(season_start_year)
    birth = _to_int_or_none(birth_year)
    if season_year is None or birth is None:
        return None
    return season_year - birth - 6


def classify_school_level_from_grade(grade):
    grade_num = _to_int_or_none(grade)
    if grade_num is None:
        return None
    if grade_num <= 0:
        return SCHOOL_LEVEL_EXCLUDED
    if grade_num <= 6:
        return "초등"
    if grade_num <= 9:
        return "중등"
    if grade_num <= 12:
        return "고등"
    return "대학·일반"


def resolve_school_level(category, birth_year=None, season_start_year=None):
    category_info = classify_school_level_from_category(category)
    category_stage = category_info["stage"]
    grade = calculate_school_grade(season_start_year, birth_year)
    grade_stage = classify_school_level_from_grade(grade)
    if category_stage == SCHOOL_LEVEL_OPEN:
        return {
            "stage_final": SCHOOL_LEVEL_OPEN,
            "stage_category": category_stage,
            "stage_grade": grade_stage,
            "grade": grade,
            "source": "open_category",
            "category_key": category_info["categoryKey"],
            "category_rule": category_info["rule"],
        }
    if grade_stage in SCHOOL_LEVEL_STAGES:
        return {
            "stage_final": grade_stage,
            "stage_category": category_stage,
            "stage_grade": grade_stage,
            "grade": grade,
            "source": "birth_year",
            "category_key": category_info["categoryKey"],
            "category_rule": category_info["rule"],
        }
    if grade_stage == SCHOOL_LEVEL_EXCLUDED:
        return {
            "stage_final": None,
            "stage_category": category_stage,
            "stage_grade": grade_stage,
            "grade": grade,
            "source": "grade_excluded",
            "category_key": category_info["categoryKey"],
            "category_rule": category_info["rule"],
        }
    if category_stage in SCHOOL_LEVEL_STAGES:
        return {
            "stage_final": category_stage,
            "stage_category": category_stage,
            "stage_grade": grade_stage,
            "grade": grade,
            "source": "category_fallback",
            "category_key": category_info["categoryKey"],
            "category_rule": category_info["rule"],
        }
    return {
        "stage_final": None,
        "stage_category": category_stage,
        "stage_grade": grade_stage,
        "grade": grade,
        "source": "excluded_or_unknown",
        "category_key": category_info["categoryKey"],
        "category_rule": category_info["rule"],
    }


def classify_school_level(category, birth_year=None, season_start_year=None):
    return resolve_school_level(category, birth_year=birth_year, season_start_year=season_start_year)["stage_final"]


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


def is_speed_meet_name(meet_name):
    text = str(meet_name or "").strip()
    if not text:
        return False
    return SPEED_MEET_NAME_TOKEN in text and SHORTTRACK_MEET_NAME_TOKEN not in text


def classify_class_cd(meet_name, round_name, round_kind=None, meet_class_cd=None):
    # 수집 원천의 classCd는 조회 파라미터 값이라 종목 판별력이 없고, meet_index_inf201.csv도 쇼트트랙만 담고 있다.
    # 게다가 전국동계체육대회처럼 한 대회명에 스피드·쇼트트랙이 함께 있는 대회가 있어 대회 단위 조인만으로는 분리되지 않는다.
    # 따라서 행 단위 규칙으로 판별한다.
    mapped = str(meet_class_cd or "").strip()
    if mapped in {SPEED_CLASS_CD, FIGURE_CLASS_CD}:
        return mapped
    kind = str(round_kind or "").strip() or classify_round(round_name)
    round_text = str(round_name or "").strip().replace(" ", "")
    if kind == "기타" and HEAT_GROUP_ROUND_RE.match(round_text):
        # 스피드스케이팅은 2명씩 조를 나눠 타고 기록으로 겨루므로 예선/결승 구분 없이 조 번호만 남는다.
        return SPEED_CLASS_CD
    if is_speed_meet_name(meet_name):
        return SPEED_CLASS_CD
    return SHORTTRACK_CLASS_CD


def attach_class_cd(df, meet_class_cd_map=None):
    out = df.copy()
    if out.empty:
        out["classCd"] = pd.Series(dtype=str)
        return out
    meet_names = out.get("대회명", pd.Series([""] * len(out), index=out.index))
    rounds = out.get("라운드", pd.Series([""] * len(out), index=out.index))
    round_kinds = out.get("라운드종류", pd.Series([""] * len(out), index=out.index))
    if meet_class_cd_map:
        mapped = [meet_class_cd_map.get(str(name or "").strip(), "") for name in meet_names]
    else:
        mapped = [""] * len(out)
    out["classCd"] = [
        classify_class_cd(name, round_name, round_kind, mapped_value)
        for name, round_name, round_kind, mapped_value in zip(meet_names, rounds, round_kinds, mapped)
    ]
    return out
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
    athlete["성별"] = athlete["성별"].astype(str).str.strip()
    athlete = athlete[["idNo", "이름", "출생년도", "성별"]].drop_duplicates(subset=["idNo"], keep="first")
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
    clean["시즌시작연도"] = pd.Series(
        [infer_season_start_year(year, date_norm, date_raw) for year, date_norm, date_raw in zip(clean["대회연도"], clean["일자_정규화"], clean["일자"])],
        dtype="Int64",
    )
    level_resolution = [
        resolve_school_level(category, birth_year=birth, season_start_year=season_year)
        for category, birth, season_year in zip(clean["종별"], clean["출생년도"], clean["시즌시작연도"])
    ]
    clean["학령구간"] = [item["stage_final"] for item in level_resolution]
    clean["학년_계산"] = pd.Series([item["grade"] for item in level_resolution], dtype="Int64")
    clean["학령구간_판정근거"] = [item["source"] for item in level_resolution]
    parsed = clean["세부종목"].apply(parse_event_detail)
    clean["거리"] = pd.Series([p[0] for p in parsed], dtype="Int64")
    clean["SF여부"] = [p[1] for p in parsed]
    clean["기록_초"] = pd.to_numeric(clean["기록"].apply(parse_time_to_seconds), errors="coerce")
    clean["라운드종류"] = clean["라운드"].apply(classify_round)
    clean["순위_정수"] = pd.Series(clean["순위"].apply(parse_rank), dtype="Int64")
    clean = attach_class_cd(clean)
    return clean
def detect_outliers(clean_df):
    reasons = {}
    reason_counts = {"하한미달": 0, "상한초과": 0, "계측오류의심": 0, "통계하한미달": 0}

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
        value = float(row["기록_초"])
        stats_lower = STATS_TIME_LOWER_BOUNDS.get(distance)
        if (
            stats_lower is not None
            and _norm_text(row.get("classCd")) == SHORTTRACK_CLASS_CD
            and value < stats_lower
        ):
            add_reason(idx, "통계하한미달", f"{distance}M 통계 하한미달({value:.3f} < {stats_lower})")
        if distance not in LOWER_BOUNDS:
            continue
        lower = LOWER_BOUNDS[distance]
        if value < lower:
            add_reason(idx, "하한미달", f"{distance}M 하한미달({value:.3f} < {lower})")
        if row["학령구간"] in {"오픈", "일반", "대학·일반", "대학"} and distance in OPEN_GENERAL_UPPER_BOUNDS:
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


def _quantile_or_none(series, q, digits=3):
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.quantile(q)), digits)


def _round_or_none(value, digits=3):
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return None
    return round(float(num), digits)


def _count_or_zero(value):
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(num):
        return 0
    return int(num)


def _first_non_empty(series):
    for value in series:
        text = _norm_text(value)
        if text:
            return text
    return ""


def build_athlete_profiles(athlete_df):
    base = athlete_df.copy()
    base["idNo"] = base["idNo"].astype(str).str.strip()
    base = base[base["idNo"] != ""].copy()
    if base.empty:
        return pd.DataFrame(columns=["idNo", "출생연도", "성별"])
    rows = []
    for id_no, group in base.groupby("idNo", sort=False):
        births = pd.to_numeric(group["출생년도"], errors="coerce").dropna()
        rows.append(
            {
                "idNo": id_no,
                "출생연도": int(births.iloc[0]) if not births.empty else pd.NA,
                "성별": _first_non_empty(group["성별"]),
            }
        )
    profile = pd.DataFrame(rows, columns=["idNo", "출생연도", "성별"])
    profile["출생연도"] = pd.Series(profile["출생연도"], dtype="Int64")
    return profile


def exclude_team_records_for_stats(records_df):
    if records_df is None or records_df.empty:
        return records_df, 0
    base = records_df.copy()
    idx = base.index
    pcnt = base.get("pcntGbn", pd.Series("", index=idx)).astype(str).str.strip().str.upper()
    detail_cd = base.get("detailClassCd", pd.Series("", index=idx)).astype(str).str.strip()
    detail_name = base.get("세부종목", pd.Series("", index=idx)).astype(str).str.strip()
    relay_mask = detail_name.str.contains("릴레이|RELAY", case=False, regex=True)
    team_mask = pcnt.eq("T") | detail_cd.str.endswith("07") | relay_mask
    removed = int(team_mask.sum())
    if removed <= 0:
        return base, 0
    return base[~team_mask].copy(), removed


def select_stats_source(records_merged_df, athlete_merged_df, id_merge_map):
    stats_records = records_merged_df
    stats_athlete = athlete_merged_df
    source_label = f"{RECORDS_CSV.name}, {ATHLETE_INFO_CSV.name}"
    if RECORDS_FULL_CSV.exists() and ATHLETE_INFO_FULL_CSV.exists():
        full_records_df = pd.read_csv(RECORDS_FULL_CSV, dtype=str, encoding="utf-8-sig").fillna("")
        full_athlete_df = pd.read_csv(ATHLETE_INFO_FULL_CSV, dtype=str, encoding="utf-8-sig").fillna("")
        stats_records = apply_id_remap(full_records_df, id_merge_map, id_col="idNo")
        stats_athlete = apply_id_remap(full_athlete_df, id_merge_map, id_col="idNo")
        source_label = f"{RECORDS_FULL_CSV.name}, {ATHLETE_INFO_FULL_CSV.name}"
    stats_records, excluded_team_rows = exclude_team_records_for_stats(stats_records)
    if excluded_team_rows:
        print(f"통계 집계에서 단체전/계주 기록 {excluded_team_rows}건 제외")
    stats_clean = build_clean_records(stats_records, stats_athlete)
    stats_placements = best_placement(stats_clean)
    stats_summary = summarize_youth(stats_placements, stats_clean, stats_athlete)
    return stats_clean, stats_placements, stats_summary, stats_athlete, source_label


def select_participation_source(records_merged_df, athlete_merged_df, id_merge_map):
    records = records_merged_df
    athlete = athlete_merged_df
    source_label = f"{RECORDS_CSV.name}, {ATHLETE_INFO_CSV.name}"
    if RECORDS_FULL_CSV.exists() and ATHLETE_INFO_FULL_CSV.exists():
        full_records_df = pd.read_csv(RECORDS_FULL_CSV, dtype=str, encoding="utf-8-sig").fillna("")
        full_athlete_df = pd.read_csv(ATHLETE_INFO_FULL_CSV, dtype=str, encoding="utf-8-sig").fillna("")
        records = apply_id_remap(full_records_df, id_merge_map, id_col="idNo")
        athlete = apply_id_remap(full_athlete_df, id_merge_map, id_col="idNo")
        source_label = f"{RECORDS_FULL_CSV.name}, {ATHLETE_INFO_FULL_CSV.name}"
    clean = build_clean_records(records, athlete)
    return clean, source_label


def _load_anon_clean_records():
    anon_df = pd.read_csv(RECORDS_ANON_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    columns = list(anon_df.columns)
    if columns != RECORDS_ANON_REQUIRED_COLUMNS:
        raise ValueError(f"[error] data/records_anon.csv 컬럼이 기대값과 다릅니다: {columns}")
    forbidden = FORBIDDEN_ANON_COLUMNS.intersection(columns)
    if forbidden:
        raise ValueError(f"[error] data/records_anon.csv에 금지 컬럼이 포함되었습니다: {', '.join(sorted(forbidden))}")
    if anon_df.empty:
        empty_clean = pd.DataFrame(
            columns=[
                "idNo",
                "이름",
                "대회명",
                "대회연도",
                "출생년도",
                "성별",
                "학령구간",
                "거리",
                "SF여부",
                "라운드",
                "라운드종류",
                "순위",
                "기록_초",
                "종별",
                "일자",
                "일자_정규화",
                "순위_정수",
                "나이_추정",
                "classCd",
            ]
        )
        empty_clean.attrs["year_missing_after_restore"] = 0
        empty_clean.attrs["winter_round_fallback_unknown"] = 0
        return empty_clean, pd.DataFrame(columns=["idNo", "이름", "출생년도", "성별"])

    clean = pd.DataFrame(
        {
            "idNo": anon_df["익명키"].astype(str).str.strip(),
            "이름": anon_df["익명키"].astype(str).str.strip(),
            "대회명": anon_df["대회명"].map(_norm_text),
            "대회연도": pd.to_numeric(anon_df["대회연도"], errors="coerce").astype("Int64"),
            "출생년도": pd.to_numeric(anon_df["출생연도"], errors="coerce").astype("Int64"),
            "성별": anon_df["성별"].map(_norm_text),
            "학령구간": anon_df["학령구간"].map(_norm_text),
            "거리": pd.to_numeric(anon_df["거리"], errors="coerce").astype("Int64"),
            "SF여부": anon_df["SF여부"].astype(str).str.strip().str.lower().isin({"y", "yes", "true", "1", "t"}),
            "라운드": anon_df["라운드"].map(_norm_text),
            "라운드종류": anon_df["라운드종류"].map(_norm_text),
            "순위": anon_df["순위"].map(_norm_text),
            "기록_초": pd.to_numeric(anon_df["기록_초"], errors="coerce"),
            "종별": anon_df["종별"].map(_norm_text),
            "일자": anon_df["일자"].map(_norm_text),
            "일자_정규화": anon_df["일자"].map(_norm_text),
            "classCd": anon_df["classCd"].map(_norm_text),
        }
    )
    missing_round_kind = clean["라운드종류"] == ""
    if missing_round_kind.any():
        clean.loc[missing_round_kind, "라운드종류"] = clean.loc[missing_round_kind, "라운드"].map(classify_round)
    missing_class_cd = clean["classCd"] == ""
    if missing_class_cd.any():
        clean.loc[missing_class_cd, "classCd"] = [
            classify_class_cd(name, round_name, round_kind)
            for name, round_name, round_kind in zip(
                clean.loc[missing_class_cd, "대회명"],
                clean.loc[missing_class_cd, "라운드"],
                clean.loc[missing_class_cd, "라운드종류"],
            )
        ]
    clean["시즌시작연도"] = pd.Series(
        [infer_season_start_year(year, date_norm, date_raw) for year, date_norm, date_raw in zip(clean["대회연도"], clean["일자_정규화"], clean["일자"])],
        dtype="Int64",
    )
    level_resolution = [
        resolve_school_level(category, birth_year=birth, season_start_year=season_year)
        for category, birth, season_year in zip(clean["종별"], clean["출생년도"], clean["시즌시작연도"])
    ]
    clean["학령구간"] = [item["stage_final"] for item in level_resolution]
    clean["학년_계산"] = pd.Series([item["grade"] for item in level_resolution], dtype="Int64")
    clean["학령구간_판정근거"] = [item["source"] for item in level_resolution]
    clean["순위_정수"] = pd.Series(clean["순위"].apply(parse_rank), dtype="Int64")
    clean["순위"] = clean["순위_정수"].astype("Int64")
    clean["나이_추정"] = pd.Series([estimate_age(y, b) for y, b in zip(clean["대회연도"], clean["출생년도"])], dtype="Int64")
    clean = clean[clean["idNo"] != ""].copy()
    clean.attrs["year_missing_after_restore"] = int(clean["대회연도"].isna().sum())
    clean.attrs["winter_round_fallback_unknown"] = 0

    athlete = (
        clean[["idNo", "이름", "출생년도", "성별"]]
        .drop_duplicates(subset=["idNo"], keep="first")
        .sort_values(["이름", "idNo"], na_position="last")
    )
    return clean, athlete


def build_stats_from_anon_records():
    clean_df, athlete_df = _load_anon_clean_records()
    placements_df = best_placement(clean_df)
    summary_df = summarize_youth(placements_df, clean_df, athlete_df)
    coverage_df = build_coverage(clean_df)
    stats_distribution_df = build_stats_distribution(clean_df, athlete_df)
    stats_participation_df = build_stats_participation(summary_df, athlete_df)
    (
        season_month_histogram_df,
        participation_df,
        season_activity_df,
        transition_summary_df,
        gap_return_rates_df,
        record_stop_rule_df,
    ) = build_participation_outputs(clean_df)
    validate_anonymous_stats(stats_distribution_df, stats_participation_df)
    class_level_map_df, class_level_year_category_df, class_level_agreement_df, class_level_mismatch_df, class_level_year_readiness_df = build_class_level_diagnostics(
        clean_df
    )
    return (
        coverage_df,
        stats_distribution_df,
        stats_participation_df,
        class_level_map_df,
        class_level_year_category_df,
        class_level_agreement_df,
        class_level_mismatch_df,
        class_level_year_readiness_df,
        season_month_histogram_df,
        participation_df,
        season_activity_df,
        transition_summary_df,
        gap_return_rates_df,
        record_stop_rule_df,
    )


def _ratio_pct(numerator, denominator):
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def _build_merge_suspect_ids(merge_candidates_df):
    if merge_candidates_df is None or merge_candidates_df.empty:
        return set()
    suspects = set()
    flagged = merge_candidates_df[merge_candidates_df["판정"].isin(["review", "reject"])].copy()
    for col in ["주idNo", "부idNo"]:
        if col not in flagged.columns:
            continue
        ids = flagged[col].map(_norm_text)
        suspects.update(id_no for id_no in ids.tolist() if id_no)
    return suspects


def _classify_level_mismatch(stage_a, stage_b, id_no, merge_suspect_ids):
    if id_no and id_no in merge_suspect_ids:
        return "병합오류 의심"
    idx_a = SCHOOL_LEVEL_ORDER.get(stage_a)
    idx_b = SCHOOL_LEVEL_ORDER.get(stage_b)
    if idx_a is None or idx_b is None:
        return "기타 불일치"
    gap = idx_a - idx_b
    if abs(gap) >= 2:
        return "출생연도 오류 의심"
    if gap == 1:
        return "상위 학년 경기 출전 가능"
    if gap == -1:
        return "유급/조기입학 가능"
    return "기타 불일치"


def build_class_level_diagnostics(clean_df, merge_candidates_df=None):
    if clean_df is None or clean_df.empty:
        empty_map = pd.DataFrame(columns=CLASS_LEVEL_MAP_COLS)
        empty_year_category = pd.DataFrame(columns=CLASS_LEVEL_YEAR_CATEGORY_COLS)
        empty_mismatch = pd.DataFrame(columns=CLASS_LEVEL_MISMATCH_COLS)
        empty_readiness = pd.DataFrame(columns=CLASS_LEVEL_YEAR_READINESS_COLS)
        summary = pd.DataFrame(
            [
                {
                    "전체행수": 0,
                    "오픈행수": 0,
                    "오픈비율(%)": 0.0,
                    "오픈행_출생연도기반판정가능행수": 0,
                    "오픈행_출생연도기반판정가능비율(%)": 0.0,
                    "출생연도결측행수": 0,
                    "출생연도결측비율(%)": 0.0,
                    "종별폴백행수": 0,
                    "종별폴백비율(%)": 0.0,
                    "비교가능행수": 0,
                    "일치행수": 0,
                    "일치율(%)": 0.0,
                    "불일치행수": 0,
                    "단계분석_권장시작연도": "",
                    "기준_최소비교행수": READINESS_MIN_COMPARABLE_ROWS,
                    "기준_최소일치율(%)": READINESS_MIN_AGREEMENT_PCT,
                    "기준_최대출생연도결측비율(%)": READINESS_MAX_BIRTH_MISSING_PCT,
                }
            ],
            columns=CLASS_LEVEL_AGREEMENT_COLS,
        )
        return empty_map, empty_year_category, summary, empty_mismatch, empty_readiness

    base = clean_df.copy()
    base["idNo"] = base.get("idNo", "").astype(str).str.strip()
    base["대회연도"] = pd.to_numeric(base.get("대회연도"), errors="coerce").astype("Int64")
    base["출생년도"] = pd.to_numeric(base.get("출생년도"), errors="coerce").astype("Int64")
    base["종별"] = base.get("종별", "").map(_norm_text)
    base["일자_정규화"] = base.get("일자_정규화", "").map(_norm_text)
    base["일자"] = base.get("일자", "").map(_norm_text)
    if "시즌시작연도" not in base.columns:
        base["시즌시작연도"] = pd.Series(
            [infer_season_start_year(year, date_norm, date_raw) for year, date_norm, date_raw in zip(base["대회연도"], base["일자_정규화"], base["일자"])],
            dtype="Int64",
        )
    else:
        base["시즌시작연도"] = pd.to_numeric(base["시즌시작연도"], errors="coerce").astype("Int64")

    resolved_rows = []
    for _, row in base.iterrows():
        resolved = resolve_school_level(
            row.get("종별", ""),
            birth_year=row.get("출생년도"),
            season_start_year=row.get("시즌시작연도"),
        )
        resolved_rows.append(
            {
                "idNo": _norm_text(row.get("idNo")),
                "대회연도": row.get("대회연도"),
                "종별": _norm_text(row.get("종별")),
                "종별정규화키": resolved["category_key"],
                "단계_A": resolved["stage_category"],
                "A_판정규칙": resolved["category_rule"],
                "단계_B": resolved["stage_grade"],
                "단계_최종": resolved["stage_final"],
                "판정근거": resolved["source"],
                "계산학년": resolved["grade"],
                "출생연도결측": pd.isna(row.get("출생년도")),
            }
        )
    level_df = pd.DataFrame(resolved_rows)
    level_df["대회연도"] = pd.to_numeric(level_df["대회연도"], errors="coerce").astype("Int64")
    level_df["계산학년"] = pd.to_numeric(level_df["계산학년"], errors="coerce").astype("Int64")

    map_df = (
        level_df.groupby(["종별", "종별정규화키", "단계_A", "A_판정규칙"], dropna=False)
        .agg(행수=("종별", "size"), 최초연도=("대회연도", "min"), 최신연도=("대회연도", "max"))
        .reset_index()
    )
    map_df["분석포함"] = map_df["단계_A"].isin(SCHOOL_LEVEL_STAGES + [SCHOOL_LEVEL_OPEN]).map(lambda v: "Y" if v else "N")
    map_df["최초연도"] = pd.to_numeric(map_df["최초연도"], errors="coerce").astype("Int64")
    map_df["최신연도"] = pd.to_numeric(map_df["최신연도"], errors="coerce").astype("Int64")
    map_df = map_df[CLASS_LEVEL_MAP_COLS].sort_values(["행수", "종별"], ascending=[False, True]).reset_index(drop=True)

    year_category_df = (
        level_df.groupby(["대회연도", "종별", "단계_A"], dropna=False)
        .size()
        .reset_index(name="행수")
        .sort_values(["대회연도", "행수", "종별"], ascending=[True, False, True], na_position="last")
        .reset_index(drop=True)
    )
    year_category_df = year_category_df[CLASS_LEVEL_YEAR_CATEGORY_COLS]

    open_rows = level_df[level_df["단계_A"] == SCHOOL_LEVEL_OPEN].copy()
    open_birth_resolved = open_rows[open_rows["단계_B"].isin(SCHOOL_LEVEL_STAGES)]
    birth_missing_rows = int(level_df["출생연도결측"].sum())
    fallback_rows = int((level_df["판정근거"] == "category_fallback").sum())

    compare_df = level_df[(level_df["단계_A"].isin(SCHOOL_LEVEL_STAGES)) & (level_df["단계_B"].isin(SCHOOL_LEVEL_STAGES))].copy()
    compare_df["일치여부"] = compare_df["단계_A"] == compare_df["단계_B"]
    merge_suspect_ids = _build_merge_suspect_ids(merge_candidates_df)
    mismatch_df = compare_df[~compare_df["일치여부"]].copy()
    if mismatch_df.empty:
        mismatch_df["불일치유형"] = pd.Series(dtype=str)
    else:
        mismatch_df["불일치유형"] = [
            _classify_level_mismatch(stage_a, stage_b, id_no, merge_suspect_ids)
            for stage_a, stage_b, id_no in zip(mismatch_df["단계_A"], mismatch_df["단계_B"], mismatch_df["idNo"])
        ]

    mismatch_types = ["상위 학년 경기 출전 가능", "유급/조기입학 가능", "출생연도 오류 의심", "병합오류 의심", "기타 불일치"]
    mismatch_rows = []
    mismatch_total = len(mismatch_df)
    for mismatch_type in mismatch_types:
        count = int((mismatch_df["불일치유형"] == mismatch_type).sum()) if mismatch_total else 0
        mismatch_rows.append({"불일치유형": mismatch_type, "건수": count, "비율(%)": _ratio_pct(count, mismatch_total)})
    mismatch_summary_df = pd.DataFrame(mismatch_rows, columns=CLASS_LEVEL_MISMATCH_COLS)

    readiness_rows = []
    year_candidates = [int(year) for year in sorted(level_df["대회연도"].dropna().astype(int).unique().tolist())]
    for year in year_candidates:
        year_rows = level_df[level_df["대회연도"] == year]
        year_compare = compare_df[compare_df["대회연도"] == year]
        total_rows = int(len(year_rows))
        compare_rows = int(len(year_compare))
        match_rows = int(year_compare["일치여부"].sum()) if compare_rows else 0
        agree_pct = _ratio_pct(match_rows, compare_rows)
        open_pct = _ratio_pct(int((year_rows["단계_A"] == SCHOOL_LEVEL_OPEN).sum()), total_rows)
        birth_missing_pct = _ratio_pct(int(year_rows["출생연도결측"].sum()), total_rows)
        reasons = []
        if compare_rows < READINESS_MIN_COMPARABLE_ROWS:
            reasons.append("비교표본부족")
        if agree_pct < READINESS_MIN_AGREEMENT_PCT:
            reasons.append("일치율미달")
        if birth_missing_pct > READINESS_MAX_BIRTH_MISSING_PCT:
            reasons.append("출생연도결측과다")
        usable = not reasons
        readiness_rows.append(
            {
                "대회연도": year,
                "전체행수": total_rows,
                "비교가능행수": compare_rows,
                "일치행수": match_rows,
                "일치율(%)": agree_pct,
                "오픈비율(%)": open_pct,
                "출생연도결측비율(%)": birth_missing_pct,
                "단계분석사용가능": "Y" if usable else "N",
                "판정사유": "충족" if usable else ", ".join(reasons),
            }
        )
    readiness_df = pd.DataFrame(readiness_rows, columns=CLASS_LEVEL_YEAR_READINESS_COLS)

    recommended_year = ""
    if not readiness_df.empty:
        usable_rows = readiness_df[readiness_df["단계분석사용가능"] == "Y"]
        if not usable_rows.empty:
            recommended_year = str(int(usable_rows["대회연도"].min()))

    compare_rows_total = int(len(compare_df))
    match_rows_total = int(compare_df["일치여부"].sum()) if compare_rows_total else 0
    mismatch_rows_total = compare_rows_total - match_rows_total
    agreement_summary_df = pd.DataFrame(
        [
            {
                "전체행수": int(len(level_df)),
                "오픈행수": int(len(open_rows)),
                "오픈비율(%)": _ratio_pct(len(open_rows), len(level_df)),
                "오픈행_출생연도기반판정가능행수": int(len(open_birth_resolved)),
                "오픈행_출생연도기반판정가능비율(%)": _ratio_pct(len(open_birth_resolved), len(open_rows)),
                "출생연도결측행수": birth_missing_rows,
                "출생연도결측비율(%)": _ratio_pct(birth_missing_rows, len(level_df)),
                "종별폴백행수": fallback_rows,
                "종별폴백비율(%)": _ratio_pct(fallback_rows, len(level_df)),
                "비교가능행수": compare_rows_total,
                "일치행수": match_rows_total,
                "일치율(%)": _ratio_pct(match_rows_total, compare_rows_total),
                "불일치행수": mismatch_rows_total,
                "단계분석_권장시작연도": recommended_year,
                "기준_최소비교행수": READINESS_MIN_COMPARABLE_ROWS,
                "기준_최소일치율(%)": READINESS_MIN_AGREEMENT_PCT,
                "기준_최대출생연도결측비율(%)": READINESS_MAX_BIRTH_MISSING_PCT,
            }
        ],
        columns=CLASS_LEVEL_AGREEMENT_COLS,
    )
    return map_df, year_category_df, agreement_summary_df, mismatch_summary_df, readiness_df


def print_class_level_diagnostics(agreement_summary_df, readiness_df, mismatch_summary_df):
    if agreement_summary_df is None or agreement_summary_df.empty:
        return
    row = agreement_summary_df.iloc[0]
    print(
        "[단계 판정] A/B 일치율 {0:.2f}% ({1}/{2}), 종별 폴백 {3}행 ({4:.2f}%), 출생연도 결측 {5}행 ({6:.2f}%)".format(
            float(row["일치율(%)"]),
            int(row["일치행수"]),
            int(row["비교가능행수"]),
            int(row["종별폴백행수"]),
            float(row["종별폴백비율(%)"]),
            int(row["출생연도결측행수"]),
            float(row["출생연도결측비율(%)"]),
        )
    )
    print(
        "[단계 판정] 오픈 행 {0}건, 출생연도 기반 단계 판정 가능 {1}건 ({2:.2f}%)".format(
            int(row["오픈행수"]),
            int(row["오픈행_출생연도기반판정가능행수"]),
            float(row["오픈행_출생연도기반판정가능비율(%)"]),
        )
    )
    start_year = _norm_text(row["단계분석_권장시작연도"])
    if start_year:
        print(f"[단계 판정] 권장 분석 시작 연도: {start_year}년")
    else:
        print("[단계 판정] 권장 분석 시작 연도: 없음(기준 미충족)")
    if mismatch_summary_df is not None and not mismatch_summary_df.empty:
        top = mismatch_summary_df.sort_values(["건수", "불일치유형"], ascending=[False, True]).iloc[0]
        print(f"[단계 판정] 최다 불일치 유형: {top['불일치유형']} ({int(top['건수'])}건)")


def _norm_group_frame(df, id_col="idNo"):
    key_df = df.copy()
    key_df[id_col] = key_df[id_col].astype(str).str.strip()
    key_df["성별"] = key_df["성별"].map(_norm_text)
    key_df["거리"] = pd.to_numeric(key_df["거리"], errors="coerce").astype("Int64")
    key_df["출생연도"] = pd.to_numeric(key_df["출생연도"], errors="coerce").astype("Int64")
    return key_df


def _is_shorttrack(series):
    return series.map(_norm_text) == SHORTTRACK_CLASS_CD


def _stats_time_outlier_mask(distances, times):
    flags = []
    for distance, value in zip(distances, times):
        if pd.isna(distance) or pd.isna(value):
            flags.append(False)
            continue
        lower = STATS_TIME_LOWER_BOUNDS.get(int(distance))
        flags.append(lower is not None and float(value) < lower)
    return pd.Series(flags, index=times.index, dtype=bool)


def _build_time_stats_base(clean_df, profiles):
    base = all_times(clean_df).copy()
    log = {"전체": int(len(base))}
    if base.empty:
        empty = pd.DataFrame(columns=DIST_GROUP_COLS + ["idNo", "기록_초"])
        empty.attrs["filter_log"] = log
        return empty
    base["idNo"] = base["idNo"].astype(str).str.strip()
    if "성별" not in base.columns:
        base = base.merge(profiles[["idNo", "성별"]], on="idNo", how="left")
    base["출생연도"] = pd.to_numeric(base.get("출생년도"), errors="coerce").astype("Int64")
    base["거리"] = pd.to_numeric(base["거리"], errors="coerce").astype("Int64")
    base["성별"] = base["성별"].map(_norm_text)
    base["classCd"] = base.get("classCd", "").map(_norm_text)

    speed_mask = ~_is_shorttrack(base["classCd"])
    log["classCd≠2 제외"] = int(speed_mask.sum())
    log["  (그중 거리 결측)"] = int((speed_mask & base["거리"].isna()).sum())
    base = base[~speed_mask]

    round_mask = base["라운드종류"] != "예선"
    log["라운드 필터 제외"] = int(round_mask.sum())
    base = base[~round_mask]

    time_missing = base["기록_초"].isna()
    log["기록 결측"] = int(time_missing.sum())
    base = base[~time_missing]

    birth_missing = base["출생연도"].isna()
    log["출생연도 결측"] = int(birth_missing.sum())
    base = base[~birth_missing]

    distance_missing = base["거리"].isna()
    log["거리 결측"] = int(distance_missing.sum())
    base = base[~distance_missing]

    gender_missing = base["성별"] == ""
    log["성별 결측"] = int(gender_missing.sum())
    base = base[~gender_missing]

    outlier_mask = _stats_time_outlier_mask(base["거리"], base["기록_초"])
    log["이상치 제외"] = int(outlier_mask.sum())
    base = base[~outlier_mask]

    base = base[base["idNo"] != ""]
    log["집계 대상"] = int(len(base))
    out = _norm_group_frame(base)[DIST_GROUP_COLS + ["idNo", "기록_초"]].copy()
    out.attrs["filter_log"] = log
    return out


def _build_rank_stats_base(clean_df, profiles):
    log = {"전체": int(len(clean_df))}
    if clean_df.empty:
        empty = pd.DataFrame(columns=DIST_GROUP_COLS + ["idNo", "순위"])
        empty.attrs["filter_log"] = log
        return empty
    source = clean_df.copy()
    source["classCd"] = source.get("classCd", "").map(_norm_text)
    speed_mask = ~_is_shorttrack(source["classCd"])
    log["classCd≠2 제외"] = int(speed_mask.sum())
    source = source[~speed_mask]

    # 순위는 선수·대회·종목당 1건만 사용해야 하므로 성적 우선순위(채점종합 > 결승/결승B) 결과에서 고른다.
    base = best_placement(source).copy()
    log["성적 행 선택"] = int(len(base))
    base["idNo"] = base["idNo"].astype(str).str.strip()
    base["순위"] = pd.to_numeric(base["순위"], errors="coerce")
    base["거리"] = pd.to_numeric(base["거리"], errors="coerce").astype("Int64")
    base["학령구간"] = base["학령구간"].map(_norm_text)

    round_mask = ~base["라운드종류"].isin(["채점종합", "결승"])
    log["결승B·기타 라운드 제외"] = int(round_mask.sum())
    base = base[~round_mask]

    # 오픈(종별이 여자부/남자부)은 성인 국가대표까지 섞이는 경기라 학령 경기와 순위 의미가 다르다.
    open_mask = base["학령구간"] == "오픈"
    log["오픈 경기 제외"] = int(open_mask.sum())
    base = base[~open_mask]

    rank_missing = base["순위"].isna()
    log["순위 결측"] = int(rank_missing.sum())
    base = base[~rank_missing]

    distance_missing = base["거리"].isna()
    log["거리 결측"] = int(distance_missing.sum())
    base = base[~distance_missing]

    base = base[["idNo", "거리", "순위"]].merge(profiles, on="idNo", how="left")
    base["성별"] = base["성별"].map(_norm_text)
    base["출생연도"] = pd.to_numeric(base["출생연도"], errors="coerce").astype("Int64")

    birth_missing = base["출생연도"].isna()
    log["출생연도 결측"] = int(birth_missing.sum())
    base = base[~birth_missing]

    gender_missing = base["성별"] == ""
    log["성별 결측"] = int(gender_missing.sum())
    base = base[~gender_missing]

    base = base[base["idNo"].astype(str).str.strip() != ""]
    log["집계 대상"] = int(len(base))
    out = _norm_group_frame(base)[DIST_GROUP_COLS + ["idNo", "순위"]].copy()
    out.attrs["filter_log"] = log
    return out


def _quantile_columns(base, value_col, quantiles, column_names):
    if base.empty:
        return pd.DataFrame(columns=column_names)
    frame = base.groupby(DIST_GROUP_COLS, dropna=False)[value_col].quantile(quantiles).unstack()
    frame.columns = column_names
    return frame


def build_stats_distribution(clean_df, athlete_df):
    profiles = build_athlete_profiles(athlete_df)
    time_base = _build_time_stats_base(clean_df, profiles)
    rank_base = _build_rank_stats_base(clean_df, profiles)
    filter_log = {"기록": time_base.attrs.get("filter_log", {}), "순위": rank_base.attrs.get("filter_log", {})}

    if time_base.empty and rank_base.empty:
        out = pd.DataFrame(columns=DIST_OUTPUT_COLS)
        out.attrs["filter_log"] = filter_log
        return out

    time_ids = time_base[DIST_GROUP_COLS + ["idNo"]].drop_duplicates()
    rank_ids = rank_base[DIST_GROUP_COLS + ["idNo"]].drop_duplicates()
    time_counts = time_ids.groupby(DIST_GROUP_COLS, dropna=False)["idNo"].nunique().rename("기록인원")
    rank_counts = rank_ids.groupby(DIST_GROUP_COLS, dropna=False)["idNo"].nunique().rename("순위인원")
    time_stats = _quantile_columns(time_base, "기록_초", DIST_TIME_QUANTILES, DIST_TIME_COLS)
    rank_stats = _quantile_columns(rank_base, "순위", DIST_RANK_QUANTILES, DIST_RANK_COLS)

    # 실제 데이터가 있는 조합만 남긴다. 존재하지 않는 조합은 행으로 만들지 않는다.
    stats = pd.concat([time_counts, rank_counts, time_stats, rank_stats], axis=1).reset_index()
    rows = []
    for _, item in stats.iterrows():
        row = {
            "출생연도": int(item["출생연도"]),
            "성별": item["성별"],
            "거리": int(item["거리"]),
        }
        time_count = _count_or_zero(item.get("기록인원"))
        rank_count = _count_or_zero(item.get("순위인원"))
        # 기록과 순위는 필터가 달라 표본 크기가 다르므로 k-익명 판정을 각각 독립으로 한다.
        if time_count < K_ANONYMITY_MIN:
            row["기록_인원수"] = INSUFFICIENT_TEXT
            for col in DIST_TIME_COLS:
                row[col] = INSUFFICIENT_TEXT
        else:
            row["기록_인원수"] = time_count
            for col in DIST_TIME_COLS:
                row[col] = _round_or_none(item.get(col), digits=3)
        if rank_count < K_ANONYMITY_MIN:
            row["순위_인원수"] = INSUFFICIENT_TEXT
            for col in DIST_RANK_COLS:
                row[col] = INSUFFICIENT_TEXT
        else:
            row["순위_인원수"] = rank_count
            for col in DIST_RANK_COLS:
                row[col] = _round_or_none(item.get(col), digits=2)
        rows.append(row)
    out = pd.DataFrame(rows, columns=DIST_OUTPUT_COLS)
    if not out.empty:
        out = out.sort_values(["출생연도", "성별", "거리"], na_position="last").reset_index(drop=True)
    out.attrs["filter_log"] = filter_log
    return out


def print_stats_filter_log(distribution_df):
    filter_log = distribution_df.attrs.get("filter_log") or {}
    for label, stages in filter_log.items():
        if not stages:
            continue
        print(f"[{label} 통계] 집계 단계별 행수")
        for name, value in stages.items():
            print(f"  {name}: {value}행")


def _insufficient_row(row, metric_cols):
    row["인원수"] = INSUFFICIENT_TEXT
    for col in metric_cols:
        row[col] = INSUFFICIENT_TEXT
    return row


def build_stats_participation(summary_df, athlete_df):
    profiles = build_athlete_profiles(athlete_df)
    base = summary_df.copy()
    base["idNo"] = base["idNo"].astype(str).str.strip()
    base = base[base["idNo"] != ""].copy()
    base["최초_출전나이"] = pd.to_numeric(base["최초_출전나이"], errors="coerce").astype("Int64")
    base["초등부_출전수"] = pd.to_numeric(base["초등부_출전수"], errors="coerce").astype("Int64")
    base = base[["idNo", "최초_출전나이", "초등부_출전수"]].merge(profiles, on="idNo", how="left")
    base["성별"] = base["성별"].astype(str).str.strip()
    base["출생연도"] = pd.to_numeric(base["출생연도"], errors="coerce").astype("Int64")
    base = base[(base["성별"] != "") & base["출생연도"].notna()].copy()
    if base.empty:
        return pd.DataFrame(columns=PART_OUTPUT_COLS)

    rows = []
    for (birth, gender), group in base.groupby(["출생연도", "성별"], sort=True, dropna=False):
        athlete_count = int(group["idNo"].nunique())
        first_age_count = int(group[group["최초_출전나이"].notna()]["idNo"].nunique())
        elem_count = int(group[group["초등부_출전수"].notna()]["idNo"].nunique())
        row = {"출생연도": int(birth), "성별": gender}
        if athlete_count < K_ANONYMITY_MIN or first_age_count < K_ANONYMITY_MIN or elem_count < K_ANONYMITY_MIN:
            rows.append(_insufficient_row(row, ["최초출전나이_p25", "최초출전나이_p50", "최초출전나이_p75", "초등부출전수_p50"]))
            continue
        row["최초출전나이_p25"] = _quantile_or_none(group["최초_출전나이"], 0.25, digits=1)
        row["최초출전나이_p50"] = _quantile_or_none(group["최초_출전나이"], 0.50, digits=1)
        row["최초출전나이_p75"] = _quantile_or_none(group["최초_출전나이"], 0.75, digits=1)
        row["초등부출전수_p50"] = _quantile_or_none(group["초등부_출전수"], 0.50, digits=1)
        row["인원수"] = athlete_count
        rows.append(row)

    out = pd.DataFrame(rows, columns=PART_OUTPUT_COLS)
    if out.empty:
        return out
    return out.sort_values(["출생연도", "성별"], na_position="last")


def _month_label(month):
    if month is None:
        return "미상"
    return f"{int(month)}월"


def _season_bucket_label(month):
    if month is None:
        return "미상"
    if int(month) >= SEASON_START_MONTH:
        return f"{SEASON_START_MONTH}~12월(시즌 시작 구간)"
    return f"1~{SEASON_START_MONTH - 1}월(시즌 종료 구간)"


def build_season_month_histogram(clean_df):
    if clean_df is None or clean_df.empty:
        out = pd.DataFrame(columns=SEASON_MONTH_HISTOGRAM_COLS)
        out.attrs["known_meets"] = 0
        out.attrs["unknown_meets"] = 0
        out.attrs["start_bucket_meets"] = 0
        out.attrs["end_bucket_meets"] = 0
        return out
    base = clean_df.copy()
    base["대회명"] = base.get("대회명", "").map(_norm_text)
    base["대회연도"] = pd.to_numeric(base.get("대회연도"), errors="coerce").astype("Int64")
    base["일자_정규화"] = base.get("일자_정규화", "").map(_norm_text)
    base["일자"] = base.get("일자", "").map(_norm_text)
    base = base[base["대회명"] != ""].copy()
    if base.empty:
        out = pd.DataFrame(columns=SEASON_MONTH_HISTOGRAM_COLS)
        out.attrs["known_meets"] = 0
        out.attrs["unknown_meets"] = 0
        out.attrs["start_bucket_meets"] = 0
        out.attrs["end_bucket_meets"] = 0
        return out

    base["대회연도_key"] = base["대회연도"].fillna(-1).astype("Int64")
    month_rows = []
    for (meet_year, meet_name), group in base.groupby(["대회연도_key", "대회명"], sort=False, dropna=False):
        months = []
        for normalized_date, raw_date in zip(group["일자_정규화"], group["일자"]):
            month = _extract_month_from_date(normalized_date, raw_date)
            if month is not None:
                months.append(month)
        selected_month = min(months) if months else None
        month_rows.append({"대회연도_key": int(meet_year), "대회명": meet_name, "월": selected_month})

    month_df = pd.DataFrame(month_rows)
    if month_df.empty:
        out = pd.DataFrame(columns=SEASON_MONTH_HISTOGRAM_COLS)
        out.attrs["known_meets"] = 0
        out.attrs["unknown_meets"] = 0
        out.attrs["start_bucket_meets"] = 0
        out.attrs["end_bucket_meets"] = 0
        return out

    month_df["월_key"] = month_df["월"].apply(lambda value: int(value) if value is not None else 0)
    month_counts = month_df.groupby("월_key", dropna=False).size().to_dict()
    total_meets = int(sum(month_counts.values()))

    rows = []
    ordered_months = list(range(1, 13)) + ([0] if 0 in month_counts else [])
    for month_key in ordered_months:
        count = int(month_counts.get(month_key, 0))
        if count <= 0:
            continue
        month_value = None if month_key == 0 else month_key
        ratio = round((count / total_meets) * 100.0, 2) if total_meets else 0.0
        rows.append(
            {
                "월": month_key,
                "월라벨": _month_label(month_value),
                "시즌구간": _season_bucket_label(month_value),
                "대회수": count,
                "대회비율(%)": ratio,
            }
        )
    out = pd.DataFrame(rows, columns=SEASON_MONTH_HISTOGRAM_COLS)
    if not out.empty:
        out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
        out["대회수"] = pd.to_numeric(out["대회수"], errors="coerce").astype("Int64")

    known_meets = int(month_df["월"].notna().sum())
    unknown_meets = int(month_df["월"].isna().sum())
    start_bucket_meets = int(month_df[month_df["월"].fillna(0).astype(int) >= SEASON_START_MONTH].shape[0])
    end_bucket_meets = int(month_df[(month_df["월"].fillna(0).astype(int) > 0) & (month_df["월"].fillna(0).astype(int) < SEASON_START_MONTH)].shape[0])
    out.attrs["known_meets"] = known_meets
    out.attrs["unknown_meets"] = unknown_meets
    out.attrs["start_bucket_meets"] = start_bucket_meets
    out.attrs["end_bucket_meets"] = end_bucket_meets
    return out


def _safe_bool_text(value):
    return "Y" if bool(value) else "N"


def _to_anon_key(id_no, anon_salt):
    text = _norm_text(id_no)
    if not text:
        return ""
    if ANON_KEY_RE.fullmatch(text):
        return text
    if anon_salt:
        return hashlib.sha256(f"{text}{anon_salt}".encode("utf-8")).hexdigest()[:12]
    return text


def _resolve_category_stage(category_series):
    stage_counts = {}
    for value in category_series.tolist():
        stage = classify_school_level_from_category(value).get("stage")
        if stage == SCHOOL_LEVEL_OPEN:
            continue
        if stage not in SCHOOL_LEVEL_STAGES:
            continue
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    if not stage_counts:
        return ""
    ordered = sorted(stage_counts.items(), key=lambda item: (-item[1], SCHOOL_LEVEL_ORDER.get(item[0], 99), item[0]))
    return ordered[0][0]


def _sorted_class_codes(values):
    code_set = {value for value in (_norm_text(item) for item in values) if value}
    if not code_set:
        return ""
    numeric_codes = sorted([code for code in code_set if code.isdigit()], key=lambda code: int(code))
    text_codes = sorted([code for code in code_set if not code.isdigit()])
    return "|".join(numeric_codes + text_codes)


def build_participation_table(clean_df):
    if clean_df is None or clean_df.empty:
        out = pd.DataFrame(columns=PARTICIPATION_OUTPUT_COLS)
        out.attrs["excluded_birth_missing_rows"] = 0
        out.attrs["excluded_grade_non_positive_rows"] = 0
        out.attrs["excluded_missing_season_rows"] = 0
        out.attrs["raw_key_rows"] = 0
        return out

    base = clean_df.copy()
    base["idNo"] = base.get("idNo", "").astype(str).str.strip()
    base["출생년도"] = pd.to_numeric(base.get("출생년도"), errors="coerce").astype("Int64")
    base["성별"] = base.get("성별", "").map(_norm_text)
    base["종별"] = base.get("종별", "").map(_norm_text)
    base["classCd"] = base.get("classCd", "").map(_norm_text)
    base["대회명"] = base.get("대회명", "").map(_norm_text)
    base["대회연도"] = pd.to_numeric(base.get("대회연도"), errors="coerce").astype("Int64")
    base["일자_정규화"] = base.get("일자_정규화", "").map(_norm_text)
    base["일자"] = base.get("일자", "").map(_norm_text)
    if "시즌시작연도" in base.columns:
        base["시즌시작연도"] = pd.to_numeric(base["시즌시작연도"], errors="coerce").astype("Int64")
    else:
        base["시즌시작연도"] = pd.Series(
            [infer_season_start_year(year, date_norm, date_raw) for year, date_norm, date_raw in zip(base["대회연도"], base["일자_정규화"], base["일자"])],
            dtype="Int64",
        )
    base["학년"] = pd.Series([calculate_school_grade(season, birth) for season, birth in zip(base["시즌시작연도"], base["출생년도"])], dtype="Int64")
    base["단계"] = [classify_school_level_from_grade(grade) for grade in base["학년"]]
    category_stage = [classify_school_level_from_category(category).get("stage") for category in base["종별"]]
    base["오픈행"] = [stage == SCHOOL_LEVEL_OPEN for stage in category_stage]

    anon_salt = _norm_text(os.environ.get("SPLITS_ANON_SALT"))
    base["익명키"] = [_to_anon_key(id_no, anon_salt) for id_no in base["idNo"]]
    base["meet_key"] = [
        "|".join(
            [
                _norm_text(meet_year),
                _norm_text(meet_name),
            ]
        )
        for meet_year, meet_name in zip(base["대회연도"], base["대회명"])
    ]
    base["meet_key"] = base["meet_key"].map(lambda value: value if value != "|" else "")

    valid = (base["익명키"] != "") & base["시즌시작연도"].notna() & base["출생년도"].notna() & base["학년"].notna() & (base["학년"] > 0)
    filtered = base[valid].copy()
    if filtered.empty:
        out = pd.DataFrame(columns=PARTICIPATION_OUTPUT_COLS)
        out.attrs["excluded_birth_missing_rows"] = int(base["출생년도"].isna().sum())
        out.attrs["excluded_grade_non_positive_rows"] = int((base["학년"].fillna(0) <= 0).sum())
        out.attrs["excluded_missing_season_rows"] = int(base["시즌시작연도"].isna().sum())
        out.attrs["raw_key_rows"] = int(
            (base["익명키"].map(_norm_text).map(lambda value: bool(value) and not bool(ANON_KEY_RE.fullmatch(value)))).sum()
        )
        return out

    rows = []
    for (anon_key, season), group in filtered.groupby(["익명키", "시즌시작연도"], sort=True, dropna=False):
        birth_year_values = pd.to_numeric(group["출생년도"], errors="coerce").dropna()
        birth_year = int(birth_year_values.iloc[0]) if not birth_year_values.empty else None
        gender = _first_non_empty(group["성별"])
        grade_values = pd.to_numeric(group["학년"], errors="coerce").dropna()
        grade = int(grade_values.iloc[0]) if not grade_values.empty else None
        stage = classify_school_level_from_grade(grade)
        meet_keys = [value for value in group["meet_key"].tolist() if _norm_text(value)]
        rows.append(
            {
                "익명키": _norm_text(anon_key),
                "시즌": int(season),
                "출생연도": birth_year,
                "성별": gender,
                "학년": grade,
                "단계": stage if stage in SCHOOL_LEVEL_STAGES else "",
                "종별_단계": _resolve_category_stage(group["종별"]),
                "대회수": len(set(meet_keys)),
                "경기수": int(len(group)),
                "classCd목록": _sorted_class_codes(group["classCd"].tolist()),
                "오픈참가": _safe_bool_text(bool(group["오픈행"].any())),
            }
        )

    out = pd.DataFrame(rows, columns=PARTICIPATION_OUTPUT_COLS)
    if not out.empty:
        for col in ["시즌", "출생연도", "학년", "대회수", "경기수"]:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
        out = out.sort_values(["시즌", "익명키"], ascending=[True, True]).reset_index(drop=True)

    raw_key_rows = int((out["익명키"].map(_norm_text).map(lambda value: bool(value) and not bool(ANON_KEY_RE.fullmatch(value)))).sum()) if not out.empty else 0
    out.attrs["excluded_birth_missing_rows"] = int(base["출생년도"].isna().sum())
    out.attrs["excluded_grade_non_positive_rows"] = int((base["학년"].fillna(0) <= 0).sum())
    out.attrs["excluded_missing_season_rows"] = int(base["시즌시작연도"].isna().sum())
    out.attrs["raw_key_rows"] = raw_key_rows
    return out


def _parse_class_code_set(value):
    tokens = [token.strip() for token in re.split(r"[|,/]", _norm_text(value)) if token.strip()]
    return set(tokens)


def _class_profile_label(class_codes):
    has_speed = SPEED_CLASS_CD in class_codes
    has_short = SHORTTRACK_CLASS_CD in class_codes
    if has_speed and has_short:
        return "병행"
    if has_short and not has_speed:
        return "쇼트트랙 전용"
    if has_speed and not has_short:
        return "스피드 전용"
    return "기타"


def build_activity_and_transition_summary(participation_df):
    if participation_df is None or participation_df.empty:
        return pd.DataFrame(columns=SEASON_ACTIVITY_OUTPUT_COLS), pd.DataFrame(columns=CLASS_TRANSITION_OUTPUT_COLS)
    base = participation_df.copy()
    base["익명키"] = base.get("익명키", "").map(_norm_text)
    base["시즌"] = pd.to_numeric(base.get("시즌"), errors="coerce").astype("Int64")
    base = base[(base["익명키"] != "") & base["시즌"].notna()].copy()
    if base.empty:
        return pd.DataFrame(columns=SEASON_ACTIVITY_OUTPUT_COLS), pd.DataFrame(columns=CLASS_TRANSITION_OUTPUT_COLS)

    season_activity = (
        base.groupby("시즌", dropna=False)["익명키"].nunique().reset_index(name="활동선수수").sort_values("시즌").reset_index(drop=True)
    )
    season_activity["시즌"] = pd.to_numeric(season_activity["시즌"], errors="coerce").astype("Int64")
    season_activity["활동선수수"] = pd.to_numeric(season_activity["활동선수수"], errors="coerce").astype("Int64")
    season_activity = season_activity[SEASON_ACTIVITY_OUTPUT_COLS]

    transition_rows = []
    for anon_key, group in base.sort_values(["익명키", "시즌"], ascending=[True, True]).groupby("익명키", sort=False):
        entries = []
        for _, row in group.iterrows():
            class_codes = _parse_class_code_set(row.get("classCd목록", ""))
            entries.append(
                {
                    "시즌": int(row["시즌"]),
                    "profile": _class_profile_label(class_codes),
                    "class_codes": class_codes,
                }
            )
        for index, current in enumerate(entries):
            previous_profile = entries[index - 1]["profile"] if index > 0 else None
            next_codes = entries[index + 1]["class_codes"] if index + 1 < len(entries) else None
            status = "전환" if previous_profile and current["profile"] != previous_profile else current["profile"]
            shorttrack_stop = int(SHORTTRACK_CLASS_CD in current["class_codes"] and (next_codes is None or SHORTTRACK_CLASS_CD not in next_codes))
            skating_stop = int(next_codes is None)
            transition_rows.append(
                {
                    "익명키": anon_key,
                    "시즌": current["시즌"],
                    "분류": status,
                    "쇼트트랙중단": shorttrack_stop,
                    "빙상중단": skating_stop,
                }
            )

    transition_df = pd.DataFrame(transition_rows)
    if transition_df.empty:
        return season_activity, pd.DataFrame(columns=CLASS_TRANSITION_OUTPUT_COLS)

    rows = []
    for season, group in transition_df.groupby("시즌", sort=True):
        rows.append(
            {
                "시즌": int(season),
                "활동선수수": int(len(group)),
                "쇼트트랙전용수": int((group["분류"] == "쇼트트랙 전용").sum()),
                "스피드전용수": int((group["분류"] == "스피드 전용").sum()),
                "병행수": int((group["분류"] == "병행").sum()),
                "전환수": int((group["분류"] == "전환").sum()),
                "기타수": int((group["분류"] == "기타").sum()),
                "쇼트트랙중단수": int(group["쇼트트랙중단"].sum()),
                "빙상중단수": int(group["빙상중단"].sum()),
            }
        )
    transition_summary = pd.DataFrame(rows, columns=CLASS_TRANSITION_OUTPUT_COLS).sort_values("시즌").reset_index(drop=True)
    for col in CLASS_TRANSITION_OUTPUT_COLS:
        transition_summary[col] = pd.to_numeric(transition_summary[col], errors="coerce").astype("Int64")
    return season_activity, transition_summary


def build_gap_return_episodes(participation_df):
    columns = ["익명키", "시작시즌", "시작학년", "관측공백시즌수", "복귀여부", "복귀공백시즌수"]
    if participation_df is None or participation_df.empty:
        return pd.DataFrame(columns=columns)
    base = participation_df.copy()
    base["익명키"] = base.get("익명키", "").map(_norm_text)
    base["시즌"] = pd.to_numeric(base.get("시즌"), errors="coerce").astype("Int64")
    base["학년"] = pd.to_numeric(base.get("학년"), errors="coerce").astype("Int64")
    base["classCd목록"] = base.get("classCd목록", "").map(_norm_text)
    base = base[(base["익명키"] != "") & base["시즌"].notna()].copy()
    if base.empty:
        return pd.DataFrame(columns=columns)

    max_season = int(base["시즌"].max())
    rows = []
    grouped = base.sort_values(["익명키", "시즌"], ascending=[True, True]).groupby("익명키", sort=False)
    for anon_key, group in grouped:
        entries = []
        for _, row in group.iterrows():
            season = _to_int_or_none(row.get("시즌"))
            if season is None:
                continue
            entries.append(
                {
                    "시즌": season,
                    "학년": _to_int_or_none(row.get("학년")),
                    "class_codes": _parse_class_code_set(row.get("classCd목록", "")),
                }
            )
        if not entries:
            continue

        for idx, current in enumerate(entries):
            if SHORTTRACK_CLASS_CD not in current["class_codes"]:
                continue
            next_entry = entries[idx + 1] if idx + 1 < len(entries) else None
            if next_entry is None:
                observed_gap = max(0, max_season - current["시즌"])
                returned = "N"
                return_gap = pd.NA
            else:
                observed_gap = max(0, next_entry["시즌"] - current["시즌"] - 1)
                returned = "Y"
                return_gap = observed_gap
            if observed_gap < 1:
                continue
            rows.append(
                {
                    "익명키": anon_key,
                    "시작시즌": current["시즌"],
                    "시작학년": current["학년"],
                    "관측공백시즌수": observed_gap,
                    "복귀여부": returned,
                    "복귀공백시즌수": return_gap,
                }
            )

    out = pd.DataFrame(rows, columns=columns)
    if out.empty:
        return out
    for col in ["시작시즌", "시작학년", "관측공백시즌수", "복귀공백시즌수"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    return out


def build_gap_return_rates(gap_episode_df):
    out = pd.DataFrame(columns=GAP_RETURN_RATE_OUTPUT_COLS)
    if gap_episode_df is None or gap_episode_df.empty:
        return out

    rows = []
    for segment_label, start_grade in GAP_RETURN_SEGMENTS:
        segment = gap_episode_df if start_grade is None else gap_episode_df[gap_episode_df["시작학년"] == start_grade]
        total_cases = int(len(segment))
        for bucket_label, min_gap in GAP_RETURN_BUCKETS:
            eligible = segment[segment["관측공백시즌수"] >= min_gap]
            case_count = int(len(eligible))
            return_count = int((eligible["복귀여부"] == "Y").sum())
            rows.append(
                {
                    "구간": segment_label,
                    "공백시즌수": bucket_label,
                    "사례수": case_count,
                    "복귀사례": return_count,
                    "복귀율(%)": _ratio_pct(return_count, case_count) if case_count else pd.NA,
                    "관측부족제외수": int(total_cases - case_count),
                }
            )
    out = pd.DataFrame(rows, columns=GAP_RETURN_RATE_OUTPUT_COLS)
    for col in ["사례수", "복귀사례", "관측부족제외수"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    out["복귀율(%)"] = pd.to_numeric(out["복귀율(%)"], errors="coerce")
    return out


def build_record_stop_rule(gap_return_rates_df):
    row = {
        "기준식": RECORD_STOP_RULE_TEXT,
        "복귀율기준(%)": RECORD_STOP_MAX_RETURN_RATE_PCT,
        "분모기준": RECORD_STOP_MIN_CASES,
        "확정n": "보류",
        "근거구간": "",
        "근거사례수": pd.NA,
        "근거복귀사례": pd.NA,
        "근거복귀율(%)": pd.NA,
        "근거문장": "공백 복귀율 집계가 없어 기록 중단 기준을 확정하지 못했습니다.",
    }
    if gap_return_rates_df is None or gap_return_rates_df.empty:
        return pd.DataFrame([row], columns=RECORD_STOP_RULE_OUTPUT_COLS)

    overall = gap_return_rates_df[gap_return_rates_df["구간"] == "전체"].copy()
    if overall.empty:
        return pd.DataFrame([row], columns=RECORD_STOP_RULE_OUTPUT_COLS)
    overall["최소공백시즌수"] = [
        4 if _norm_text(label) == "4+" else _to_int_or_none(label)
        for label in overall["공백시즌수"].tolist()
    ]
    overall["사례수"] = pd.to_numeric(overall["사례수"], errors="coerce").astype("Int64")
    overall["복귀사례"] = pd.to_numeric(overall["복귀사례"], errors="coerce").astype("Int64")
    overall["복귀율(%)"] = pd.to_numeric(overall["복귀율(%)"], errors="coerce")
    overall = overall[overall["최소공백시즌수"].notna()].copy()
    if overall.empty:
        return pd.DataFrame([row], columns=RECORD_STOP_RULE_OUTPUT_COLS)

    eligible = overall[
        overall["사례수"].notna()
        & (overall["사례수"] >= RECORD_STOP_MIN_CASES)
        & overall["복귀율(%)"].notna()
        & (overall["복귀율(%)"] <= RECORD_STOP_MAX_RETURN_RATE_PCT)
    ].copy()
    if not eligible.empty:
        selected = eligible.sort_values(["최소공백시즌수", "복귀율(%)"], ascending=[True, True]).iloc[0]
        row["확정n"] = _norm_text(selected["공백시즌수"])
        row["근거구간"] = _norm_text(selected["공백시즌수"])
        row["근거사례수"] = int(selected["사례수"])
        row["근거복귀사례"] = int(selected["복귀사례"])
        row["근거복귀율(%)"] = round(float(selected["복귀율(%)"]), 2)
        row["근거문장"] = (
            f"공백 {row['근거구간']}시즌 이상 사례 {row['근거사례수']}건 중 복귀 {row['근거복귀사례']}건"
            f"({row['근거복귀율(%)']}%)으로 기준(복귀율 ≤ {RECORD_STOP_MAX_RETURN_RATE_PCT}%, 분모 ≥ {RECORD_STOP_MIN_CASES})을 충족해 "
            f"기록 중단 기준을 {row['확정n']}시즌으로 확정했습니다."
        )
        return pd.DataFrame([row], columns=RECORD_STOP_RULE_OUTPUT_COLS)

    denominator_ready = overall[
        overall["사례수"].notna() & (overall["사례수"] >= RECORD_STOP_MIN_CASES) & overall["복귀율(%)"].notna()
    ].copy()
    if denominator_ready.empty:
        row["근거문장"] = (
            f"모든 공백 구간에서 분모 {RECORD_STOP_MIN_CASES}건 이상을 확보하지 못해 기록 중단 기준 확정을 보류했습니다."
        )
    else:
        best = denominator_ready.sort_values(["복귀율(%)", "최소공백시즌수"], ascending=[True, True]).iloc[0]
        best_label = _norm_text(best["공백시즌수"])
        best_rate = round(float(best["복귀율(%)"]), 2)
        row["근거문장"] = (
            f"분모 기준(≥ {RECORD_STOP_MIN_CASES})을 만족한 구간 중 최저 복귀율은 공백 {best_label}시즌 {best_rate}%로, "
            f"복귀율 기준(≤ {RECORD_STOP_MAX_RETURN_RATE_PCT}%)을 충족하지 못해 기록 중단 기준 확정을 보류했습니다."
        )
    return pd.DataFrame([row], columns=RECORD_STOP_RULE_OUTPUT_COLS)


def build_participation_outputs(clean_df):
    season_month_histogram_df = build_season_month_histogram(clean_df)
    participation_df = build_participation_table(clean_df)
    season_activity_df, transition_summary_df = build_activity_and_transition_summary(participation_df)
    gap_episode_df = build_gap_return_episodes(participation_df)
    gap_return_rates_df = build_gap_return_rates(gap_episode_df)
    record_stop_rule_df = build_record_stop_rule(gap_return_rates_df)
    return (
        season_month_histogram_df,
        participation_df,
        season_activity_df,
        transition_summary_df,
        gap_return_rates_df,
        record_stop_rule_df,
    )


def print_season_boundary_evidence(season_month_histogram_df):
    known_meets = int(season_month_histogram_df.attrs.get("known_meets", 0))
    unknown_meets = int(season_month_histogram_df.attrs.get("unknown_meets", 0))
    start_bucket_meets = int(season_month_histogram_df.attrs.get("start_bucket_meets", 0))
    end_bucket_meets = int(season_month_histogram_df.attrs.get("end_bucket_meets", 0))
    print(f"시즌 경계 근거(월별 대회): 확인 가능 {known_meets}개 / 일자 미확보 {unknown_meets}개")
    if known_meets > 0:
        ratio = round((start_bucket_meets / known_meets) * 100.0, 2)
        print(
            f"시즌 시작 구간({SEASON_START_MONTH}~12월) {start_bucket_meets}개 vs 종료 구간(1~{SEASON_START_MONTH - 1}월) {end_bucket_meets}개 ({ratio}%)"
        )


def validate_anonymous_stats(distribution_df, participation_df):
    def assert_schema(df, expected_cols, filename):
        if list(df.columns) != expected_cols:
            raise ValueError(f"[error] {filename} 컬럼이 기대값과 다릅니다: {list(df.columns)}")
        forbidden = FORBIDDEN_OUTPUT_COLUMNS.intersection(df.columns)
        if forbidden:
            raise ValueError(f"[error] {filename}에 개인식별 금지 컬럼이 포함되었습니다: {', '.join(sorted(forbidden))}")

    def assert_k_rule(df, metric_cols, filename, count_col="인원수"):
        if df.empty:
            return
        for idx, row in df.iterrows():
            row_no = idx + 2
            count_value = row[count_col]
            if str(count_value).strip() == INSUFFICIENT_TEXT:
                invalid = [col for col in metric_cols if str(row[col]).strip() != INSUFFICIENT_TEXT]
                if invalid:
                    raise ValueError(f"[error] {filename} {row_no}행: {count_col}=데이터 부족인데 지표 컬럼이 노출되었습니다 ({', '.join(invalid)})")
                continue
            count_num = pd.to_numeric(pd.Series([count_value]), errors="coerce").iloc[0]
            if pd.isna(count_num) or int(count_num) < K_ANONYMITY_MIN:
                raise ValueError(f"[error] {filename} {row_no}행: k-익명 기준 미달 {count_col}가 공개되었습니다 ({count_value})")

    assert_schema(distribution_df, DIST_OUTPUT_COLS, "data/stats_distribution.csv")
    assert_schema(participation_df, PART_OUTPUT_COLS, "data/stats_participation.csv")
    assert_k_rule(distribution_df, DIST_TIME_COLS, "data/stats_distribution.csv", count_col="기록_인원수")
    assert_k_rule(distribution_df, DIST_RANK_COLS, "data/stats_distribution.csv", count_col="순위_인원수")
    assert_k_rule(participation_df, ["최초출전나이_p25", "최초출전나이_p50", "최초출전나이_p75", "초등부출전수_p50"], "data/stats_participation.csv")


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
        if not RECORDS_ANON_CSV.exists():
            print("[error] data/records.csv 또는 data/athlete_info.csv 파일이 없습니다.")
            print("[error] data/records_anon.csv도 없어 익명 통계를 재생성할 수 없습니다.")
            return
        (
            coverage_df,
            stats_distribution_df,
            stats_participation_df,
            class_level_map_df,
            class_level_year_category_df,
            class_level_agreement_df,
            class_level_mismatch_df,
            class_level_year_readiness_df,
            season_month_histogram_df,
            participation_df,
            season_activity_df,
            transition_summary_df,
            gap_return_rates_df,
            record_stop_rule_df,
        ) = build_stats_from_anon_records()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        coverage_df.to_csv(COVERAGE_CSV, index=False, encoding="utf-8-sig")
        stats_distribution_df.to_csv(STATS_DISTRIBUTION_CSV, index=False, encoding="utf-8-sig")
        stats_participation_df.to_csv(STATS_PARTICIPATION_CSV, index=False, encoding="utf-8-sig")
        season_month_histogram_df.to_csv(SEASON_MONTH_HISTOGRAM_CSV, index=False, encoding="utf-8-sig")
        participation_df.to_csv(PARTICIPATION_CSV, index=False, encoding="utf-8-sig")
        season_activity_df.to_csv(SEASON_ACTIVITY_COUNTS_CSV, index=False, encoding="utf-8-sig")
        transition_summary_df.to_csv(CLASS_TRANSITION_SUMMARY_CSV, index=False, encoding="utf-8-sig")
        gap_return_rates_df.to_csv(GAP_RETURN_RATES_CSV, index=False, encoding="utf-8-sig")
        record_stop_rule_df.to_csv(RECORD_STOP_RULE_CSV, index=False, encoding="utf-8-sig")
        class_level_map_df.to_csv(CLASS_LEVEL_MAP_CSV, index=False, encoding="utf-8-sig")
        class_level_year_category_df.to_csv(CLASS_LEVEL_YEAR_CATEGORY_COUNTS_CSV, index=False, encoding="utf-8-sig")
        class_level_agreement_df.to_csv(CLASS_LEVEL_AB_AGREEMENT_SUMMARY_CSV, index=False, encoding="utf-8-sig")
        class_level_mismatch_df.to_csv(CLASS_LEVEL_AB_MISMATCH_TYPES_CSV, index=False, encoding="utf-8-sig")
        class_level_year_readiness_df.to_csv(CLASS_LEVEL_YEAR_READINESS_CSV, index=False, encoding="utf-8-sig")
        print_stats_filter_log(stats_distribution_df)
        print_class_level_diagnostics(class_level_agreement_df, class_level_year_readiness_df, class_level_mismatch_df)
        print(f"데이터 커버리지 저장 완료: {COVERAGE_CSV}")
        print(f"익명 분포 통계 저장 완료: {STATS_DISTRIBUTION_CSV} ({len(stats_distribution_df)}행)")
        print(f"익명 참가 통계 저장 완료: {STATS_PARTICIPATION_CSV} ({len(stats_participation_df)}행)")
        print(f"시즌 월별 히스토그램 저장 완료: {SEASON_MONTH_HISTOGRAM_CSV} ({len(season_month_histogram_df)}행)")
        print(f"참가 이력 저장 완료: {PARTICIPATION_CSV} ({len(participation_df)}행)")
        print(f"시즌별 활동 선수수 저장 완료: {SEASON_ACTIVITY_COUNTS_CSV} ({len(season_activity_df)}행)")
        print(f"종목 전환 요약 저장 완료: {CLASS_TRANSITION_SUMMARY_CSV} ({len(transition_summary_df)}행)")
        print(f"공백 복귀율 저장 완료: {GAP_RETURN_RATES_CSV} ({len(gap_return_rates_df)}행)")
        print(f"기록 중단 기준 저장 완료: {RECORD_STOP_RULE_CSV} ({len(record_stop_rule_df)}행)")
        if not record_stop_rule_df.empty:
            print(record_stop_rule_df.iloc[0].get("근거문장", ""))
        print(f"종별 단계 매핑 저장 완료: {CLASS_LEVEL_MAP_CSV} ({len(class_level_map_df)}행)")
        print(f"연도×종별 집계 저장 완료: {CLASS_LEVEL_YEAR_CATEGORY_COUNTS_CSV} ({len(class_level_year_category_df)}행)")
        print(f"단계 A/B 요약 저장 완료: {CLASS_LEVEL_AB_AGREEMENT_SUMMARY_CSV}")
        print(f"단계 A/B 불일치 유형 저장 완료: {CLASS_LEVEL_AB_MISMATCH_TYPES_CSV} ({len(class_level_mismatch_df)}행)")
        print(f"연도별 단계 분석 사용성 저장 완료: {CLASS_LEVEL_YEAR_READINESS_CSV} ({len(class_level_year_readiness_df)}행)")
        print_season_boundary_evidence(season_month_histogram_df)
        print(
            "참가 이력 제외 행수: 출생연도 결측 {0}행 / 학년<=0 {1}행 / 시즌결측 {2}행".format(
                participation_df.attrs.get("excluded_birth_missing_rows", 0),
                participation_df.attrs.get("excluded_grade_non_positive_rows", 0),
                participation_df.attrs.get("excluded_missing_season_rows", 0),
            )
        )
        if participation_df.attrs.get("raw_key_rows", 0):
            print("[warn] participation.csv 익명키 중 12자리 hex 형식 미준수 행이 있습니다. 커밋 전 익명키 생성 경로를 확인하세요.")
        print(f"익명 통계 입력 소스: {RECORDS_ANON_CSV.name}")
        return
    records_df = pd.read_csv(RECORDS_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    athlete_df = pd.read_csv(ATHLETE_INFO_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    athlete_index_df, athlete_index_path = load_athlete_index_df()

    aff_counts = collect_affiliation_counts(records_df, athlete_index_df)
    school_aliases_df, school_ambiguous_df = build_school_aliases_and_ambiguous(aff_counts)
    profiles = build_id_profiles(records_df, athlete_df, athlete_index_df)
    record_index = build_record_index(records_df)
    id_merge_candidates_df, id_merges_auto_df = build_id_merge_tables(profiles, record_index)
    id_merges_existing_df = load_existing_id_merges()
    id_merges_df, id_merge_stats = merge_id_merges(id_merges_existing_df, id_merges_auto_df)
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
    stats_clean_df, stats_placements_df, stats_summary_df, stats_athlete_df, stats_source_label = select_stats_source(
        records_merged_df, athlete_merged_df, id_merge_map
    )
    participation_clean_df, participation_source_label = select_participation_source(records_merged_df, athlete_merged_df, id_merge_map)
    stats_distribution_df = build_stats_distribution(stats_clean_df, stats_athlete_df)
    stats_participation_df = build_stats_participation(stats_summary_df, stats_athlete_df)
    (
        season_month_histogram_df,
        participation_df,
        season_activity_df,
        transition_summary_df,
        gap_return_rates_df,
        record_stop_rule_df,
    ) = build_participation_outputs(participation_clean_df)
    validate_anonymous_stats(stats_distribution_df, stats_participation_df)
    class_level_map_df, class_level_year_category_df, class_level_agreement_df, class_level_mismatch_df, class_level_year_readiness_df = build_class_level_diagnostics(
        clean_df, id_merge_candidates_df
    )
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
    stats_distribution_df.to_csv(STATS_DISTRIBUTION_CSV, index=False, encoding="utf-8-sig")
    stats_participation_df.to_csv(STATS_PARTICIPATION_CSV, index=False, encoding="utf-8-sig")
    season_month_histogram_df.to_csv(SEASON_MONTH_HISTOGRAM_CSV, index=False, encoding="utf-8-sig")
    participation_df.to_csv(PARTICIPATION_CSV, index=False, encoding="utf-8-sig")
    season_activity_df.to_csv(SEASON_ACTIVITY_COUNTS_CSV, index=False, encoding="utf-8-sig")
    transition_summary_df.to_csv(CLASS_TRANSITION_SUMMARY_CSV, index=False, encoding="utf-8-sig")
    gap_return_rates_df.to_csv(GAP_RETURN_RATES_CSV, index=False, encoding="utf-8-sig")
    record_stop_rule_df.to_csv(RECORD_STOP_RULE_CSV, index=False, encoding="utf-8-sig")
    class_level_map_df.to_csv(CLASS_LEVEL_MAP_CSV, index=False, encoding="utf-8-sig")
    class_level_year_category_df.to_csv(CLASS_LEVEL_YEAR_CATEGORY_COUNTS_CSV, index=False, encoding="utf-8-sig")
    class_level_agreement_df.to_csv(CLASS_LEVEL_AB_AGREEMENT_SUMMARY_CSV, index=False, encoding="utf-8-sig")
    class_level_mismatch_df.to_csv(CLASS_LEVEL_AB_MISMATCH_TYPES_CSV, index=False, encoding="utf-8-sig")
    class_level_year_readiness_df.to_csv(CLASS_LEVEL_YEAR_READINESS_CSV, index=False, encoding="utf-8-sig")
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
    print("이상치 사유별 건수: 하한미달 {0}건 / 상한초과 {1}건 / 계측오류의심 {2}건 / 통계하한미달 {3}건".format(outlier_reason_counts["하한미달"], outlier_reason_counts["상한초과"], outlier_reason_counts["계측오류의심"], outlier_reason_counts["통계하한미달"]))
    print(f"이상치 {len(outliers_df)}건 검출 (data/outliers.csv)")
    review_count = 0 if id_merge_candidates_df.empty else int((id_merge_candidates_df["판정"] == "review").sum())
    auto_count = id_merge_stats["auto_count"]
    merge_total_count = id_merge_stats["total_count"]
    merge_added_count = id_merge_stats["added_auto"]
    merge_conflict_skipped = id_merge_stats["conflict_skipped"]
    print(f"학교 표기 목록 저장 완료: {SCHOOL_RAW_LIST_TXT}")
    if athlete_index_path is None:
        print(f"선수 인덱스 입력: 미사용 (환경변수 {ATHLETE_INDEX_ENV} 또는 {ATHLETE_INDEX_CSV} 파일 없음)")
    else:
        print(f"선수 인덱스 입력: {athlete_index_path}")
    print(f"학교 정규화 사전 저장 완료: {SCHOOL_ALIASES_CSV} ({len(school_aliases_df)}행)")
    print(f"지역 접두 모호 케이스 저장 완료: {SCHOOL_AMBIGUOUS_CSV} ({len(school_ambiguous_df)}행)")
    print(f"id 병합 후보 저장 완료: {ID_MERGE_CANDIDATES_CSV} ({len(id_merge_candidates_df)}행)")
    print(f"id 확정 병합 저장 완료: {ID_MERGES_CSV} (기존 {id_merge_stats['existing_count']}건 + 자동후보 {auto_count}건, 신규반영 {merge_added_count}건, 총 {merge_total_count}건)")
    if merge_conflict_skipped:
        print(f"id 병합 충돌로 자동후보 미반영: {merge_conflict_skipped}건 (기존 확정값 유지)")
    print(f"id 병합 review 건수: {review_count}건")
    print(f"익명 분포 통계 저장 완료: {STATS_DISTRIBUTION_CSV} ({len(stats_distribution_df)}행)")
    print(f"익명 참가 통계 저장 완료: {STATS_PARTICIPATION_CSV} ({len(stats_participation_df)}행)")
    print(f"시즌 월별 히스토그램 저장 완료: {SEASON_MONTH_HISTOGRAM_CSV} ({len(season_month_histogram_df)}행)")
    print(f"참가 이력 저장 완료: {PARTICIPATION_CSV} ({len(participation_df)}행)")
    print(f"시즌별 활동 선수수 저장 완료: {SEASON_ACTIVITY_COUNTS_CSV} ({len(season_activity_df)}행)")
    print(f"종목 전환 요약 저장 완료: {CLASS_TRANSITION_SUMMARY_CSV} ({len(transition_summary_df)}행)")
    print(f"공백 복귀율 저장 완료: {GAP_RETURN_RATES_CSV} ({len(gap_return_rates_df)}행)")
    print(f"기록 중단 기준 저장 완료: {RECORD_STOP_RULE_CSV} ({len(record_stop_rule_df)}행)")
    if not record_stop_rule_df.empty:
        print(record_stop_rule_df.iloc[0].get("근거문장", ""))
    print(f"종별 단계 매핑 저장 완료: {CLASS_LEVEL_MAP_CSV} ({len(class_level_map_df)}행)")
    print(f"연도×종별 집계 저장 완료: {CLASS_LEVEL_YEAR_CATEGORY_COUNTS_CSV} ({len(class_level_year_category_df)}행)")
    print(f"단계 A/B 요약 저장 완료: {CLASS_LEVEL_AB_AGREEMENT_SUMMARY_CSV}")
    print(f"단계 A/B 불일치 유형 저장 완료: {CLASS_LEVEL_AB_MISMATCH_TYPES_CSV} ({len(class_level_mismatch_df)}행)")
    print(f"연도별 단계 분석 사용성 저장 완료: {CLASS_LEVEL_YEAR_READINESS_CSV} ({len(class_level_year_readiness_df)}행)")
    print(f"익명 통계 입력 소스: {stats_source_label}")
    print(f"참가 이력 입력 소스: {participation_source_label}")
    print_season_boundary_evidence(season_month_histogram_df)
    print(
        "참가 이력 제외 행수: 출생연도 결측 {0}행 / 학년<=0 {1}행 / 시즌결측 {2}행".format(
            participation_df.attrs.get("excluded_birth_missing_rows", 0),
            participation_df.attrs.get("excluded_grade_non_positive_rows", 0),
            participation_df.attrs.get("excluded_missing_season_rows", 0),
        )
    )
    if participation_df.attrs.get("raw_key_rows", 0):
        print("[warn] participation.csv 익명키 중 12자리 hex 형식 미준수 행이 있습니다. 커밋 전 익명키 생성 경로를 확인하세요.")
    print_stats_filter_log(stats_distribution_df)
    print_class_level_diagnostics(class_level_agreement_df, class_level_year_readiness_df, class_level_mismatch_df)


if __name__ == "__main__":
    main()
