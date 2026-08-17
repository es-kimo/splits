import json
import hashlib
import os
import re
from datetime import date
from pathlib import Path

import pandas as pd
from analyze import (
    SHORTTRACK_CLASS_CD,
    best_placement,
    build_clean_records,
    classify_class_cd,
)
from local_env import load_local_env

DATA_DIR = Path("data")
SITE_DATA_DIR = Path("site/data")
RECORDS_ANON_CSV = DATA_DIR / "records_anon.csv"
ATHLETES_JSON = SITE_DATA_DIR / "athletes.json"
MEETS_JSON = SITE_DATA_DIR / "meets.json"
DISTRIBUTION_JSON = SITE_DATA_DIR / "distribution.json"
META_JSON = SITE_DATA_DIR / "meta.json"
ANON_SALT_ENV = "SPLITS_ANON_SALT"
ANON_KEY_ALGORITHM = "sha256"
ANON_KEY_HEX_LENGTH = 12
ANON_KEY_SOURCE_FIELD = "idNo"
ANON_KEY_EXCLUDED_FIELDS = ("이름", "출생연도", "소속", "성별", "시도", "BIB", "레인")
MEET_INDEX_CSV_ENV = "SPLITS_MEET_INDEX_CSV"
DEFAULT_SHARED_MEET_INDEX_CSV = Path("/Users/kihyun/orgs/personal/splits/data/meet_index_inf201.csv")
INPUT_FILES = [
    "placements.csv",
    "youth_summary.csv",
    "age_matrix.csv",
    "athlete_info.csv",
    "coverage.csv",
    "public_figures.csv",
    "stats_distribution.csv",
]
MEET_SOURCE_RECORD_CANDIDATES = [
    ("records_full.csv", "athlete_info_full.csv"),
    ("records.csv", "athlete_info.csv"),
]
AGES = [str(age) for age in range(7, 19)]
PUBLIC_FIGURES_REQUIRED_COLUMNS = ["idNo", "이름", "슬러그", "출생연도", "지정근거", "언론보도URL", "지정일자", "상태"]
PUBLIC_FIGURES_ALLOWED_STATUS = {"active", "removed"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
K_ANONYMITY_MIN = 10
INSUFFICIENT_TEXT = "데이터 부족"
TIME_METRIC_MAP = [
    ("기록_p05", "timeP05", 3),
    ("기록_p10", "timeP10", 3),
    ("기록_p20", "timeP20", 3),
    ("기록_p30", "timeP30", 3),
    ("기록_p40", "timeP40", 3),
    ("기록_p50", "timeP50", 3),
    ("기록_p60", "timeP60", 3),
    ("기록_p70", "timeP70", 3),
    ("기록_p80", "timeP80", 3),
    ("기록_p90", "timeP90", 3),
    ("기록_p95", "timeP95", 3),
]
RANK_METRIC_MAP = [
    ("순위_p25", "rankP25", 2),
    ("순위_p50", "rankP50", 2),
    ("순위_p75", "rankP75", 2),
]
STATS_DISTRIBUTION_REQUIRED_COLUMNS = (
    ["출생연도", "성별", "거리", "기록_인원수"]
    + [source for source, _target, _digits in TIME_METRIC_MAP]
    + ["순위_인원수"]
    + [source for source, _target, _digits in RANK_METRIC_MAP]
)
DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ROUND_NUMBER_RE = re.compile(r"제\s*(\d+)\s*회")
PHASE_NUMBER_RE = re.compile(r"(\d+)\s*차")
MEET_SLUG_SEED_MAX_BYTES = 48
MEET_SLUG_HASH_LEN = 8
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
RECORDS_ANON_FORBIDDEN_COLUMNS = {"idNo", "이름", "소속", "시도", "BIB", "레인"}
GRADE_RE = re.compile(r"([1-6](?:\s*,\s*[1-6])?)\s*학년")
YEAR_RE = re.compile(r"(19|20)\d{2}")
MEET_MATCH_TEXT_RE = re.compile(r"[^0-9a-z가-힣]+")


def as_text(value):
    # CSV 경유 입력은 fillna("")로 결측이 지워지지만, analyze.py에서 직접 넘어온 프레임은
    # pd.NA/NaN이 살아 있다. `value or ""` 형태는 pd.NA에서 TypeError가 나므로 여기서 흡수한다.
    if value is None:
        return ""
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value).strip()


def as_int(value):
    text = as_text(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def as_float(value):
    text = as_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def as_id(value):
    return as_text(value)


def as_bool(value):
    return as_text(value).lower() in {"true", "1", "y", "yes", "t"}


def rank_band_text(rank):
    if rank is None:
        return "-"
    if rank < 10:
        return "한 자리수"
    return f"{(rank // 10) * 10}등대"


def read_csv(name):
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {path}")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def read_csv_path(path):
    if not path.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {path}")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _norm_text(value):
    return str(value or "").strip()


def _as_iso_date(value):
    text = _norm_text(value)
    return text if DATE_ISO_RE.fullmatch(text) else None


def _pick_location(group):
    for column in ["개최장소", "개최지", "장소"]:
        if column not in group.columns:
            continue
        for value in group[column].tolist():
            text = _norm_text(value)
            if text:
                return text
    return None


def _normalize_slug_text(value):
    text = _norm_text(value).lower()
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "meet"


def _remove_year_prefix_from_slug(value, year):
    text = value
    patterns = [
        rf"^{year}(?:-\d{{2}})?-",
        rf"^{year}(?:/{str(year + 1)[-2:]})?(?:시즌)?-",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text)
    return text.strip("-") or value


def _trim_slug_to_max_bytes(value, max_bytes):
    text = re.sub(r"-{2,}", "-", _norm_text(value)).strip("-")
    if not text:
        return ""
    chunks = []
    size = 0
    for ch in text:
        encoded = ch.encode("utf-8")
        if size + len(encoded) > max_bytes:
            break
        chunks.append(ch)
        size += len(encoded)
    return re.sub(r"-{2,}", "-", "".join(chunks)).strip("-")


def _meet_slug_hash(year, meet_name):
    seed = f"{year}:{_norm_text(meet_name)}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:MEET_SLUG_HASH_LEN]


def _build_meet_slug(year, meet_name, slug_seed):
    # 파일시스템(예: ext4)의 파일명 길이 제한을 넘지 않도록 seed를 UTF-8 바이트 단위로 제한한다.
    compact_seed = _trim_slug_to_max_bytes(slug_seed, MEET_SLUG_SEED_MAX_BYTES)
    hashed = _meet_slug_hash(year, meet_name)
    if compact_seed:
        return f"{year}-{compact_seed}-{hashed}"
    return f"{year}-meet-{hashed}"


def _extract_series_key(meet_name):
    text = _norm_text(meet_name).lower()
    text = re.sub(r"\d{4}\s*/\s*\d{2}\s*시즌", " ", text)
    text = re.sub(r"\d{4}\s*시즌", " ", text)
    text = re.sub(r"\b(19|20)\d{2}\b", " ", text)
    text = re.sub(r"제\s*\d+\s*회", " 제회 ", text)
    text = re.sub(r"\d+\s*차", " 차 ", text)
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text or _normalize_slug_text(meet_name)


def _extract_series_label(meet_name):
    text = _norm_text(meet_name)
    text = re.sub(r"^\d{4}\s*/\s*\d{2}\s*시즌\s*", "", text)
    text = re.sub(r"^\d{4}\s*시즌\s*", "", text)
    text = re.sub(r"^\d{4}\s*", "", text)
    text = re.sub(r"제\s*\d+\s*회\s*", "", text)
    text = re.sub(r"\d+\s*차\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text or _norm_text(meet_name) or "-"


def _extract_round_order(meet_name):
    text = _norm_text(meet_name)
    round_match = ROUND_NUMBER_RE.search(text)
    if round_match:
        return int(round_match.group(1))
    phase_match = PHASE_NUMBER_RE.search(text)
    if phase_match:
        return int(phase_match.group(1))
    return None


def _load_meet_source():
    missing = []
    for record_name, athlete_name in MEET_SOURCE_RECORD_CANDIDATES:
        record_path = DATA_DIR / record_name
        athlete_path = DATA_DIR / athlete_name
        if not record_path.exists() or not athlete_path.exists():
            missing.append((record_path, athlete_path))
            continue
        records = read_csv_path(record_path)
        athlete_info = read_csv_path(athlete_path)
        clean_records = build_clean_records(records, athlete_info)
        placements = best_placement(clean_records)
        placements["idNo"] = placements["idNo"].map(as_id)
        placements["대회연도_num"] = placements["대회연도"].map(as_int)
        placements["거리_num"] = placements["거리"].map(as_int)
        placements["sf_bool"] = placements["SF여부"].map(as_bool)
        return clean_records, placements
    missing_text = ", ".join([f"{record_path.name}+{athlete_path.name}" for record_path, athlete_path in missing])
    raise FileNotFoundError(f"[error] 대회 집계용 기록 파일이 없습니다: {missing_text}")


def anon_key_spec():
    return {
        "algorithm": ANON_KEY_ALGORITHM,
        "source_field": ANON_KEY_SOURCE_FIELD,
        "salt_env": ANON_SALT_ENV,
        "hex_length": ANON_KEY_HEX_LENGTH,
        "formula": f"{ANON_KEY_ALGORITHM}({ANON_KEY_SOURCE_FIELD} + SALT)[:{ANON_KEY_HEX_LENGTH}]",
        "excluded_fields": list(ANON_KEY_EXCLUDED_FIELDS),
    }


def _build_anon_key(id_no, salt):
    source = as_id(id_no)
    if not source:
        return ""
    return hashlib.sha256(f"{source}{salt}".encode("utf-8")).hexdigest()[:ANON_KEY_HEX_LENGTH]


def build_anon_key(id_no, salt):
    return _build_anon_key(id_no, salt)


def _extract_grade_text(category_text):
    text = as_text(category_text).replace(" ", "")
    if not text:
        return ""
    match = GRADE_RE.search(text)
    if not match:
        return ""
    return match.group(1).replace(" ", "")


def _format_float_text(value, digits=3):
    num = as_float(value)
    if num is None:
        return ""
    return f"{round(num, digits):.{digits}f}"


def _extract_years_from_text(*values):
    years = set()
    for value in values:
        text = as_text(value)
        for match in YEAR_RE.finditer(text):
            year = int(match.group(0))
            if 1900 <= year <= 2099:
                years.add(year)
    return years


def _normalize_meet_match_text(value):
    text = as_text(value).lower()
    return MEET_MATCH_TEXT_RE.sub("", text)


def _load_meet_index_entries():
    candidate_paths = []
    env_path = as_text(os.environ.get(MEET_INDEX_CSV_ENV))
    if env_path:
        candidate_paths.append(Path(env_path).expanduser())
    candidate_paths.append(DATA_DIR / "meet_index_inf201.csv")
    candidate_paths.append(DEFAULT_SHARED_MEET_INDEX_CSV)

    seen = set()
    selected = None
    for path in candidate_paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            selected = path
            break
    if selected is None:
        return [], None

    frame = read_csv_path(selected)
    required_columns = ["classCd", "toCd", "대회명"]
    missing = [name for name in required_columns if name not in frame.columns]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"[error] {selected} 필수 컬럼이 없습니다: {missing_text}")

    rows = []
    dedup = set()
    for _, row in frame.iterrows():
        to_cd = as_text(row.get("toCd"))
        event_name = as_text(row.get("대회명"))
        if not to_cd or not event_name:
            continue
        class_cd = as_text(row.get("classCd"))
        search_app_yn = as_text(row.get("searchAppYn"))
        period = as_text(row.get("기간"))
        norm_name = _normalize_meet_match_text(event_name)
        if not norm_name:
            continue
        row_key = (class_cd, to_cd, search_app_yn, event_name, period)
        if row_key in dedup:
            continue
        dedup.add(row_key)
        rows.append(
            {
                "classCd": class_cd,
                "toCd": to_cd,
                "searchAppYn": search_app_yn,
                "대회명": event_name,
                "기간": period,
                "normName": norm_name,
                "years": _extract_years_from_text(event_name, period),
            }
        )
    return rows, selected


def _match_to_cd_for_meet(meet_year, meet_name, entries, preferred_class_cds=None):
    norm_target = _normalize_meet_match_text(meet_name)
    if meet_year is None or not norm_target or not entries:
        return "", "missing-key"

    def score_name(candidate_norm):
        if norm_target == candidate_norm:
            return 3
        if norm_target in candidate_norm or candidate_norm in norm_target:
            if min(len(norm_target), len(candidate_norm)) >= 8:
                return 2
        return 0

    year_filtered = [item for item in entries if not item["years"] or meet_year in item["years"]]
    search_pool = year_filtered if year_filtered else entries
    scored = []
    for item in search_pool:
        score = score_name(item["normName"])
        if score > 0:
            scored.append((score, item))
    if not scored:
        return "", "name-not-matched"

    max_score = max(score for score, _item in scored)
    top = [item for score, item in scored if score == max_score]
    unique_to_cd = sorted({item["toCd"] for item in top if item["toCd"]})
    if len(unique_to_cd) == 1:
        return unique_to_cd[0], "matched"
    preferred_classes = {as_text(value) for value in (preferred_class_cds or set()) if as_text(value)}
    if preferred_classes:
        preferred_top = [item for item in top if as_text(item.get("classCd")) in preferred_classes]
        preferred_to_cd = sorted({item["toCd"] for item in preferred_top if item["toCd"]})
        if len(preferred_to_cd) == 1:
            return preferred_to_cd[0], "matched"
    return "", "ambiguous"


def _build_meet_to_cd_map(clean_records):
    entries, source_path = _load_meet_index_entries()
    if not entries:
        return {}, {"source_path": None, "total": 0, "matched": 0, "unmatched": 0, "ambiguous": 0}

    base = clean_records.copy()
    base["대회연도_num"] = pd.to_numeric(base.get("대회연도"), errors="coerce").astype("Int64")
    base["대회명_text"] = base.get("대회명", "").map(as_text)
    base["classCd_text"] = base.get("classCd", "").map(as_text)
    meet_keys = base[["대회연도_num", "대회명_text"]].drop_duplicates()
    class_preferences = {}
    grouped_classes = base.groupby(["대회연도_num", "대회명_text"], dropna=False)["classCd_text"]
    for (year_value, meet_name), values in grouped_classes:
        if pd.isna(year_value) or not meet_name:
            continue
        class_preferences[(int(year_value), meet_name)] = {value for value in values.tolist() if value}

    mapping = {}
    matched = 0
    unmatched = 0
    ambiguous = 0
    for _, item in meet_keys.iterrows():
        year_value = item.get("대회연도_num")
        meet_name = item.get("대회명_text")
        if pd.isna(year_value) or not meet_name:
            continue
        year_int = int(year_value)
        class_pref = class_preferences.get((year_int, meet_name), set())
        to_cd, reason = _match_to_cd_for_meet(year_int, meet_name, entries, preferred_class_cds=class_pref)
        mapping[(year_int, meet_name)] = to_cd
        if reason == "matched":
            matched += 1
        elif reason == "ambiguous":
            ambiguous += 1
            unmatched += 1
        else:
            unmatched += 1

    stats = {
        "source_path": str(source_path),
        "total": int(len(mapping)),
        "matched": int(matched),
        "unmatched": int(unmatched),
        "ambiguous": int(ambiguous),
    }
    return mapping, stats


def build_records_anon(clean_records, salt):
    salt_text = as_text(salt)
    if not salt_text:
        raise ValueError(f"[error] 익명키 생성을 위한 환경변수 {ANON_SALT_ENV} 값이 필요합니다.")
    if clean_records.empty:
        return pd.DataFrame(columns=RECORDS_ANON_REQUIRED_COLUMNS)

    base = clean_records.copy()
    base["idNo_text"] = base["idNo"].map(as_id)
    base["대회연도_num"] = pd.to_numeric(base.get("대회연도"), errors="coerce").astype("Int64")
    base["거리_num"] = pd.to_numeric(base.get("거리"), errors="coerce").astype("Int64")
    base["SF여부_bool"] = base.get("SF여부", "").map(as_bool)
    base["순위_num"] = pd.to_numeric(base.get("순위_정수"), errors="coerce").astype("Int64")
    base["익명키"] = base["idNo_text"].map(lambda value: _build_anon_key(value, salt_text))
    meet_to_cd_map, to_cd_stats = _build_meet_to_cd_map(base)
    direct_to_cd_rows = 0
    mapped_to_cd_rows = 0
    unresolved_to_cd_rows = 0

    rows = []
    for _, row in base.iterrows():
        year_num = row.get("대회연도_num")
        dist_num = row.get("거리_num")
        rank_num = row.get("순위_num")
        meet_name = as_text(row.get("대회명"))
        date_text = as_text(row.get("일자_정규화")) or as_text(row.get("일자"))
        to_cd = ""
        row_to_cd = as_text(row.get("toCd"))
        if row_to_cd:
            to_cd = row_to_cd
            direct_to_cd_rows += 1
        elif pd.notna(year_num) and meet_name:
            to_cd = meet_to_cd_map.get((int(year_num), meet_name), "")
            if to_cd:
                mapped_to_cd_rows += 1
            else:
                unresolved_to_cd_rows += 1
        else:
            unresolved_to_cd_rows += 1
        rows.append(
            {
                "toCd": to_cd,
                "classCd": as_text(row.get("classCd")) or classify_class_cd(meet_name, row.get("라운드"), row.get("라운드종류")),
                "대회명": meet_name,
                "대회연도": str(int(year_num)) if pd.notna(year_num) else "",
                "일자": date_text,
                "종별": as_text(row.get("종별")),
                "학령구간": as_text(row.get("학령구간")),
                "거리": str(int(dist_num)) if pd.notna(dist_num) else "",
                "SF여부": "Y" if bool(row.get("SF여부_bool")) else "N",
                "라운드": as_text(row.get("라운드")),
                "라운드종류": as_text(row.get("라운드종류")),
                "순위": str(int(rank_num)) if pd.notna(rank_num) else "",
                "기록_초": _format_float_text(row.get("기록_초"), digits=3),
                "사유": "",
                "성별": as_text(row.get("성별")),
                "출생연도": str(as_int(row.get("출생년도")) or ""),
                "학년": _extract_grade_text(row.get("종별")),
                "익명키": as_text(row.get("익명키")),
            }
        )

    out = pd.DataFrame(rows, columns=RECORDS_ANON_REQUIRED_COLUMNS)
    if out.empty:
        return out
    out = out.sort_values(["대회연도", "대회명", "일자", "거리", "라운드", "익명키"], na_position="last").reset_index(drop=True)
    to_cd_stats.update(
        {
            "rows_total": int(len(out)),
            "rows_direct": int(direct_to_cd_rows),
            "rows_mapped": int(mapped_to_cd_rows),
            "rows_unresolved": int(unresolved_to_cd_rows),
        }
    )
    out.attrs["to_cd_stats"] = to_cd_stats
    return out


def validate_records_anon(frame):
    columns = list(frame.columns)
    if columns != RECORDS_ANON_REQUIRED_COLUMNS:
        raise ValueError(f"[error] data/records_anon.csv 컬럼이 기대값과 다릅니다: {columns}")
    forbidden = RECORDS_ANON_FORBIDDEN_COLUMNS.intersection(columns)
    if forbidden:
        raise ValueError(f"[error] data/records_anon.csv에 금지 컬럼이 포함되었습니다: {', '.join(sorted(forbidden))}")
    if frame.empty:
        return
    key_series = frame["익명키"].astype(str).str.strip()
    invalid = frame[~key_series.str.fullmatch(r"[0-9a-f]{12}")]
    if not invalid.empty:
        first_row_no = int(invalid.index[0]) + 2
        raise ValueError(f"[error] data/records_anon.csv {first_row_no}행 익명키 형식이 올바르지 않습니다.")
    class_series = frame["classCd"].astype(str).str.strip()
    invalid_class = frame[~class_series.isin({"1", "2", "3"})]
    if not invalid_class.empty:
        first_row_no = int(invalid_class.index[0]) + 2
        raise ValueError(f"[error] data/records_anon.csv {first_row_no}행 classCd 값이 올바르지 않습니다.")


def parse_public_figures(frame):
    missing_columns = [column for column in PUBLIC_FIGURES_REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise ValueError(f"[error] data/public_figures.csv 필수 컬럼이 없습니다: {missing_text}")

    rows = []
    seen_ids = set()
    seen_slugs = set()
    for idx, row in frame.iterrows():
        row_no = idx + 2
        id_no = as_id(row.get("idNo", ""))
        name = str(row.get("이름", "")).strip()
        slug = str(row.get("슬러그", "")).strip().lower()
        birth = as_int(row.get("출생연도", ""))
        reason = str(row.get("지정근거", "")).strip()
        media_url = str(row.get("언론보도URL", "")).strip()
        designated_at = str(row.get("지정일자", "")).strip()
        status = str(row.get("상태", "")).strip().lower()

        if not id_no:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 idNo 값이 비어 있습니다.")
        if not name:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 이름 값이 비어 있습니다.")
        if not slug:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 슬러그 값이 비어 있습니다.")
        if not SLUG_RE.fullmatch(slug):
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 슬러그 형식이 올바르지 않습니다: {slug}")
        if birth is None:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 출생연도 값이 올바르지 않습니다.")
        if not reason:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 지정근거 값이 비어 있습니다.")
        if not media_url or not media_url.startswith(("http://", "https://")):
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 언론보도URL 값이 올바르지 않습니다.")
        if not designated_at:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 지정일자 값이 비어 있습니다.")
        if status not in PUBLIC_FIGURES_ALLOWED_STATUS:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 상태 값이 올바르지 않습니다: {status}")
        if id_no in seen_ids:
            raise ValueError(f"[error] data/public_figures.csv idNo 중복이 있습니다: {id_no}")
        if slug in seen_slugs:
            raise ValueError(f"[error] data/public_figures.csv 슬러그 중복이 있습니다: {slug}")

        seen_ids.add(id_no)
        seen_slugs.add(slug)
        rows.append(
            {
                "idNo": id_no,
                "name": name,
                "slug": slug,
                "birth": birth,
                "designationReason": reason,
                "mediaReportUrl": media_url,
                "designatedAt": designated_at,
                "status": status,
            }
        )

    if not rows:
        raise ValueError("[error] data/public_figures.csv에 명단 행이 없습니다.")
    return rows


def build_athletes_payload(frames):
    placements = frames["placements.csv"]
    summary = frames["youth_summary.csv"]
    matrix = frames["age_matrix.csv"]
    athlete_info = frames["athlete_info.csv"]
    coverage = frames["coverage.csv"]
    public_figures = parse_public_figures(frames["public_figures.csv"])
    active_figures = [item for item in public_figures if item["status"] == "active"]
    if not active_figures:
        raise ValueError("[error] data/public_figures.csv에 active 상태 선수가 없습니다.")
    active_ids = [item["idNo"] for item in active_figures]
    active_id_set = set(active_ids)
    public_by_id = {item["idNo"]: item for item in public_figures}

    required_id_frames = {
        "placements.csv": placements,
        "youth_summary.csv": summary,
        "age_matrix.csv": matrix,
        "athlete_info.csv": athlete_info,
    }
    for frame_name, frame in required_id_frames.items():
        if "idNo" not in frame.columns:
            raise ValueError(f"[error] idNo 컬럼이 없습니다: data/{frame_name}")
        frame["idNo"] = frame["idNo"].map(as_id)

    placements["순위_num"] = placements["순위"].map(as_int)
    placements["대회연도_num"] = placements["대회연도"].map(as_int)
    placements["나이_추정_num"] = placements["나이_추정"].map(as_int)
    placements["거리_num"] = placements["거리"].map(as_int)
    placements["sf_bool"] = placements["SF여부"].map(as_bool)
    placements_target = placements[placements["idNo"].isin(active_id_set)].copy()

    elem = placements_target[(placements_target["학령구간"] == "초등") & placements_target["순위_num"].notna()].copy()
    elem_median = elem.groupby("idNo")["순위_num"].median().to_dict()

    info_by_id = {}
    for id_no, group in athlete_info.groupby("idNo", sort=False):
        if not id_no:
            continue
        names = [v.strip() for v in group.get("이름", pd.Series(dtype=str)).tolist() if str(v).strip()]
        teams = [v.strip() for v in group.get("소속팀", pd.Series(dtype=str)).tolist() if str(v).strip()]
        genders = [v.strip() for v in group.get("성별", pd.Series(dtype=str)).tolist() if str(v).strip()]
        births = [as_int(v) for v in group.get("출생년도", pd.Series(dtype=str)).tolist() if as_int(v) is not None]
        info_by_id[id_no] = {
            "name": names[0] if names else id_no,
            "birth": births[0] if births else None,
            "team": teams[0] if teams else "-",
            "gender": genders[0] if genders else None,
        }

    summary_by_id = {}
    for _, row in summary.iterrows():
        id_no = as_id(row.get("idNo", ""))
        name = str(row.get("이름", "")).strip()
        if not id_no:
            continue
        summary_by_id[id_no] = {
            "name": name,
            "first": as_int(row.get("최초_출전나이")),
            "elemBest": as_int(row.get("초등부_최고순위")),
            "elemWorst": as_int(row.get("초등부_최저순위")),
            "elemCount": as_int(row.get("초등부_출전수")) or 0,
        }

    matrix_by_id = {}
    for _, row in matrix.iterrows():
        id_no = as_id(row.get("idNo", ""))
        name = str(row.get("이름", "")).strip()
        if not id_no:
            continue
        matrix_by_id[id_no] = {"name": name, "ages": {age: as_int(row.get(age, "")) for age in AGES}}

    history_by_id = {}
    for _, row in placements_target.iterrows():
        id_no = as_id(row.get("idNo", ""))
        rank = as_int(row.get("순위"))
        if not id_no or rank is None:
            continue
        history_by_id.setdefault(id_no, []).append(
            {
                "year": as_int(row.get("대회연도")),
                "age": as_int(row.get("나이_추정")),
                "meet": str(row.get("대회명", "")).strip() or "-",
                "distance": as_int(row.get("거리")),
                "sf": as_bool(row.get("SF여부", "")),
                "rank": rank,
                "round": str(row.get("결승구분", "")).strip() or str(row.get("라운드종류", "")).strip() or "-",
            }
        )

    athletes = []
    for id_no in active_ids:
        public = public_by_id[id_no]
        s = summary_by_id.get(id_no, {})
        info = info_by_id.get(id_no, {"name": id_no, "birth": None, "team": "-", "gender": None})
        m = matrix_by_id.get(id_no, {})
        has_profile = id_no in info_by_id or id_no in summary_by_id or id_no in matrix_by_id
        history = history_by_id.get(id_no, [])
        if not has_profile and not history:
            raise ValueError(f"[error] data/public_figures.csv의 idNo가 분석 데이터에 없습니다: {id_no}")

        name = public["name"] or info.get("name") or s.get("name") or m.get("name") or id_no
        birth = public["birth"] if public.get("birth") is not None else info.get("birth")
        median = elem_median.get(id_no)
        median_value = float(median) if median is not None else None
        history = sorted(history, key=lambda x: (x.get("year") is None, -(x.get("year") or 0), x.get("meet", ""), x.get("distance") or 0, x.get("rank") or 9999))
        athletes.append(
            {
                "idNo": id_no,
                "slug": public["slug"],
                "url": f"athlete/{public['slug']}/",
                "name": name,
                "birth": birth,
                "team": info["team"],
                "gender": info["gender"],
                "designationReason": public["designationReason"],
                "mediaReportUrl": public["mediaReportUrl"],
                "designatedAt": public["designatedAt"],
                "status": public["status"],
                "first": s.get("first"),
                "ages": m.get("ages", {age: None for age in AGES}),
                "elem": {
                    "best": s.get("elemBest"),
                    "median": median_value,
                    "worst": s.get("elemWorst"),
                    "count": s.get("elemCount", 0),
                },
                "history": history,
            }
        )

    years = [y for y in placements_target["대회연도_num"].tolist() if y is not None]
    if not years:
        years = [as_int(v) for v in coverage.get("대회연도", pd.Series(dtype=str)).tolist()]
        years = [y for y in years if y is not None]
    year_start, year_end = (min(years), max(years)) if years else (None, None)

    all_ages = [a for a in placements_target["나이_추정_num"].tolist() if isinstance(a, int)]
    ages_for_span = [a for a in all_ages if a <= 25] or all_ages
    age_min = min(ages_for_span) if ages_for_span else None
    age_max = max(ages_for_span) if ages_for_span else None

    elem_with_data = [a for a in athletes if (a["elem"].get("count") or 0) > 0]
    elem_top2_count = sum(1 for a in elem_with_data if (a["elem"].get("best") or 9999) <= 2)
    elem_worst_max = max((a["elem"].get("worst") or 0) for a in elem_with_data) if elem_with_data else None

    first_ages = [a.get("first") for a in athletes if a.get("first") is not None]
    first_age_min = min(first_ages) if first_ages else None
    first_age_max = max(first_ages) if first_ages else None

    missing_elem_names = [a["name"] for a in athletes if (a["elem"].get("count") or 0) == 0]
    payload = {
        "meta": {
            "athleteCount": len(athletes),
            "placementCount": int(len(placements_target)),
            "yearStart": year_start,
            "yearEnd": year_end,
            "yearSpan": (year_end - year_start) if year_start is not None and year_end is not None else None,
            "ageMin": age_min,
            "ageMax": age_max,
            "elemTop2Count": elem_top2_count,
            "elemWorstBand": rank_band_text(elem_worst_max),
            "firstAgeMin": first_age_min,
            "firstAgeMax": first_age_max,
            "missingElemNames": missing_elem_names,
        },
        "ages": [int(age) for age in AGES],
        "athletes": athletes,
    }
    return payload, placements_target, public_figures, active_id_set


def _group_placements_by_meet(frame):
    if frame.empty:
        return {}
    base = frame.copy()
    base["idNo"] = base["idNo"].map(as_id)
    base["대회연도_num"] = base["대회연도"].map(as_int)
    base["대회명_text"] = base["대회명"].astype(str).str.strip().replace("", "-")
    base["거리_num"] = base["거리"].map(as_int)
    base["sf_bool"] = base["SF여부"].map(as_bool)
    base = base[base["대회연도_num"].notna()].copy()
    if base.empty:
        return {}
    return {(int(year), meet): group.copy() for (year, meet), group in base.groupby(["대회연도_num", "대회명_text"], dropna=False, sort=False)}


def build_meets(clean_records, placements_all, placements_target, active_public_by_id):
    if clean_records.empty:
        return {"items": []}

    base = clean_records.copy()
    base["idNo"] = base["idNo"].map(as_id)
    base["대회명_text"] = base["대회명"].astype(str).str.strip().replace("", "-")
    base["대회연도_num"] = pd.to_numeric(base["대회연도"], errors="coerce").astype("Int64")
    base["거리_num"] = pd.to_numeric(base["거리"], errors="coerce").astype("Int64")
    base["기록_초_num"] = pd.to_numeric(base["기록_초"], errors="coerce")
    base["라운드종류_text"] = base["라운드종류"].astype(str).str.strip() if "라운드종류" in base.columns else ""
    base["일자_정규화_text"] = base["일자_정규화"].astype(str).str.strip() if "일자_정규화" in base.columns else ""
    base["일자_text"] = base["일자"].astype(str).str.strip() if "일자" in base.columns else ""
    base["종별_text"] = base["종별"].astype(str).str.strip() if "종별" in base.columns else ""
    base = base[(base["대회연도_num"].notna()) & (base["대회명_text"] != "-")].copy()
    if base.empty:
        return {"items": []}

    placement_by_meet = _group_placements_by_meet(placements_all)
    public_placement_by_meet = _group_placements_by_meet(placements_target)

    items = []
    for (year, meet), group in base.groupby(["대회연도_num", "대회명_text"], dropna=False, sort=False):
        year_int = int(year)
        meet_key = (year_int, meet)
        distances = sorted({int(v) for v in group["거리_num"].dropna().tolist()})

        date_candidates = []
        date_candidates.extend([_as_iso_date(value) for value in group["일자_정규화_text"].tolist()])
        date_candidates.extend([_as_iso_date(value) for value in group["일자_text"].tolist()])
        valid_dates = sorted({value for value in date_candidates if value})
        date_start = valid_dates[0] if valid_dates else None
        date_end = valid_dates[-1] if valid_dates else None
        location = _pick_location(group)

        athlete_count = int(group["idNo"].replace("", pd.NA).dropna().nunique())

        category_source = group[["idNo", "종별_text"]].copy()
        category_source = category_source[(category_source["idNo"] != "") & (category_source["종별_text"] != "")]
        category_source = category_source.drop_duplicates(subset=["idNo", "종별_text"])
        category_breakdown = (
            category_source.groupby("종별_text")["idNo"]
            .nunique()
            .sort_values(ascending=False)
            .reset_index(name="athleteCount")
            .rename(columns={"종별_text": "category"})
            .to_dict("records")
        )

        placement_group = placement_by_meet.get(meet_key, pd.DataFrame())
        round_types = sorted({str(value).strip() for value in placement_group.get("결승구분", pd.Series(dtype=str)).tolist() if str(value).strip()})
        race_count = int(len(placement_group)) if not placement_group.empty else int(group["거리_num"].notna().sum())
        has_semifinal = bool(group["라운드종류_text"].isin(["준결승", "준준결승"]).any())

        distribution_items = []
        for distance in distances:
            distance_rows = group[
                (group["거리_num"] == distance)
                & (group["라운드종류_text"] == "예선")
                & group["기록_초_num"].notna()
            ].copy()
            distance_athlete_count = int(distance_rows["idNo"].replace("", pd.NA).dropna().nunique())
            insufficient = distance_athlete_count < K_ANONYMITY_MIN
            if insufficient:
                distribution_items.append(
                    {
                        "distance": distance,
                        "athleteCount": None,
                        "insufficient": True,
                        "timeP10": None,
                        "timeP25": None,
                        "timeP50": None,
                        "timeP75": None,
                        "timeP90": None,
                    }
                )
                continue

            quantiles = distance_rows["기록_초_num"].quantile([0.10, 0.25, 0.50, 0.75, 0.90])
            distribution_items.append(
                {
                    "distance": distance,
                    "athleteCount": distance_athlete_count,
                    "insufficient": False,
                    "timeP10": round(float(quantiles.loc[0.10]), 3),
                    "timeP25": round(float(quantiles.loc[0.25]), 3),
                    "timeP50": round(float(quantiles.loc[0.50]), 3),
                    "timeP75": round(float(quantiles.loc[0.75]), 3),
                    "timeP90": round(float(quantiles.loc[0.90]), 3),
                }
            )

        public_group = public_placement_by_meet.get(meet_key, pd.DataFrame())
        public_results = []
        if not public_group.empty:
            for id_no, athlete_group in public_group.groupby("idNo", sort=False):
                public = active_public_by_id.get(as_id(id_no))
                if not public:
                    continue
                placements = []
                for _, row in athlete_group.iterrows():
                    rank = as_int(row.get("순위"))
                    if rank is None:
                        continue
                    placements.append(
                        {
                            "distance": as_int(row.get("거리")),
                            "rank": rank,
                            "sf": as_bool(row.get("SF여부")),
                            "round": _norm_text(row.get("결승구분")) or _norm_text(row.get("라운드종류")) or "-",
                        }
                    )
                placements = sorted(placements, key=lambda value: ((value.get("distance") is None), value.get("distance") or 9999, value.get("sf"), value.get("rank") or 9999))
                if not placements:
                    continue
                public_results.append(
                    {
                        "name": public["name"],
                        "slug": public["slug"],
                        "url": f"athlete/{public['slug']}/",
                        "bestRank": min(item["rank"] for item in placements),
                        "raceCount": len(placements),
                        "distances": sorted({item["distance"] for item in placements if item["distance"] is not None}),
                        "rounds": _unique_in_order([item["round"] for item in placements]),
                        "placements": placements,
                    }
                )
            public_results = sorted(public_results, key=lambda item: (item["bestRank"], item["name"]))

        slug_seed = _remove_year_prefix_from_slug(_normalize_slug_text(meet), year_int)
        series_key = _extract_series_key(meet)
        series_name = _extract_series_label(meet)
        series_round = _extract_round_order(meet)
        items.append(
            {
                "year": year_int,
                "meet": meet,
                "raceCount": race_count,
                "athleteCount": athlete_count,
                "distanceSet": distances,
                "roundTypes": round_types,
                "hasSemifinal": has_semifinal,
                "dateStart": date_start,
                "dateEnd": date_end,
                "location": location,
                "categoryBreakdown": category_breakdown,
                "distanceDistribution": {
                    "kAnonymityMin": K_ANONYMITY_MIN,
                    "insufficientText": INSUFFICIENT_TEXT,
                    "items": distribution_items,
                },
                "publicFigureResults": public_results,
                "seriesKey": series_key,
                "seriesName": series_name,
                "seriesRound": series_round,
                "_slugSeed": slug_seed,
                "seriesLinks": [],
            }
        )

    items = sorted(items, key=lambda item: (-item["year"], item["meet"]))

    slug_counts = {}
    for item in items:
        slug_seed = item.pop("_slugSeed") or "meet"
        slug_base = _build_meet_slug(item["year"], item["meet"], slug_seed)
        slug_counts[slug_base] = slug_counts.get(slug_base, 0) + 1
        count = slug_counts[slug_base]
        slug = slug_base if count == 1 else f"{slug_base}-{count}"
        item["slug"] = slug
        item["url"] = f"meet/{slug}/"

    by_series = {}
    for item in items:
        by_series.setdefault(item["seriesKey"], []).append(item)
    for series_items in by_series.values():
        ordered = sorted(
            series_items,
            key=lambda item: (
                -(item["year"] or 0),
                item["seriesRound"] is None,
                item["seriesRound"] or 9999,
                item["meet"],
            ),
        )
        for current in ordered:
            current["seriesLinks"] = [
                {
                    "year": other["year"],
                    "meet": other["meet"],
                    "slug": other["slug"],
                    "url": other["url"],
                }
                for other in ordered
                if other["slug"] != current["slug"]
            ]

    return {"items": items}


def attach_meet_links(athletes, meets):
    meet_map = {}
    for item in meets.get("items", []):
        key = (as_int(item.get("year")), _norm_text(item.get("meet")))
        if key[0] is None or not key[1]:
            continue
        meet_map[key] = item
    for athlete in athletes:
        history = athlete.get("history", [])
        for row in history:
            key = (as_int(row.get("year")), _norm_text(row.get("meet")))
            target = meet_map.get(key)
            row["meetSlug"] = target["slug"] if target else None
            row["meetUrl"] = target["url"] if target else None


def _read_metric_value(raw_value, row_no, column_name):
    text = str(raw_value or "").strip()
    if not text:
        raise ValueError(f"[error] data/stats_distribution.csv {row_no}행 {column_name} 값이 비어 있습니다.")
    value = as_float(text)
    if value is None:
        raise ValueError(f"[error] data/stats_distribution.csv {row_no}행 {column_name} 값이 숫자가 아닙니다: {text}")
    return value


def _unique_in_order(values):
    return list(dict.fromkeys(values))


def _read_metric_group(item, row_no, metric_map, count_text, count_label):
    insufficient = count_text == INSUFFICIENT_TEXT
    values = {}
    count_value = None
    if not count_text:
        raise ValueError(f"[error] data/stats_distribution.csv {row_no}행 {count_label} 값이 비어 있습니다.")
    if insufficient:
        for source_col, target_col, _round_digits in metric_map:
            metric_text = str(item.get(source_col, "")).strip()
            if metric_text != INSUFFICIENT_TEXT:
                raise ValueError(
                    f"[error] data/stats_distribution.csv {row_no}행: {count_label}=데이터 부족인데 {source_col} 값이 노출되었습니다."
                )
            values[target_col] = None
    else:
        count_value = as_int(count_text)
        if count_value is None:
            raise ValueError(f"[error] data/stats_distribution.csv {row_no}행 {count_label} 값이 숫자가 아닙니다: {count_text}")
        if count_value < K_ANONYMITY_MIN:
            raise ValueError(
                f"[error] data/stats_distribution.csv {row_no}행 {count_label}가 k-익명 기준 미만으로 노출되었습니다: {count_value}"
            )
        for source_col, target_col, round_digits in metric_map:
            values[target_col] = round(_read_metric_value(item.get(source_col, ""), row_no, source_col), round_digits)
    return count_value, insufficient, values


def build_distribution(stats_distribution_frame):
    columns = list(stats_distribution_frame.columns)
    if columns != STATS_DISTRIBUTION_REQUIRED_COLUMNS:
        raise ValueError(f"[error] data/stats_distribution.csv 컬럼이 기대값과 다릅니다: {columns}")

    rows = []
    for idx, item in stats_distribution_frame.iterrows():
        row_no = idx + 2
        birth_year = as_int(item.get("출생연도", ""))
        gender = str(item.get("성별", "")).strip()
        distance = as_int(item.get("거리", ""))
        if birth_year is None:
            raise ValueError(f"[error] data/stats_distribution.csv {row_no}행 출생연도 값이 올바르지 않습니다.")
        if not gender:
            raise ValueError(f"[error] data/stats_distribution.csv {row_no}행 성별 값이 비어 있습니다.")
        if distance is None:
            raise ValueError(f"[error] data/stats_distribution.csv {row_no}행 거리 값이 올바르지 않습니다.")

        # 기록과 순위는 집계 필터가 달라 표본 크기가 다르므로 각각 독립으로 판정한다.
        time_count, time_insufficient, time_values = _read_metric_group(
            item, row_no, TIME_METRIC_MAP, str(item.get("기록_인원수", "")).strip(), "기록_인원수"
        )
        rank_count, rank_insufficient, rank_values = _read_metric_group(
            item, row_no, RANK_METRIC_MAP, str(item.get("순위_인원수", "")).strip(), "순위_인원수"
        )

        rows.append(
            {
                "birthYear": birth_year,
                "gender": gender,
                "distance": distance,
                "timeCount": time_count,
                "timeInsufficient": time_insufficient,
                "rankCount": rank_count,
                "rankInsufficient": rank_insufficient,
                **time_values,
                **rank_values,
            }
        )

    rows = sorted(rows, key=lambda row: (row["birthYear"], row["gender"], row["distance"]))

    return {
        "kAnonymityMin": K_ANONYMITY_MIN,
        "insufficientText": INSUFFICIENT_TEXT,
        "filters": {
            "birthYears": sorted({row["birthYear"] for row in rows}),
            "genders": _unique_in_order([row["gender"] for row in rows]),
            "distances": sorted({row["distance"] for row in rows}),
        },
        "rows": rows,
    }


def build_meta(payload, public_figures):
    meta = dict(payload["meta"])
    meta["generatedAt"] = date.today().isoformat()
    meta["publicFigureCount"] = len(public_figures)
    meta["activeFigureCount"] = int(meta.get("athleteCount") or 0)
    return meta


def assert_public_scope(athletes, active_id_set):
    exported_ids = {as_id(item.get("idNo")) for item in athletes if as_id(item.get("idNo"))}
    extra = sorted(v for v in exported_ids if v not in active_id_set)
    if extra:
        raise ValueError(f"[error] 공개 명단 외 idNo가 athletes.json에 포함되었습니다: {', '.join(extra[:5])}")


def main():
    load_local_env()
    try:
        frames = {name: read_csv(name) for name in INPUT_FILES}
        payload, placements_target, public_figures, active_id_set = build_athletes_payload(frames)
        active_public_by_id = {item["idNo"]: item for item in public_figures if item.get("status") == "active"}
        meet_records, meet_placements = _load_meet_source()
        records_anon = build_records_anon(meet_records, os.environ.get(ANON_SALT_ENV, ""))
        validate_records_anon(records_anon)
        meets = build_meets(meet_records, meet_placements, placements_target, active_public_by_id)
        attach_meet_links(payload["athletes"], meets)
        distribution = build_distribution(frames["stats_distribution.csv"])
        meta = build_meta(payload, public_figures)
        athletes_doc = {"ages": payload["ages"], "athletes": payload["athletes"]}
        assert_public_scope(athletes_doc["athletes"], active_id_set)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return

    write_csv(RECORDS_ANON_CSV, records_anon)
    write_json(ATHLETES_JSON, athletes_doc)
    write_json(MEETS_JSON, meets)
    write_json(DISTRIBUTION_JSON, distribution)
    write_json(META_JSON, meta)
    to_cd_stats = records_anon.attrs.get("to_cd_stats") or {}
    if to_cd_stats.get("source_path"):
        print(
            "[ok] records_anon toCd 매핑: source={0} matched={1}/{2} (unmatched={3}, ambiguous={4})".format(
                to_cd_stats.get("source_path"),
                to_cd_stats.get("matched", 0),
                to_cd_stats.get("total", 0),
                to_cd_stats.get("unmatched", 0),
                to_cd_stats.get("ambiguous", 0),
            )
        )
        print(
            "[ok] records_anon toCd 채움: direct={0}, mapped={1}, unresolved={2} / total_rows={3}".format(
                to_cd_stats.get("rows_direct", 0),
                to_cd_stats.get("rows_mapped", 0),
                to_cd_stats.get("rows_unresolved", 0),
                to_cd_stats.get("rows_total", 0),
            )
        )
    else:
        print("[ok] records_anon toCd 매핑: meet_index_inf201.csv 미발견으로 공백 유지")
    print(f"[ok] 생성 완료: {RECORDS_ANON_CSV}")
    print(f"[ok] 생성 완료: {ATHLETES_JSON}")
    print(f"[ok] 생성 완료: {MEETS_JSON}")
    print(f"[ok] 생성 완료: {DISTRIBUTION_JSON}")
    print(f"[ok] 생성 완료: {META_JSON}")


if __name__ == "__main__":
    main()
