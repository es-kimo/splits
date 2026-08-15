import argparse
import csv
import json
import os
import pathlib
import re
import time
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

from build_data import ANON_SALT_ENV, RECORDS_ANON_REQUIRED_COLUMNS, build_records_anon, validate_records_anon
from analyze import build_clean_records
from event_participants import (
    _base_payload,
    _extract_participant_entries,
    _extract_result_headers,
    _find_table_by_caption,
    _parse_js_args,
)
from local_env import load_local_env
from scrape import parse_athlete_info, parse_history

BASE_URL = "https://result.sports.or.kr/SK"
INF201_ENDPOINT = f"{BASE_URL}/INF201.do"
INF301_ENDPOINT = f"{BASE_URL}/INF301.do"
INF310_ENDPOINT = f"{BASE_URL}/INF310.do"
INF503_ENDPOINT = f"{BASE_URL}/INF503.do"
DETAIL_CLASS_AJAX_ENDPOINT = f"{BASE_URL}/code/selectDetailClassCdListAjax.do"

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "splits-full-collector/2.0 (+https://github.com/es-kimo/splits)",
}
JSON_HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "User-Agent": "splits-full-collector/2.0 (+https://github.com/es-kimo/splits)",
}
TIMEOUT_SECONDS = 20
REQUEST_GAP_SECONDS = 1.0
RETRY_GAP_SECONDS = 5.0
MAX_RETRIES = 3

DEFAULT_DATA_DIR = pathlib.Path("data")
DATA_DIR = DEFAULT_DATA_DIR

RAW_ROOT_DIR = DATA_DIR / "raw"
RAW_INF201_DIR = RAW_ROOT_DIR / "inf201"
RAW_INF301_KIND_DIR = RAW_ROOT_DIR / "inf301_kind"
RAW_DETAIL_AJAX_DIR = RAW_ROOT_DIR / "detail_class_ajax"
RAW_INF301_DIR = RAW_ROOT_DIR / "inf301"
RAW_INF310_DIR = RAW_ROOT_DIR / "inf310"
RAW_INF503_DIR = RAW_ROOT_DIR / "inf503"

PROGRESS_JSON = DATA_DIR / "collect_progress.json"
REQUEST_FAILURES_CSV = DATA_DIR / "collect_request_failures.csv"
MEET_FAILURES_CSV = DATA_DIR / "collect_failures.csv"
DETAIL_FAILURES_CSV = DATA_DIR / "detail_failures.csv"
MEET_INDEX_INF201_CSV = DATA_DIR / "meet_index_inf201.csv"
WEEKLY_SUMMARY_JSON = DATA_DIR / "weekly_incremental_summary.json"
SUSPICIOUS_IDS_CSV = DATA_DIR / "suspicious_ids.csv"
RECORDS_ANON_CSV = DATA_DIR / "records_anon.csv"
RECORDS_FULL_CSV = DATA_DIR / "records_full.csv"
ATHLETE_INFO_FULL_CSV = DATA_DIR / "athlete_info_full.csv"
RECORDS_CSV = DATA_DIR / "records.csv"
ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"
RESOLVED_CSV = DATA_DIR / "resolved.csv"
MEET_INDEX_FIELDS = ["classCd", "toCd", "searchAppYn", "대회명", "장소", "기간", "상태", "pageIndex", "updatedAt"]
ANON_RECORD_KEY_FIELDS = ["익명키", "대회명", "종별", "거리", "SF여부", "라운드", "순위", "기록_초"]
KNOWN_WARNING_STAGES = {"inf301_result_call_parse", "inf310_zero_participant"}

FAILURE_FIELDS = [
    "requestType",
    "requestKey",
    "endpoint",
    "payloadJson",
    "cachePath",
    "context",
    "reason",
    "attempts",
    "최종실패시각",
]
MEET_FAILURE_FIELDS = [
    "classCd",
    "toCd",
    "대회명",
    "event_status",
    "세부종목수",
    "성공세부종목수",
    "실패세부종목수",
    "경고세부종목수",
    "대표실패단계",
    "대표사유",
    "최종실패시각",
    "시도횟수",
]
DETAIL_FAILURE_FIELDS = [
    "classCd",
    "toCd",
    "kindCd",
    "detailClassCd",
    "실패단계",
    "단계",
    "사유",
    "대회명",
    "종별",
    "세부종목",
    "심각도",
    "최종시각",
]
SUSPICIOUS_ID_FIELDS = [
    "classCd",
    "toCd",
    "대회명",
    "kindCd",
    "detailClassCd",
    "baseClassCd",
    "rhCd",
    "pcntGbn",
    "idNo_원본",
    "추출소스",
    "행대표이름",
]
ATHLETE_INFO_FIELDS = ["idNo", "이름", "성별", "출생년도", "종별", "소속팀", "팀코드", "시도"]
RECORD_FIELDS = [
    "idNo",
    "대회명",
    "일자",
    "일자_정규화",
    "종별",
    "세부종목",
    "라운드",
    "소속",
    "기록",
    "순위",
    "학년",
    "레인",
    "BIB",
    "사유",
    "기록차",
    "classCd",
    "toCd",
    "kindCd",
    "detailClassCd",
    "baseClassCd",
    "rhCd",
    "pcntGbn",
    "소스",
    "source",
]

DATE_DIGITS_RE = re.compile(r"^(19|20)\d{2}(0[1-9]|1[0-2])([0-2]\d|3[01])$")
DATE_DOTTED_RE = re.compile(r"^((?:19|20)\d{2})[.\-/](0?[1-9]|1[0-2])[.\-/](0?[1-9]|[12]\d|3[01])$")
FIRST_DATE_RE = re.compile(r"((?:19|20)\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")
KIND_CD_RE = re.compile(r"^\d{2}$")
MEET_NAME_NORMALIZE_RE = re.compile(r"[^0-9a-z가-힣]+")


def _configure_data_paths(base_dir):
    global DATA_DIR
    global RAW_ROOT_DIR
    global RAW_INF201_DIR
    global RAW_INF301_KIND_DIR
    global RAW_DETAIL_AJAX_DIR
    global RAW_INF301_DIR
    global RAW_INF310_DIR
    global RAW_INF503_DIR
    global PROGRESS_JSON
    global REQUEST_FAILURES_CSV
    global MEET_FAILURES_CSV
    global DETAIL_FAILURES_CSV
    global MEET_INDEX_INF201_CSV
    global WEEKLY_SUMMARY_JSON
    global SUSPICIOUS_IDS_CSV
    global RECORDS_ANON_CSV
    global RECORDS_FULL_CSV
    global ATHLETE_INFO_FULL_CSV
    global RECORDS_CSV
    global ATHLETE_INFO_CSV
    global RESOLVED_CSV

    DATA_DIR = pathlib.Path(base_dir).expanduser()
    RAW_ROOT_DIR = DATA_DIR / "raw"
    RAW_INF201_DIR = RAW_ROOT_DIR / "inf201"
    RAW_INF301_KIND_DIR = RAW_ROOT_DIR / "inf301_kind"
    RAW_DETAIL_AJAX_DIR = RAW_ROOT_DIR / "detail_class_ajax"
    RAW_INF301_DIR = RAW_ROOT_DIR / "inf301"
    RAW_INF310_DIR = RAW_ROOT_DIR / "inf310"
    RAW_INF503_DIR = RAW_ROOT_DIR / "inf503"

    PROGRESS_JSON = DATA_DIR / "collect_progress.json"
    REQUEST_FAILURES_CSV = DATA_DIR / "collect_request_failures.csv"
    MEET_FAILURES_CSV = DATA_DIR / "collect_failures.csv"
    DETAIL_FAILURES_CSV = DATA_DIR / "detail_failures.csv"
    MEET_INDEX_INF201_CSV = DATA_DIR / "meet_index_inf201.csv"
    WEEKLY_SUMMARY_JSON = DATA_DIR / "weekly_incremental_summary.json"
    SUSPICIOUS_IDS_CSV = DATA_DIR / "suspicious_ids.csv"
    RECORDS_ANON_CSV = DATA_DIR / "records_anon.csv"
    RECORDS_FULL_CSV = DATA_DIR / "records_full.csv"
    ATHLETE_INFO_FULL_CSV = DATA_DIR / "athlete_info_full.csv"
    RECORDS_CSV = DATA_DIR / "records.csv"
    ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"
    RESOLVED_CSV = DATA_DIR / "resolved.csv"


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _norm(value):
    return str(value or "").strip()


def _normalize_meet_name(value):
    return MEET_NAME_NORMALIZE_RE.sub("", _norm(value).lower())


def _record_identity_key(id_no, meet_name, detail_name, round_name, rank, record):
    return (
        _norm(id_no),
        _normalize_meet_name(meet_name),
        _norm(detail_name),
        _norm(round_name),
        _norm(rank),
        _norm(record),
    )


def _safe_fragment(value):
    text = _norm(value)
    if not text:
        return "empty"
    return re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", text)


def _normalize_date_text(raw):
    text = _norm(raw)
    if not text:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    if DATE_DIGITS_RE.fullmatch(text):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    dotted = DATE_DOTTED_RE.fullmatch(text)
    if dotted:
        return f"{dotted.group(1)}-{int(dotted.group(2)):02d}-{int(dotted.group(3)):02d}"
    return ""


def _extract_event_date(event_info):
    for key in ["기간", "대회기간", "경기기간"]:
        value = _norm(event_info.get(key))
        if not value:
            continue
        direct = _normalize_date_text(value)
        if direct:
            return value, direct
        match = FIRST_DATE_RE.search(value)
        if not match:
            continue
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return value, f"{year:04d}-{month:02d}-{day:02d}"
    return "", ""


def _default_progress():
    return {
        "version": 3,
        "updated_at": "",
        "last_mode": "",
        "request_gap_seconds": REQUEST_GAP_SECONDS,
        "counters": {
            "request_network_attempted": 0,
            "request_cache_hit": 0,
            "request_success": 0,
            "request_failure": 0,
            "request_sleep_applied": 0,
            "inf201_pages_parsed": 0,
            "inf201_events_total": 0,
            "inf201_events_class2": 0,
            "inf301_kind_requests": 0,
            "detail_class_ajax_requests": 0,
            "inf301_requests": 0,
            "inf310_requests": 0,
            "inf503_requests": 0,
            "records_inf310_rows": 0,
            "records_inf503_score_rows": 0,
        },
        "meets": {},
        "last_summary": {},
    }


def _load_progress():
    if not PROGRESS_JSON.exists():
        return _default_progress()
    try:
        payload = json.loads(PROGRESS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[warn] {PROGRESS_JSON} 파싱 실패: 진행상태를 초기화합니다.")
        return _default_progress()
    default = _default_progress()
    for key, value in default.items():
        payload.setdefault(key, value)
    if "counters" not in payload or not isinstance(payload["counters"], dict):
        payload["counters"] = default["counters"]
    else:
        for key, value in default["counters"].items():
            payload["counters"].setdefault(key, value)
    if "meets" not in payload or not isinstance(payload["meets"], dict):
        payload["meets"] = {}
    return payload


def _save_progress(progress):
    progress["updated_at"] = _now_iso()
    PROGRESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PROGRESS_JSON)


def _bump_counter(progress, key, amount=1):
    progress["counters"][key] = int(progress["counters"].get(key, 0)) + int(amount)


def _meet_key(class_cd, to_cd):
    return f"{_norm(class_cd)}:{_norm(to_cd)}"


def _ensure_meet_progress(progress, event):
    class_cd = _norm(event.get("classCd"))
    to_cd = _norm(event.get("toCd"))
    key = _meet_key(class_cd, to_cd)
    meets = progress.setdefault("meets", {})
    if key not in meets:
        meets[key] = {
            "classCd": class_cd,
            "toCd": to_cd,
            "대회명": _norm(event.get("대회명")),
            "상태": "pending",
            "마지막단계": "",
            "마지막오류": "",
            "시도횟수": 0,
            "updated_at": "",
        }
    return key, meets[key]


def _seed_meet_progress(progress, events):
    for event in events:
        _ensure_meet_progress(progress, event)


def _set_meet_status(progress, event, status, stage="", error=""):
    key, item = _ensure_meet_progress(progress, event)
    item["상태"] = _norm(status) or item["상태"]
    item["마지막단계"] = _norm(stage)
    item["마지막오류"] = _norm(error)
    if status == "in_progress":
        item["시도횟수"] = int(item.get("시도횟수", 0)) + 1
    item["updated_at"] = _now_iso()
    progress["meets"][key] = item
    _save_progress(progress)


def _load_csv_rows(path):
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _save_csv_rows(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        if path.exists():
            path.unlink()
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_meet_index_row(row, *, updated_at):
    return {
        "classCd": _norm(row.get("classCd")),
        "toCd": _norm(row.get("toCd")),
        "searchAppYn": _norm(row.get("searchAppYn")),
        "대회명": _norm(row.get("대회명")),
        "장소": _norm(row.get("장소")),
        "기간": _norm(row.get("기간")),
        "상태": _norm(row.get("상태")),
        "pageIndex": _norm(row.get("pageIndex")),
        "updatedAt": _norm(row.get("updatedAt")) or updated_at,
    }


def _meet_index_sort_key(row):
    class_cd = _norm(row.get("classCd"))
    to_cd = _norm(row.get("toCd"))
    class_part = (0, int(class_cd)) if class_cd.isdigit() else (1, class_cd)
    to_part = (0, int(to_cd)) if to_cd.isdigit() else (1, to_cd)
    return class_part + to_part


def _load_meet_index_rows():
    rows = []
    for row in _load_csv_rows(MEET_INDEX_INF201_CSV):
        class_cd = _norm(row.get("classCd"))
        to_cd = _norm(row.get("toCd"))
        if not class_cd or not to_cd:
            continue
        rows.append(_build_meet_index_row(row, updated_at=_now_iso()))
    return sorted(rows, key=_meet_index_sort_key)


def _save_meet_index_rows(rows):
    normalized = []
    now_iso = _now_iso()
    for row in rows:
        class_cd = _norm(row.get("classCd"))
        to_cd = _norm(row.get("toCd"))
        if not class_cd or not to_cd:
            continue
        normalized.append(_build_meet_index_row(row, updated_at=now_iso))
    normalized = sorted(normalized, key=_meet_index_sort_key)
    _save_csv_rows(MEET_INDEX_INF201_CSV, normalized, MEET_INDEX_FIELDS)
    return normalized


def _merge_meet_index_rows(*row_sets):
    merged = {}
    now_iso = _now_iso()
    for rows in row_sets:
        for row in rows:
            class_cd = _norm(row.get("classCd"))
            to_cd = _norm(row.get("toCd"))
            if not class_cd or not to_cd:
                continue
            key = _meet_key(class_cd, to_cd)
            merged[key] = _build_meet_index_row(row, updated_at=now_iso)
    return sorted(merged.values(), key=_meet_index_sort_key)


def _seed_meet_index_from_records_anon():
    if not RECORDS_ANON_CSV.exists():
        return []
    frame = pd.read_csv(RECORDS_ANON_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    if "toCd" not in frame.columns or "대회명" not in frame.columns:
        return []
    base = frame.copy()
    base["toCd"] = base["toCd"].astype(str).str.strip()
    base["대회명"] = base["대회명"].astype(str).str.strip()
    base["일자"] = base["일자"].astype(str).str.strip() if "일자" in base.columns else ""
    base = base[(base["toCd"] != "") & (base["대회명"] != "")].copy()
    if base.empty:
        return []
    rows = []
    now_iso = _now_iso()
    for to_cd, group in base.groupby(["toCd"], dropna=False, sort=True):
        meet_counts = group["대회명"].value_counts()
        meet_name = meet_counts.index[0] if not meet_counts.empty else ""
        dates = sorted({value for value in group["일자"].tolist() if _norm(value)})
        period = ""
        if dates:
            period = dates[0] if len(dates) == 1 else f"{dates[0]}~{dates[-1]}"
        rows.append(
            {
                "classCd": "2",
                "toCd": _norm(to_cd),
                "searchAppYn": "",
                "대회명": _norm(meet_name),
                "장소": "",
                "기간": period,
                "상태": "",
                "pageIndex": "",
                "updatedAt": now_iso,
            }
        )
    return sorted(rows, key=_meet_index_sort_key)


def _ensure_meet_index_rows():
    rows = _load_meet_index_rows()
    if rows:
        return rows, False
    seeded = _seed_meet_index_from_records_anon()
    if not seeded:
        return [], False
    saved = _save_meet_index_rows(seeded)
    print(f"[weekly] meet_index 초기 시드 생성: {MEET_INDEX_INF201_CSV} ({len(saved)}건)")
    return saved, True


def _collect_inf201_page_events(session, page_index, *, refresh, request_gap_seconds, progress, failures):
    cache_path = _cache_path_inf201(page_index)
    payload = _base_payload()
    payload["pageIndex"] = str(page_index)
    request_key = f"inf201:{page_index}"
    html, _, _reason = _fetch_with_cache(
        session,
        request_type="inf201",
        request_key=request_key,
        endpoint=INF201_ENDPOINT,
        payload=payload,
        cache_path=cache_path,
        context=f"page={page_index}",
        refresh=refresh,
        request_gap_seconds=request_gap_seconds,
        progress=progress,
        failures=failures,
    )
    _bump_counter(progress, "inf201_pages_parsed")
    _save_progress(progress)
    if html is None:
        return []
    return _parse_inf201_events_html(html, page_index=page_index)


def _append_records_anon_from_full():
    if not RECORDS_FULL_CSV.exists() or not ATHLETE_INFO_FULL_CSV.exists():
        raise FileNotFoundError(f"[error] 익명 append 입력이 없습니다: {RECORDS_FULL_CSV}, {ATHLETE_INFO_FULL_CSV}")

    records_full = pd.read_csv(RECORDS_FULL_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    athlete_full = pd.read_csv(ATHLETE_INFO_FULL_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    clean_records = build_clean_records(records_full, athlete_full)
    records_anon_new = build_records_anon(clean_records, os.environ.get(ANON_SALT_ENV, ""))
    validate_records_anon(records_anon_new)

    if RECORDS_ANON_CSV.exists():
        existing = pd.read_csv(RECORDS_ANON_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    else:
        existing = pd.DataFrame(columns=RECORDS_ANON_REQUIRED_COLUMNS)
    existing = existing.reindex(columns=RECORDS_ANON_REQUIRED_COLUMNS).fillna("")

    key_sep = "\u241f"
    existing_key = existing[ANON_RECORD_KEY_FIELDS].astype(str).agg(key_sep.join, axis=1)
    new_key = records_anon_new[ANON_RECORD_KEY_FIELDS].astype(str).agg(key_sep.join, axis=1)
    append_mask = ~new_key.isin(set(existing_key.tolist()))
    appended_rows = records_anon_new.loc[append_mask].copy()
    duplicate_rows = int((~append_mask).sum())

    merged = pd.concat([existing, appended_rows[RECORDS_ANON_REQUIRED_COLUMNS]], ignore_index=True)
    merged = merged.fillna("")
    merged = merged.sort_values(["대회연도", "대회명", "일자", "거리", "라운드", "익명키"], na_position="last").reset_index(drop=True)
    merged_key = merged[ANON_RECORD_KEY_FIELDS].astype(str).agg(key_sep.join, axis=1)
    dup_count = int(merged_key.duplicated().sum())
    if dup_count:
        raise ValueError(f"[error] records_anon append 후 중복 키가 남았습니다: {dup_count}건")

    merged.to_csv(RECORDS_ANON_CSV, index=False, encoding="utf-8-sig")
    print(
        "[weekly] records_anon append: 신규 {0:,}건 / 기존중복스킵 {1:,}건 / 총 {2:,}건".format(
            int(len(appended_rows)),
            duplicate_rows,
            int(len(merged)),
        )
    )
    return {
        "appended_rows": int(len(appended_rows)),
        "duplicate_skipped": duplicate_rows,
        "total_rows": int(len(merged)),
    }

def _load_failures():
    failures = {}
    for row in _load_csv_rows(REQUEST_FAILURES_CSV):
        key = _norm(row.get("requestKey"))
        if not key:
            continue
        failures[key] = {
            "requestType": _norm(row.get("requestType")),
            "requestKey": key,
            "endpoint": _norm(row.get("endpoint")),
            "payloadJson": _norm(row.get("payloadJson")),
            "cachePath": _norm(row.get("cachePath")),
            "context": _norm(row.get("context")),
            "reason": _norm(row.get("reason")),
            "attempts": _norm(row.get("attempts")),
            "최종실패시각": _norm(row.get("최종실패시각")),
        }
    return failures


def _save_failures(failures):
    rows = [failures[key] for key in sorted(failures.keys())]
    _save_csv_rows(REQUEST_FAILURES_CSV, rows, FAILURE_FIELDS)


def _load_meet_failures():
    failures = {}
    for row in _load_csv_rows(MEET_FAILURES_CSV):
        class_cd = _norm(row.get("classCd"))
        to_cd = _norm(row.get("toCd"))
        if not class_cd or not to_cd:
            continue
        key = f"{class_cd}:{to_cd}"
        failures[key] = {
            "classCd": class_cd,
            "toCd": to_cd,
            "대회명": _norm(row.get("대회명")),
            "event_status": _norm(row.get("event_status")) or "실패",
            "세부종목수": _norm(row.get("세부종목수")),
            "성공세부종목수": _norm(row.get("성공세부종목수")),
            "실패세부종목수": _norm(row.get("실패세부종목수")),
            "경고세부종목수": _norm(row.get("경고세부종목수")),
            "대표실패단계": _norm(row.get("대표실패단계") or row.get("실패단계")),
            "대표사유": _norm(row.get("대표사유") or row.get("사유")),
            "최종실패시각": _norm(row.get("최종실패시각")),
            "시도횟수": _norm(row.get("시도횟수")),
        }
    return failures


def _save_meet_failures(meet_failures):
    rows = [meet_failures[key] for key in sorted(meet_failures.keys())]
    _save_csv_rows(MEET_FAILURES_CSV, rows, MEET_FAILURE_FIELDS)


def _map_event_status_to_progress(event_status):
    status = _norm(event_status)
    if status == "완료":
        return "done"
    if status == "부분완료":
        return "partial"
    return "failed"


def _apply_event_status_rows(progress, meet_failures, event_status_rows):
    for row in event_status_rows:
        class_cd = _norm(row.get("classCd"))
        to_cd = _norm(row.get("toCd"))
        if not class_cd or not to_cd:
            continue
        key = _meet_key(class_cd, to_cd)
        event_stub = {"classCd": class_cd, "toCd": to_cd, "대회명": _norm(row.get("대회명"))}
        event_status = _norm(row.get("event_status")) or "실패"
        _set_meet_status(
            progress,
            event_stub,
            _map_event_status_to_progress(event_status),
            stage=_norm(row.get("대표실패단계")),
            error=_norm(row.get("대표사유")),
        )
        if event_status == "완료":
            if key in meet_failures:
                meet_failures.pop(key)
            continue
        meet_item = progress.get("meets", {}).get(key, {})
        meet_failures[key] = {
            "classCd": class_cd,
            "toCd": to_cd,
            "대회명": _norm(row.get("대회명")),
            "event_status": event_status,
            "세부종목수": _norm(row.get("세부종목수")),
            "성공세부종목수": _norm(row.get("성공세부종목수")),
            "실패세부종목수": _norm(row.get("실패세부종목수")),
            "경고세부종목수": _norm(row.get("경고세부종목수")),
            "대표실패단계": _norm(row.get("대표실패단계")),
            "대표사유": _norm(row.get("대표사유")),
            "최종실패시각": _now_iso(),
            "시도횟수": str(int(meet_item.get("시도횟수", 0))),
        }
    _save_meet_failures(meet_failures)


def _is_retryable_http(status_code):
    return status_code == 429 or status_code >= 500


def _post_with_retry(session, endpoint, payload, *, headers=None, json_body=False):
    last_reason = "unknown"
    req_headers = headers or HEADERS
    body = json.dumps(payload, ensure_ascii=False) if json_body else payload
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.post(endpoint, data=body, headers=req_headers, timeout=TIMEOUT_SECONDS)
        except requests.Timeout:
            last_reason = "timeout"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_GAP_SECONDS)
                continue
            return None, attempt, last_reason
        except requests.RequestException as exc:
            last_reason = f"network_error:{exc.__class__.__name__}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_GAP_SECONDS)
                continue
            return None, attempt, last_reason

        status = int(response.status_code)
        if _is_retryable_http(status):
            last_reason = f"http_{status}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_GAP_SECONDS)
                continue
            return None, attempt, last_reason
        if status >= 400:
            return None, attempt, f"http_{status}"
        return response.text, attempt, ""
    return None, MAX_RETRIES, last_reason


def _record_failure(failures, request_type, request_key, endpoint, payload, cache_path, context, reason, attempts):
    failures[request_key] = {
        "requestType": request_type,
        "requestKey": request_key,
        "endpoint": endpoint,
        "payloadJson": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "cachePath": str(cache_path),
        "context": context,
        "reason": reason,
        "attempts": str(attempts),
        "최종실패시각": _now_iso(),
    }


def _clear_failure(failures, request_key):
    if request_key in failures:
        failures.pop(request_key)


def _cache_path_inf201(page_index):
    return RAW_INF201_DIR / f"{int(page_index):03d}.html"


def _cache_path_inf301_kind(class_cd, to_cd):
    return RAW_INF301_KIND_DIR / f"{_safe_fragment(class_cd)}_{_safe_fragment(to_cd)}.html"


def _legacy_cache_path_inf301_kind(to_cd):
    return RAW_INF301_KIND_DIR / f"{_safe_fragment(to_cd)}.html"


def _cache_path_detail_class_ajax(class_cd, to_cd, kind_cd):
    return RAW_DETAIL_AJAX_DIR / f"{_safe_fragment(class_cd)}_{_safe_fragment(to_cd)}_{_safe_fragment(kind_cd)}.json"


def _cache_path_inf301(class_cd, to_cd, kind_cd, detail_class_cd):
    return (
        RAW_INF301_DIR
        / f"{_safe_fragment(class_cd)}_{_safe_fragment(to_cd)}_{_safe_fragment(kind_cd)}_{_safe_fragment(detail_class_cd)}.html"
    )


def _legacy_cache_path_inf301(to_cd, kind_cd, detail_class_cd):
    return RAW_INF301_DIR / f"{_safe_fragment(to_cd)}_{_safe_fragment(kind_cd)}_{_safe_fragment(detail_class_cd)}.html"


def _cache_path_inf310(class_cd, to_cd, kind_cd, detail_class_cd, base_class_cd, rh_cd, pcnt_gbn):
    return RAW_INF310_DIR / (
        f"{_safe_fragment(class_cd)}_{_safe_fragment(to_cd)}_{_safe_fragment(kind_cd)}_{_safe_fragment(detail_class_cd)}_"
        f"{_safe_fragment(base_class_cd)}_{_safe_fragment(rh_cd)}_{_safe_fragment(pcnt_gbn)}.html"
    )


def _legacy_cache_path_inf310(to_cd, kind_cd, detail_class_cd, base_class_cd, rh_cd, pcnt_gbn):
    return RAW_INF310_DIR / (
        f"{_safe_fragment(to_cd)}_{_safe_fragment(kind_cd)}_{_safe_fragment(detail_class_cd)}_"
        f"{_safe_fragment(base_class_cd)}_{_safe_fragment(rh_cd)}_{_safe_fragment(pcnt_gbn)}.html"
    )


def _cache_path_inf503(id_no):
    return RAW_INF503_DIR / f"{_safe_fragment(id_no)}.html"


def _fetch_with_cache(
    session,
    *,
    request_type,
    request_key,
    endpoint,
    payload,
    cache_path,
    context,
    refresh,
    request_gap_seconds,
    progress,
    failures,
    headers=None,
    json_body=False,
):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not refresh:
        _bump_counter(progress, "request_cache_hit")
        _clear_failure(failures, request_key)
        _save_failures(failures)
        _save_progress(progress)
        return cache_path.read_text(encoding="utf-8"), True, ""

    _bump_counter(progress, "request_network_attempted")
    html, attempts, reason = _post_with_retry(session, endpoint, payload, headers=headers, json_body=json_body)
    if html is None:
        _bump_counter(progress, "request_failure")
        _record_failure(
            failures,
            request_type=request_type,
            request_key=request_key,
            endpoint=endpoint,
            payload=payload,
            cache_path=cache_path,
            context=context,
            reason=reason,
            attempts=attempts,
        )
        _save_failures(failures)
        _save_progress(progress)
        print(f"[fail] {request_type} {context} (reason={reason}, attempts={attempts})")
        return None, False, reason

    cache_path.write_text(html, encoding="utf-8")
    _bump_counter(progress, "request_success")
    _clear_failure(failures, request_key)
    _save_failures(failures)
    _save_progress(progress)
    if request_gap_seconds > 0:
        time.sleep(request_gap_seconds)
        _bump_counter(progress, "request_sleep_applied")
        _save_progress(progress)
    return html, False, ""


def _parse_inf201_events_html(html, page_index):
    soup = BeautifulSoup(html, "html.parser")
    default_search_app_yn = ""
    node = soup.find("input", attrs={"name": "searchAppYn"})
    if node and node.has_attr("value"):
        default_search_app_yn = _norm(node.get("value", ""))
    events = []
    for tr in soup.find_all("tr"):
        args = _parse_js_args(tr.get("onclick", ""), "fnEventInfo")
        if not args or len(args) < 2:
            continue
        class_cd = _norm(args[0])
        to_cd = _norm(args[1])
        search_app_yn = _norm(args[2]) if len(args) >= 3 else default_search_app_yn
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        event_name = _norm(tds[1].get_text(" ", strip=True))
        place = _norm(tds[2].get_text(" ", strip=True))
        period = _norm(tds[3].get_text(" ", strip=True))
        status = _norm(tds[4].get_text(" ", strip=True)) if len(tds) >= 5 else ""
        events.append(
            {
                "classCd": class_cd,
                "toCd": to_cd,
                "searchAppYn": search_app_yn,
                "대회명": event_name,
                "장소": place,
                "기간": period,
                "상태": status,
                "pageIndex": page_index,
            }
        )
    return events


def _parse_inf301_kind_options_html(html):
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", attrs={"id": "searchKindCd"})
    if not select:
        return []
    kinds = []
    seen = set()
    for option in select.find_all("option"):
        kind_cd = _norm(option.get("value"))
        if not kind_cd or kind_cd in seen:
            continue
        if not KIND_CD_RE.fullmatch(kind_cd):
            continue
        seen.add(kind_cd)
        kinds.append({"kindCd": kind_cd, "kindNm": _norm(option.get_text(" ", strip=True))})
    return kinds


def _parse_detail_class_list_json(raw_text, kind_cd, kind_nm):
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    rows = payload.get("LIST")
    if not isinstance(rows, list):
        return []
    details = []
    for row in rows:
        detail_class_cd = _norm(row.get("DETAIL_CLASS_CD"))
        if not detail_class_cd:
            continue
        details.append(
            {
                "kindCd": _norm(kind_cd),
                "종별": _norm(kind_nm),
                "detailClassCd": detail_class_cd,
                "세부종목": _norm(row.get("DETAIL_CLASS_NM")),
                "firstDetailClassCd": _norm(row.get("FIRST_DCLASS_CD")),
            }
        )
    return details


def _parse_inf301_result_calls_html(html):
    soup = BeautifulSoup(html, "html.parser")
    calls = []
    seen = set()
    for node in soup.find_all(attrs={"onclick": True}):
        args = _parse_js_args(node.get("onclick", ""), "fnEventResult")
        if not args or len(args) < 6:
            continue
        item = {
            "useGbn": _norm(args[0]),
            "pcntGbn": _norm(args[1]),
            "baseClassCd": _norm(args[2]),
            "rhCd": _norm(args[3]),
            "rhNm": _norm(args[4]),
            "baseClassNm": _norm(args[5]),
        }
        key = tuple(item.values())
        if key in seen:
            continue
        seen.add(key)
        calls.append(item)
    return calls


def _is_relay_context(detail_class_cd, detail_name, calls):
    if _norm(detail_class_cd).endswith("07"):
        return True
    name = _norm(detail_name)
    if "릴레이" in name or "RELAY" in name.upper():
        return True
    for call in calls:
        if _norm(call.get("pcntGbn")).upper() == "T":
            return True
        if _norm(call.get("baseClassCd")) == "07":
            return True
    return False


def _classify_inf301_empty_calls(html_301):
    soup = BeautifulSoup(html_301 or "", "html.parser")
    full_text = soup.get_text(" ", strip=True)
    has_no_schedule = "조회된 일정이 없습니다" in full_text
    raw_onclick_calls = 0
    parsed_onclick_calls = 0
    for node in soup.find_all(attrs={"onclick": True}):
        onclick = _norm(node.get("onclick"))
        if "fnEventResult(" in onclick:
            raw_onclick_calls += 1
        if _parse_js_args(onclick, "fnEventResult"):
            parsed_onclick_calls += 1
    gm_options = []
    gm_select = soup.find("select", attrs={"id": "searchGmDt"})
    if gm_select:
        for option in gm_select.find_all("option"):
            value = _norm(option.get("value"))
            if value:
                gm_options.append(value)

    if raw_onclick_calls > 0 and parsed_onclick_calls <= 0:
        return "parser_mismatch", f"fnEventResult_raw={raw_onclick_calls} parsed=0 gm_options={len(gm_options)}"
    if has_no_schedule:
        return "no_schedule_rows", f"gm_options={len(gm_options)}"
    return "calls_empty_unknown", f"fnEventResult_raw={raw_onclick_calls} parsed={parsed_onclick_calls} gm_options={len(gm_options)}"


def _parse_inf310_rows_html(html, result_call, *, context=None, suspicious_rows=None):
    context = context or {}
    suspicious_rows = suspicious_rows if suspicious_rows is not None else []
    soup = BeautifulSoup(html, "html.parser")
    table = _find_table_by_caption(soup, "경기결과")
    if not table:
        return {
            "rows": [],
            "stats": {
                "table_found": False,
                "header_detected": False,
                "data_row_count": 0,
                "category_row_count": 0,
                "row_with_participant_count": 0,
                "row_without_participant_count": 0,
                "row_without_participant_likely_result_count": 0,
                "participant_entry_count": 0,
                "suspicious_id_count": 0,
            },
        }

    headers = _extract_result_headers(table)
    header_detected = bool(headers)
    if not header_detected:
        print(
            "[warn] INF310 헤더 미감지: classCd={0} toCd={1} kindCd={2} detailClassCd={3} rhCd={4} pcntGbn={5}".format(
                _norm(context.get("classCd")),
                _norm(context.get("toCd")),
                _norm(context.get("kindCd")),
                _norm(context.get("detailClassCd")),
                _norm(result_call.get("rhCd")),
                _norm(result_call.get("pcntGbn")) or "-",
            )
        )
    rows = []
    seen = set()
    suspicious_ids = set()

    current_round = _norm(result_call.get("rhNm"))
    current_category = ""
    data_row_count = 0
    category_row_count = 0
    row_with_participant_count = 0
    row_without_participant_count = 0
    row_without_participant_likely_result_count = 0
    participant_entry_count = 0
    allow_non_numeric_ids = _is_relay_context(
        context.get("detailClassCd"),
        context.get("detailName"),
        [result_call],
    )

    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        if len(ths) == 1 and ths[0].get("colspan"):
            round_label = _norm(ths[0].get_text(" ", strip=True))
            if round_label:
                current_round = round_label
            continue

        tds = tr.find_all("td")
        if not tds:
            continue
        if len(tds) == 1 and tds[0].get("colspan"):
            category_label = _norm(tds[0].get_text(" ", strip=True))
            if category_label:
                current_category = category_label
            category_row_count += 1
            continue

        data_row_count += 1
        values = [_norm(td.get_text(" ", strip=True)) for td in tds]
        row_map = {}
        for idx, value in enumerate(values):
            key = headers[idx] if idx < len(headers) and headers[idx] else f"col{idx}"
            row_map[key] = value

        rank = _norm(row_map.get("순위"))
        bib = _norm(row_map.get("BIB"))
        lane = _norm(row_map.get("레인"))
        grade = _norm(row_map.get("학년"))
        record = _norm(row_map.get("기록"))
        reason = _norm(row_map.get("사유"))
        record_gap = _norm(row_map.get("기록차"))
        affiliation = _norm(row_map.get("소속"))
        row_name = _norm(row_map.get("성명") or row_map.get("선수명") or row_map.get("팀명"))

        def invalid_id_sink(raw_id, raw_source, source_label):
            row = {
                "classCd": _norm(context.get("classCd")),
                "toCd": _norm(context.get("toCd")),
                "대회명": _norm(context.get("대회명")),
                "kindCd": _norm(context.get("kindCd")),
                "detailClassCd": _norm(context.get("detailClassCd")),
                "baseClassCd": _norm(result_call.get("baseClassCd")),
                "rhCd": _norm(result_call.get("rhCd")),
                "pcntGbn": _norm(result_call.get("pcntGbn")),
                "idNo_원본": _norm(raw_id),
                "추출소스": _norm(raw_source),
                "행대표이름": _norm(source_label) or row_name,
            }
            key = (row["classCd"], row["toCd"], row["kindCd"], row["detailClassCd"], row["baseClassCd"], row["rhCd"], row["idNo_원본"], row["추출소스"])
            if key in suspicious_ids:
                return
            suspicious_ids.add(key)
            suspicious_rows.append(row)

        participants = _extract_participant_entries(
            tr,
            row_map,
            invalid_id_sink=invalid_id_sink,
            allow_non_numeric_ids=allow_non_numeric_ids,
        )
        if not participants:
            row_without_participant_count += 1
            if rank or record or row_name:
                row_without_participant_likely_result_count += 1
            continue

        row_with_participant_count += 1
        participant_entry_count += len(participants)
        for participant in participants:
            id_no = _norm(participant.get("idNo"))
            participant_name = _norm(participant.get("name")) or row_name
            if not id_no:
                continue
            unique_key = (
                id_no,
                participant_name,
                current_round,
                current_category,
                rank,
                record,
                result_call.get("baseClassCd", ""),
                result_call.get("rhCd", ""),
            )
            if unique_key in seen:
                continue
            seen.add(unique_key)
            rows.append(
                {
                    "idNo": id_no,
                    "이름": participant_name,
                    "소속": affiliation,
                    "종별구분": current_category,
                    "라운드": current_round,
                    "순위": rank,
                    "기록": record,
                    "학년": grade,
                    "레인": lane,
                    "BIB": bib,
                    "사유": reason,
                    "기록차": record_gap,
                }
            )

    return {
        "rows": rows,
        "stats": {
            "table_found": True,
            "header_detected": header_detected,
            "data_row_count": data_row_count,
            "category_row_count": category_row_count,
            "row_with_participant_count": row_with_participant_count,
            "row_without_participant_count": row_without_participant_count,
            "row_without_participant_likely_result_count": row_without_participant_likely_result_count,
            "participant_entry_count": participant_entry_count,
            "suspicious_id_count": len(suspicious_ids),
        },
    }


def _collect_inf201_events(session, refresh, request_gap_seconds, progress, failures, max_pages=None):
    events = []
    page_limit = int(max_pages) if max_pages is not None else 200
    page = 1
    while True:
        if page > page_limit:
            break
        cache_path = _cache_path_inf201(page)
        payload = _base_payload()
        payload["pageIndex"] = str(page)
        request_key = f"inf201:{page}"
        html, _, _ = _fetch_with_cache(
            session,
            request_type="inf201",
            request_key=request_key,
            endpoint=INF201_ENDPOINT,
            payload=payload,
            cache_path=cache_path,
            context=f"page={page}",
            refresh=refresh,
            request_gap_seconds=request_gap_seconds,
            progress=progress,
            failures=failures,
        )
        _bump_counter(progress, "inf201_pages_parsed")
        _save_progress(progress)
        if html is None:
            page += 1
            continue
        page_events = _parse_inf201_events_html(html, page_index=page)
        if not page_events:
            break
        events.extend(page_events)
        page += 1

    dedup = {}
    for event in events:
        key = (_norm(event.get("classCd")), _norm(event.get("toCd")))
        if key[0] and key[1]:
            dedup[key] = event
    merged = [dedup[key] for key in sorted(dedup.keys())]
    class2 = [event for event in merged if _norm(event.get("classCd")) == "2"]
    _bump_counter(progress, "inf201_events_total", len(merged))
    _bump_counter(progress, "inf201_events_class2", len(class2))
    _save_progress(progress)
    return class2


def _collect_event_route(
    session,
    events,
    refresh,
    request_gap_seconds,
    progress,
    failures,
    meet_failures,
):
    _ = meet_failures
    total_events = len(events)
    seen_inf310 = set()
    _seed_meet_progress(progress, events)

    for idx, event in enumerate(events, start=1):
        class_cd = _norm(event.get("classCd"))
        to_cd = _norm(event.get("toCd"))
        search_app_yn = _norm(event.get("searchAppYn"))
        event_name = _norm(event.get("대회명"))
        print(f"[event {idx}/{total_events}] classCd={class_cd} toCd={to_cd} | {event_name}")
        _set_meet_status(progress, event, "in_progress", stage="start")
        event_inf310_calls = 0

        payload_kind = _base_payload()
        payload_kind.update({"classCd": class_cd, "toCd": to_cd, "searchAppYn": search_app_yn})
        html_kind, _, reason = _fetch_with_cache(
            session,
            request_type="inf301_kind",
            request_key=f"inf301-kind:{class_cd}:{to_cd}",
            endpoint=INF301_ENDPOINT,
            payload=payload_kind,
            cache_path=_cache_path_inf301_kind(class_cd, to_cd),
            context=f"classCd={class_cd} toCd={to_cd}",
            refresh=refresh,
            request_gap_seconds=request_gap_seconds,
            progress=progress,
            failures=failures,
        )
        _bump_counter(progress, "inf301_kind_requests")
        _save_progress(progress)
        if html_kind is None:
            _set_meet_status(progress, event, "in_progress", stage="inf301_kind_fetch_failed", error=reason or "kind_fetch_failed")
            continue

        kind_items = _parse_inf301_kind_options_html(html_kind)
        if not kind_items:
            _set_meet_status(progress, event, "in_progress", stage="inf301_kind_parse_empty", error="kind_options_empty")
            continue
        dropdown_kind_codes = sorted({_norm(item.get("kindCd")) for item in kind_items if _norm(item.get("kindCd"))})
        requested_kind_codes = set()

        for kind_item in kind_items:
            kind_cd = _norm(kind_item.get("kindCd"))
            kind_nm = _norm(kind_item.get("kindNm"))
            requested_kind_codes.add(kind_cd)
            payload_ajax = {"classCd": class_cd, "toCd": to_cd, "kindCd": kind_cd}
            ajax_text, _, ajax_reason = _fetch_with_cache(
                session,
                request_type="detail_class_ajax",
                request_key=f"detail-ajax:{class_cd}:{to_cd}:{kind_cd}",
                endpoint=DETAIL_CLASS_AJAX_ENDPOINT,
                payload=payload_ajax,
                cache_path=_cache_path_detail_class_ajax(class_cd, to_cd, kind_cd),
                context=f"classCd={class_cd} toCd={to_cd} kindCd={kind_cd}",
                refresh=refresh,
                request_gap_seconds=request_gap_seconds,
                progress=progress,
                failures=failures,
                headers=JSON_HEADERS,
                json_body=True,
            )
            _bump_counter(progress, "detail_class_ajax_requests")
            _save_progress(progress)
            if ajax_text is None:
                print(f"[warn] detail_class_ajax fetch 실패: toCd={to_cd} kindCd={kind_cd} reason={ajax_reason or 'unknown'}")
                continue
            details = _parse_detail_class_list_json(ajax_text, kind_cd=kind_cd, kind_nm=kind_nm)
            if not details:
                print(f"[info] detail_class_ajax LIST 비어있음: toCd={to_cd} kindCd={kind_cd} (요청 스킵)")
                continue

            for detail in details:
                detail_class_cd = _norm(detail.get("detailClassCd"))
                payload_301 = _base_payload()
                payload_301.update(
                    {
                        "classCd": class_cd,
                        "toCd": to_cd,
                        "searchAppYn": search_app_yn,
                        "kindCd": kind_cd,
                        "detailClassCd": detail_class_cd,
                        "searchKindCd": kind_cd,
                        "searchDetailClassCd": detail_class_cd,
                    }
                )
                html_301, _, reason_301 = _fetch_with_cache(
                    session,
                    request_type="inf301",
                    request_key=f"inf301:{to_cd}:{kind_cd}:{detail_class_cd}",
                    endpoint=INF301_ENDPOINT,
                    payload=payload_301,
                    cache_path=_cache_path_inf301(class_cd, to_cd, kind_cd, detail_class_cd),
                    context=f"toCd={to_cd} kindCd={kind_cd} detailClassCd={detail_class_cd}",
                    refresh=refresh,
                    request_gap_seconds=request_gap_seconds,
                    progress=progress,
                    failures=failures,
                )
                _bump_counter(progress, "inf301_requests")
                _save_progress(progress)
                if html_301 is None:
                    print(
                        f"[warn] INF301 fetch 실패: toCd={to_cd} kindCd={kind_cd} detailClassCd={detail_class_cd} reason={reason_301 or 'unknown'}"
                    )
                    continue

                calls = _parse_inf301_result_calls_html(html_301)
                if not calls:
                    empty_stage, empty_reason = _classify_inf301_empty_calls(html_301)
                    print(
                        "[warn] INF301 result call 없음: toCd={0} kindCd={1} detailClassCd={2} stage={3} reason={4}".format(
                            to_cd,
                            kind_cd,
                            detail_class_cd,
                            empty_stage,
                            empty_reason,
                        )
                    )
                    continue

                for call in calls:
                    base_class_cd = _norm(call.get("baseClassCd"))
                    rh_cd = _norm(call.get("rhCd"))
                    pcnt_gbn = _norm(call.get("pcntGbn")) or "-"
                    use_gbn = _norm(call.get("useGbn"))
                    call_key = (to_cd, kind_cd, detail_class_cd, base_class_cd, rh_cd, pcnt_gbn, use_gbn)
                    if call_key in seen_inf310:
                        continue
                    seen_inf310.add(call_key)

                    payload_310 = _base_payload()
                    payload_310.update(
                        {
                            "classCd": class_cd,
                            "toCd": to_cd,
                            "searchAppYn": search_app_yn,
                            "kindCd": kind_cd,
                            "detailClassCd": detail_class_cd,
                            "searchKindCd": kind_cd,
                            "searchDetailClassCd": detail_class_cd,
                            "baseClassCd": base_class_cd,
                            "rhCd": rh_cd,
                            "rhNm": _norm(call.get("rhNm")),
                            "baseClassNm": _norm(call.get("baseClassNm")),
                            "pcntGbn": _norm(call.get("pcntGbn")),
                            "useGbn": use_gbn,
                        }
                    )
                    _, _, reason_310 = _fetch_with_cache(
                        session,
                        request_type="inf310",
                        request_key=f"inf310:{to_cd}:{kind_cd}:{detail_class_cd}:{base_class_cd}:{rh_cd}:{pcnt_gbn}:{use_gbn or '-'}",
                        endpoint=INF310_ENDPOINT,
                        payload=payload_310,
                        cache_path=_cache_path_inf310(
                            class_cd=class_cd,
                            to_cd=to_cd,
                            kind_cd=kind_cd,
                            detail_class_cd=detail_class_cd,
                            base_class_cd=base_class_cd,
                            rh_cd=rh_cd,
                            pcnt_gbn=pcnt_gbn,
                        ),
                        context=f"toCd={to_cd} kindCd={kind_cd} detailClassCd={detail_class_cd} baseClassCd={base_class_cd} rhCd={rh_cd} pcntGbn={pcnt_gbn}",
                        refresh=refresh,
                        request_gap_seconds=request_gap_seconds,
                        progress=progress,
                        failures=failures,
                    )
                    _bump_counter(progress, "inf310_requests")
                    _save_progress(progress)
                    if reason_310:
                        print(
                            f"[warn] INF310 fetch 실패: toCd={to_cd} kindCd={kind_cd} detailClassCd={detail_class_cd} baseClassCd={base_class_cd} rhCd={rh_cd} reason={reason_310}"
                        )
                        continue
                    event_inf310_calls += 1
        requested_kind_codes_sorted = sorted(requested_kind_codes)
        extra_requested = sorted(set(requested_kind_codes_sorted) - set(dropdown_kind_codes))
        subset_ok = len(extra_requested) == 0
        print(f"[event {idx}/{total_events}] toCd={to_cd}")
        print(f" 드롭다운 kindCd: {','.join(dropdown_kind_codes)} ({len(dropdown_kind_codes)}개)")
        print(f" 요청 kindCd: {','.join(requested_kind_codes_sorted)} ({len(requested_kind_codes_sorted)}개)")
        print(f" 집합 일치: {'OK' if subset_ok else 'MISMATCH'}")
        if not subset_ok:
            print(f"[warn] 요청 kindCd가 드롭다운 밖 값 포함: toCd={to_cd} extra={','.join(extra_requested)}")

        if event_inf310_calls <= 0:
            _set_meet_status(progress, event, "in_progress", stage="inf310_calls_empty", error="no_inf310_calls")
            continue
        _set_meet_status(progress, event, "done", stage="fetch_completed")

    return meet_failures


def _load_events_from_inf201_cache():
    events = []
    for path in sorted(RAW_INF201_DIR.glob("*.html")):
        try:
            page_index = int(path.stem)
        except ValueError:
            page_index = 0
        html = path.read_text(encoding="utf-8")
        events.extend(_parse_inf201_events_html(html, page_index=page_index))
    dedup = {}
    for event in events:
        key = (_norm(event.get("classCd")), _norm(event.get("toCd")))
        if key[0] == "2" and key[1]:
            dedup[key] = event
    return [dedup[key] for key in sorted(dedup.keys())]


def _infer_gender(categories):
    has_male = any("남자" in _norm(cat) for cat in categories)
    has_female = any("여자" in _norm(cat) for cat in categories)
    if has_male and not has_female:
        return "남"
    if has_female and not has_male:
        return "여"
    return ""


def _build_base_records(events):
    records = []
    seen_records = set()
    seen_inf310_cache = set()
    id_seed = {}
    winter_ids = set()
    to_cd_by_meet = {}
    suspicious_rows = []
    detail_failures = []
    event_status_rows = []
    parse_stats = {
        "events_total": len(events),
        "events_winter": 0,
        "kind_count": 0,
        "detail_class_count": 0,
        "inf301_call_count": 0,
        "inf310_call_count": 0,
        "inf310_table_missing_call_count": 0,
        "inf310_header_missing_call_count": 0,
        "inf310_data_row_count": 0,
        "inf310_category_row_count": 0,
        "inf310_row_without_participant_count": 0,
        "inf310_row_without_participant_likely_result_count": 0,
        "inf310_participant_entry_count": 0,
        "inf310_suspicious_id_count": 0,
        "inf310_zero_participant_detail_count": 0,
        "inf310_zero_participant_relay_warning_count": 0,
        "detail_success_count": 0,
        "detail_failure_count": 0,
        "detail_warning_count": 0,
        "event_complete_count": 0,
        "event_partial_count": 0,
        "event_failed_count": 0,
        "inf301_no_schedule_detail_count": 0,
        "inf301_parser_mismatch_detail_count": 0,
    }

    for event in events:
        class_cd = _norm(event.get("classCd"))
        to_cd = _norm(event.get("toCd"))
        event_name = _norm(event.get("대회명"))
        event_records_before = len(records)
        event_detail_total = 0
        event_detail_failed = 0
        event_detail_warned = 0
        first_failure_stage = ""
        first_failure_reason = ""
        first_warning_stage = ""
        first_warning_reason = ""

        def add_detail_failure(kind_cd, detail_class_cd, detail_category, detail_name, stage, reason):
            nonlocal event_detail_failed, first_failure_stage, first_failure_reason
            parse_stats["detail_failure_count"] += 1
            event_detail_failed += 1
            if not first_failure_stage:
                first_failure_stage = _norm(stage)
                first_failure_reason = _norm(reason)
            detail_failures.append(
                {
                    "classCd": class_cd,
                    "toCd": to_cd,
                    "kindCd": _norm(kind_cd),
                    "detailClassCd": _norm(detail_class_cd),
                    "실패단계": _norm(stage),
                    "단계": _norm(stage),
                    "사유": _norm(reason),
                    "대회명": event_name,
                    "종별": _norm(detail_category),
                    "세부종목": _norm(detail_name),
                    "심각도": "fail",
                    "최종시각": _now_iso(),
                }
            )

        def add_detail_warning(kind_cd, detail_class_cd, detail_category, detail_name, stage, reason):
            nonlocal event_detail_warned, first_warning_stage, first_warning_reason
            parse_stats["detail_warning_count"] += 1
            event_detail_warned += 1
            if not first_warning_stage:
                first_warning_stage = _norm(stage)
                first_warning_reason = _norm(reason)
            detail_failures.append(
                {
                    "classCd": class_cd,
                    "toCd": to_cd,
                    "kindCd": _norm(kind_cd),
                    "detailClassCd": _norm(detail_class_cd),
                    "실패단계": _norm(stage),
                    "단계": _norm(stage),
                    "사유": _norm(reason),
                    "대회명": event_name,
                    "종별": _norm(detail_category),
                    "세부종목": _norm(detail_name),
                    "심각도": "warn",
                    "최종시각": _now_iso(),
                }
            )

        is_winter = "동계체" in event_name
        if is_winter:
            parse_stats["events_winter"] += 1
        if event_name:
            to_cd_by_meet.setdefault(event_name, set()).add(to_cd)
        _, event_date_norm = _extract_event_date(event)
        cache_kind = _cache_path_inf301_kind(class_cd, to_cd)
        if not cache_kind.exists():
            legacy_kind = _legacy_cache_path_inf301_kind(to_cd)
            if legacy_kind.exists():
                cache_kind = legacy_kind
        if not cache_kind.exists():
            add_detail_failure("", "", "", "", "inf301_kind_cache_missing", "INF301 kind 캐시 없음")
            event_status_rows.append(
                {
                    "classCd": class_cd,
                    "toCd": to_cd,
                    "대회명": event_name,
                    "event_status": "실패",
                    "세부종목수": "0",
                    "성공세부종목수": "0",
                    "실패세부종목수": "1",
                    "경고세부종목수": "0",
                    "대표실패단계": "inf301_kind_cache_missing",
                    "대표사유": "INF301 kind 캐시 없음",
                }
            )
            parse_stats["event_failed_count"] += 1
            continue

        kind_items = _parse_inf301_kind_options_html(cache_kind.read_text(encoding="utf-8"))
        if not kind_items:
            add_detail_failure("", "", "", "", "inf301_kind_parse", "INF301 kind 옵션 미감지")
            event_status_rows.append(
                {
                    "classCd": class_cd,
                    "toCd": to_cd,
                    "대회명": event_name,
                    "event_status": "실패",
                    "세부종목수": "0",
                    "성공세부종목수": "0",
                    "실패세부종목수": "1",
                    "경고세부종목수": "0",
                    "대표실패단계": "inf301_kind_parse",
                    "대표사유": "INF301 kind 옵션 미감지",
                }
            )
            parse_stats["event_failed_count"] += 1
            continue
        parse_stats["kind_count"] += len(kind_items)

        for kind_item in kind_items:
            kind_cd = _norm(kind_item.get("kindCd"))
            kind_nm = _norm(kind_item.get("kindNm"))
            cache_detail = _cache_path_detail_class_ajax(class_cd, to_cd, kind_cd)
            if not cache_detail.exists():
                add_detail_failure(kind_cd, "", kind_nm, "", "detail_class_cache_missing", f"kindCd={kind_cd}")
                continue

            details = _parse_detail_class_list_json(cache_detail.read_text(encoding="utf-8"), kind_cd=kind_cd, kind_nm=kind_nm)
            if not details:
                print(f"[info] detail_class_ajax LIST 비어있음(export): toCd={to_cd} kindCd={kind_cd} (정상 스킵)")
                continue
            parse_stats["detail_class_count"] += len(details)

            for detail in details:
                detail_class_cd = _norm(detail.get("detailClassCd"))
                detail_category = _norm(detail.get("종별"))
                detail_name_seed = _norm(detail.get("세부종목"))
                event_detail_total += 1
                detail_participant_rows = 0

                cache_301 = _cache_path_inf301(class_cd, to_cd, kind_cd, detail_class_cd)
                if not cache_301.exists():
                    legacy_301 = _legacy_cache_path_inf301(to_cd, kind_cd, detail_class_cd)
                    if legacy_301.exists():
                        cache_301 = legacy_301
                if not cache_301.exists():
                    add_detail_failure(
                        kind_cd,
                        detail_class_cd,
                        detail_category,
                        detail_name_seed,
                        "inf301_detail_cache_missing",
                        f"kindCd={kind_cd} detailClassCd={detail_class_cd}",
                    )
                    continue
                html_301 = cache_301.read_text(encoding="utf-8")
                calls = _parse_inf301_result_calls_html(html_301)
                parse_stats["inf301_call_count"] += len(calls)
                if not calls:
                    reason_code, reason_detail = _classify_inf301_empty_calls(html_301)
                    if reason_code == "no_schedule_rows":
                        parse_stats["inf301_no_schedule_detail_count"] += 1
                        add_detail_warning(
                            kind_cd,
                            detail_class_cd,
                            detail_category,
                            detail_name_seed,
                            "inf301_result_call_parse",
                            f"kindCd={kind_cd} detailClassCd={detail_class_cd} code={reason_code} {reason_detail}",
                        )
                    elif reason_code == "parser_mismatch":
                        parse_stats["inf301_parser_mismatch_detail_count"] += 1
                        add_detail_failure(
                            kind_cd,
                            detail_class_cd,
                            detail_category,
                            detail_name_seed,
                            "inf301_result_call_parse_unexpected",
                            f"kindCd={kind_cd} detailClassCd={detail_class_cd} code={reason_code} {reason_detail}",
                        )
                    else:
                        add_detail_failure(
                            kind_cd,
                            detail_class_cd,
                            detail_category,
                            detail_name_seed,
                            "inf301_result_call_parse_unexpected",
                            f"kindCd={kind_cd} detailClassCd={detail_class_cd} code={reason_code} {reason_detail}",
                        )
                    continue

                is_relay_detail = _is_relay_context(detail_class_cd, detail_name_seed, calls)
                detail_cache_missing = False
                for call in calls:
                    pcnt_gbn = _norm(call.get("pcntGbn")) or "-"
                    cache_310 = _cache_path_inf310(
                        class_cd=class_cd,
                        to_cd=to_cd,
                        kind_cd=kind_cd,
                        detail_class_cd=detail_class_cd,
                        base_class_cd=_norm(call.get("baseClassCd")),
                        rh_cd=_norm(call.get("rhCd")),
                        pcnt_gbn=pcnt_gbn,
                    )
                    if not cache_310.exists():
                        legacy_310 = _legacy_cache_path_inf310(
                            to_cd=to_cd,
                            kind_cd=kind_cd,
                            detail_class_cd=detail_class_cd,
                            base_class_cd=_norm(call.get("baseClassCd")),
                            rh_cd=_norm(call.get("rhCd")),
                            pcnt_gbn=pcnt_gbn,
                        )
                        if legacy_310.exists():
                            cache_310 = legacy_310
                    if not cache_310.exists():
                        detail_cache_missing = True
                        continue
                    cache_key = str(cache_310)
                    if cache_key in seen_inf310_cache:
                        continue
                    seen_inf310_cache.add(cache_key)
                    inf310 = _parse_inf310_rows_html(
                        cache_310.read_text(encoding="utf-8"),
                        call,
                        context={
                            "classCd": class_cd,
                            "toCd": to_cd,
                            "대회명": event_name,
                            "kindCd": kind_cd,
                            "detailClassCd": detail_class_cd,
                            "detailName": detail_name_seed,
                        },
                        suspicious_rows=suspicious_rows,
                    )
                    rows = inf310["rows"]
                    stats = inf310["stats"]
                    parse_stats["inf310_call_count"] += 1
                    if not stats.get("table_found", True):
                        parse_stats["inf310_table_missing_call_count"] += 1
                    elif not stats["header_detected"]:
                        parse_stats["inf310_header_missing_call_count"] += 1
                    parse_stats["inf310_data_row_count"] += stats["data_row_count"]
                    parse_stats["inf310_category_row_count"] += stats["category_row_count"]
                    parse_stats["inf310_row_without_participant_count"] += stats["row_without_participant_count"]
                    parse_stats["inf310_row_without_participant_likely_result_count"] += stats["row_without_participant_likely_result_count"]
                    parse_stats["inf310_participant_entry_count"] += stats["participant_entry_count"]
                    parse_stats["inf310_suspicious_id_count"] += stats.get("suspicious_id_count", 0)

                    detail_name = detail_name_seed or _norm(call.get("baseClassNm"))
                    for row in rows:
                        record_key = _record_identity_key(
                            _norm(row.get("idNo")),
                            event_name,
                            detail_name,
                            _norm(row.get("라운드")),
                            _norm(row.get("순위")),
                            _norm(row.get("기록")),
                        )
                        if not record_key[0]:
                            continue
                        if record_key in seen_records:
                            continue
                        seen_records.add(record_key)
                        detail_participant_rows += 1
                        records.append(
                            {
                                "idNo": _norm(row.get("idNo")),
                                "대회명": event_name,
                                "일자": event_date_norm,
                                "일자_정규화": event_date_norm,
                                "종별": detail_category,
                                "세부종목": detail_name,
                                "라운드": _norm(row.get("라운드")),
                                "소속": _norm(row.get("소속")),
                                "기록": _norm(row.get("기록")),
                                "순위": _norm(row.get("순위")),
                                "학년": _norm(row.get("학년")),
                                "레인": _norm(row.get("레인")),
                                "BIB": _norm(row.get("BIB")),
                                "사유": _norm(row.get("사유")),
                                "기록차": _norm(row.get("기록차")),
                                "classCd": class_cd,
                                "toCd": to_cd,
                                "kindCd": kind_cd,
                                "detailClassCd": detail_class_cd,
                                "baseClassCd": _norm(call.get("baseClassCd")),
                                "rhCd": _norm(call.get("rhCd")),
                                "pcntGbn": pcnt_gbn,
                                "소스": "INF310",
                                "source": "event",
                            }
                        )
                        item = id_seed.setdefault(
                            _norm(row.get("idNo")),
                            {"이름": "", "종별목록": set(), "소속목록": set(), "성별": ""},
                        )
                        name = _norm(row.get("이름"))
                        if name and not item["이름"]:
                            item["이름"] = name
                        if detail_category:
                            item["종별목록"].add(detail_category)
                        affiliation = _norm(row.get("소속"))
                        if affiliation:
                            item["소속목록"].add(affiliation)
                        if is_winter:
                            winter_ids.add(_norm(row.get("idNo")))

                if detail_cache_missing:
                    add_detail_failure(
                        kind_cd,
                        detail_class_cd,
                        detail_category,
                        detail_name_seed,
                        "inf310_cache_missing",
                        f"kindCd={kind_cd} detailClassCd={detail_class_cd}",
                    )
                    continue

                if detail_participant_rows <= 0:
                    if is_relay_detail:
                        parse_stats["inf310_zero_participant_relay_warning_count"] += 1
                        add_detail_warning(
                            kind_cd,
                            detail_class_cd,
                            detail_category,
                            detail_name_seed,
                            "inf310_zero_participant",
                            f"kindCd={kind_cd} detailClassCd={detail_class_cd}",
                        )
                        print(
                            f"[warn] 계주 세부종목 참가자 0건(실패 미판정): toCd={to_cd} kindCd={kind_cd} detailClassCd={detail_class_cd}"
                        )
                        parse_stats["detail_success_count"] += 1
                        continue
                    parse_stats["inf310_zero_participant_detail_count"] += 1
                    add_detail_failure(
                        kind_cd,
                        detail_class_cd,
                        detail_category,
                        detail_name_seed,
                        "inf310_zero_participant_unexpected",
                        f"kindCd={kind_cd} detailClassCd={detail_class_cd}",
                    )
                    continue
                parse_stats["detail_success_count"] += 1

        event_record_delta = len(records) - event_records_before
        event_success_details = max(0, event_detail_total - event_detail_failed)
        if event_record_delta > 0:
            if event_detail_failed > 0:
                event_status = "부분완료"
                parse_stats["event_partial_count"] += 1
            else:
                event_status = "완료"
                parse_stats["event_complete_count"] += 1
        else:
            if event_detail_warned > 0 and event_detail_failed <= 0:
                event_status = "부분완료"
                parse_stats["event_partial_count"] += 1
            else:
                event_status = "실패"
                parse_stats["event_failed_count"] += 1

        summary_stage = first_failure_stage or first_warning_stage
        summary_reason = first_failure_reason or first_warning_reason
        event_status_rows.append(
            {
                "classCd": class_cd,
                "toCd": to_cd,
                "대회명": event_name,
                "event_status": event_status,
                "세부종목수": str(event_detail_total),
                "성공세부종목수": str(event_success_details),
                "실패세부종목수": str(event_detail_failed),
                "경고세부종목수": str(event_detail_warned),
                "대표실패단계": _norm(summary_stage),
                "대표사유": _norm(summary_reason),
            }
        )

    for id_no, item in id_seed.items():
        if not item["성별"]:
            item["성별"] = _infer_gender(item["종별목록"])
        item["종별목록"] = sorted(item["종별목록"])
        item["소속목록"] = sorted(item["소속목록"])

    to_cd_final = {}
    for meet_name, values in to_cd_by_meet.items():
        to_cd_final[meet_name] = next(iter(values)) if len(values) == 1 else ""
    event_status_rows = sorted(event_status_rows, key=lambda r: (_norm(r.get("classCd")), _norm(r.get("toCd"))))
    return records, id_seed, sorted(winter_ids), to_cd_final, parse_stats, suspicious_rows, detail_failures, event_status_rows


def _collect_inf503_for_ids(session, id_list, refresh, request_gap_seconds, progress, failures):
    total = len(id_list)
    print(f"[inf503] 대상 {total}명")
    for idx, id_no in enumerate(id_list, start=1):
        payload = {"pclassCd": "SK", "idNo": id_no, "pageIndex": "1"}
        html, _, _ = _fetch_with_cache(
            session,
            request_type="inf503",
            request_key=f"inf503:{id_no}",
            endpoint=INF503_ENDPOINT,
            payload=payload,
            cache_path=_cache_path_inf503(id_no),
            context=f"idNo={id_no} ({idx}/{total})",
            refresh=refresh,
            request_gap_seconds=request_gap_seconds,
            progress=progress,
            failures=failures,
        )
        _bump_counter(progress, "inf503_requests")
        _save_progress(progress)
        if html is None:
            continue


def _build_athlete_info_and_score_supplement(id_seed, to_cd_by_meet):
    athlete_rows = []
    supplement_rows = []
    supplement_seen = set()
    birth_year_ok = 0
    inf503_cache_missing = 0

    for id_no in sorted(id_seed.keys()):
        seed = id_seed.get(id_no, {})
        cache = _cache_path_inf503(id_no)
        if cache.exists():
            html = cache.read_text(encoding="utf-8")
            info = parse_athlete_info(html)
        else:
            html = ""
            info = {}
            inf503_cache_missing += 1

        name = _norm(info.get("이름")) or _norm(seed.get("이름"))
        gender = _norm(info.get("성별")) or _norm(seed.get("성별"))
        birth_year = _norm(info.get("출생년도"))
        if birth_year:
            birth_year_ok += 1
        athlete_rows.append(
            {
                "idNo": id_no,
                "이름": name,
                "성별": gender,
                "출생년도": birth_year,
                "종별": _norm(info.get("종별")),
                "소속팀": _norm(info.get("소속팀")),
                "팀코드": _norm(info.get("팀코드")),
                "시도": _norm(info.get("시도")),
            }
        )

        if not html:
            continue
        for row in parse_history(html, id_no):
            meet_name = _norm(row.get("대회명"))
            round_name = _norm(row.get("라운드"))
            date_raw = _norm(row.get("일자"))
            date_norm = _normalize_date_text(_norm(row.get("일자_정규화")) or date_raw)
            key = _record_identity_key(
                id_no,
                meet_name,
                _norm(row.get("세부종목")),
                round_name,
                _norm(row.get("순위")),
                _norm(row.get("기록")),
            )
            if key in supplement_seen:
                continue
            supplement_seen.add(key)
            supplement_rows.append(
                {
                    "idNo": id_no,
                    "대회명": meet_name,
                    "일자": date_raw,
                    "일자_정규화": date_norm,
                    "종별": _norm(row.get("종별")),
                    "세부종목": _norm(row.get("세부종목")),
                    "라운드": round_name,
                    "소속": _norm(row.get("소속")),
                    "기록": _norm(row.get("기록")),
                    "순위": _norm(row.get("순위")),
                    "학년": "",
                    "레인": "",
                    "BIB": "",
                    "사유": "",
                    "기록차": "",
                    "classCd": "2",
                    "toCd": _norm(to_cd_by_meet.get(meet_name)),
                    "kindCd": "",
                    "detailClassCd": "",
                    "baseClassCd": "",
                    "rhCd": "",
                    "pcntGbn": "I",
                    "소스": "INF503_SCORE",
                    "source": "inf503",
                }
            )

    return athlete_rows, supplement_rows, birth_year_ok, inf503_cache_missing


def _export_full_csv(events, progress):
    base_records, id_seed, winter_ids, to_cd_by_meet, parse_stats, suspicious_rows, detail_failures, event_status_rows = _build_base_records(events)
    athlete_rows, supplement_rows, birth_year_ok, inf503_cache_missing = _build_athlete_info_and_score_supplement(
        id_seed=id_seed,
        to_cd_by_meet=to_cd_by_meet,
    )

    existing_keys = {
        _record_identity_key(
            _norm(row.get("idNo")),
            _norm(row.get("대회명")),
            _norm(row.get("세부종목")),
            _norm(row.get("라운드")),
            _norm(row.get("순위")),
            _norm(row.get("기록")),
        )
        for row in base_records
    }
    merged_records = list(base_records)
    supplement_added = 0
    supplement_duplicate_skipped = 0
    for row in supplement_rows:
        key = _record_identity_key(
            _norm(row.get("idNo")),
            _norm(row.get("대회명")),
            _norm(row.get("세부종목")),
            _norm(row.get("라운드")),
            _norm(row.get("순위")),
            _norm(row.get("기록")),
        )
        if key in existing_keys:
            supplement_duplicate_skipped += 1
            continue
        existing_keys.add(key)
        merged_records.append(row)
        supplement_added += 1

    merged_records = sorted(
        merged_records,
        key=lambda r: (
            _norm(r.get("대회명")),
            _norm(r.get("일자_정규화")),
            _norm(r.get("세부종목")),
            _norm(r.get("라운드")),
            _norm(r.get("idNo")),
        ),
    )
    athlete_rows = sorted(athlete_rows, key=lambda r: (_norm(r.get("이름")), _norm(r.get("idNo"))))

    RECORDS_FULL_CSV.parent.mkdir(parents=True, exist_ok=True)
    ATHLETE_INFO_FULL_CSV.parent.mkdir(parents=True, exist_ok=True)
    with RECORDS_FULL_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=RECORD_FIELDS)
        writer.writeheader()
        writer.writerows(merged_records)
    with ATHLETE_INFO_FULL_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=ATHLETE_INFO_FIELDS)
        writer.writeheader()
        writer.writerows(athlete_rows)
    _save_csv_rows(SUSPICIOUS_IDS_CSV, suspicious_rows, SUSPICIOUS_ID_FIELDS)
    _save_csv_rows(DETAIL_FAILURES_CSV, detail_failures, DETAIL_FAILURE_FIELDS)

    _bump_counter(progress, "records_inf310_rows", len(base_records))
    _bump_counter(progress, "records_inf503_score_rows", supplement_added)
    _save_progress(progress)

    print(
        "[export] 기록 {0:,}건 (INF310 {1:,} + INF503 보완 추가 {2:,})".format(
            len(merged_records),
            len(base_records),
            supplement_added,
        )
    )
    print(f"[export] INF503 중복 병합 스킵 {supplement_duplicate_skipped:,}건 (중복 키 기준)")
    print(f"[export] 선수 {len(athlete_rows):,}명 / 출생년도 확보 {birth_year_ok:,}명")
    print(
        f"[export] INF503 대상 idNo {len(id_seed):,}명 (동계체전 참가자 {len(winter_ids):,}명 포함) / INF503 캐시 미보유 {inf503_cache_missing:,}명"
    )
    print(f"[export] idNo 비정상 감지 {len(suspicious_rows):,}건 → {SUSPICIOUS_IDS_CSV}")
    if suspicious_rows:
        length_counts = {}
        for row in suspicious_rows:
            length = len(_norm(row.get("idNo_원본")))
            length_counts[length] = length_counts.get(length, 0) + 1
        dist_text = ", ".join(f"{length}자리 {count:,}건" for length, count in sorted(length_counts.items()))
        print(f"[export] idNo 비정상 길이 분포: {dist_text}")
    print(f"[export] 세부종목 실패 {len(detail_failures):,}건 → {DETAIL_FAILURES_CSV}")
    detail_failure_summary = _summarize_detail_failures(detail_failures)
    print(
        "[export] 세부종목 실패 분류: known_warning {0:,} / unknown_warning {1:,} / unknown_failure {2:,}".format(
            detail_failure_summary["known_warning_count"],
            detail_failure_summary["unknown_warning_count"],
            detail_failure_summary["unknown_failure_count"],
        )
    )
    print(
        "[export] INF310 파싱: data row {0:,} / 구분행 {1:,} / 참가자 없음 row {2:,}(결과행 추정 {3:,}) / table 미감지 {4:,} / header 미감지 {5:,} / 비정상 id {6:,}".format(
            parse_stats["inf310_data_row_count"],
            parse_stats["inf310_category_row_count"],
            parse_stats["inf310_row_without_participant_count"],
            parse_stats["inf310_row_without_participant_likely_result_count"],
            parse_stats.get("inf310_table_missing_call_count", 0),
            parse_stats["inf310_header_missing_call_count"],
            parse_stats["inf310_suspicious_id_count"],
        )
    )
    print(
        "[export] 요청 구조: events {0:,}(동계체 {1:,}) / kind {2:,} / detail {3:,} / INF301 call {4:,} / INF310 call {5:,}".format(
            parse_stats["events_total"],
            parse_stats["events_winter"],
            parse_stats["kind_count"],
            parse_stats["detail_class_count"],
            parse_stats["inf301_call_count"],
            parse_stats["inf310_call_count"],
        )
    )
    event_total = parse_stats.get("event_complete_count", 0) + parse_stats.get("event_partial_count", 0) + parse_stats.get("event_failed_count", 0)
    event_complete = parse_stats.get("event_complete_count", 0)
    event_partial = parse_stats.get("event_partial_count", 0)
    event_failed = parse_stats.get("event_failed_count", 0)
    detail_total = parse_stats.get("detail_class_count", 0)
    detail_success = parse_stats.get("detail_success_count", 0)
    detail_failure = parse_stats.get("detail_failure_count", 0)
    print(
        "[export] 대회 상태: 완료 {0:,} / 부분완료 {1:,} / 실패 {2:,} (완료율 {3:.2f}% / 부분완료 포함 {4:.2f}%)".format(
            event_complete,
            event_partial,
            event_failed,
            (event_complete / event_total * 100.0) if event_total else 0.0,
            ((event_complete + event_partial) / event_total * 100.0) if event_total else 0.0,
        )
    )
    print(
        "[export] 세부종목 상태: 성공 {0:,} / 실패 {1:,} / 경고 {2:,} / 전체 {3:,} (성공률 {4:.2f}%)".format(
            detail_success,
            detail_failure,
            parse_stats.get("detail_warning_count", 0),
            detail_total,
            (detail_success / detail_total * 100.0) if detail_total else 0.0,
        )
    )
    print(
        "[export] 세부종목 참가자 0건: 일반 실패 {0:,} / 계주 경고 {1:,}".format(
            parse_stats["inf310_zero_participant_detail_count"],
            parse_stats.get("inf310_zero_participant_relay_warning_count", 0),
        )
    )
    print(
        "[export] INF301 call 미감지 분류: no_schedule {0:,} / parser_mismatch {1:,}".format(
            parse_stats.get("inf301_no_schedule_detail_count", 0),
            parse_stats.get("inf301_parser_mismatch_detail_count", 0),
        )
    )
    return {
        "records_total": len(merged_records),
        "records_inf310": len(base_records),
        "records_inf503_added": supplement_added,
        "records_inf503_duplicate_skipped": supplement_duplicate_skipped,
        "athletes_total": len(athlete_rows),
        "birth_year_covered": birth_year_ok,
        "winter_ids": len(winter_ids),
        "inf503_cache_missing": inf503_cache_missing,
        "known_warning_count": detail_failure_summary["known_warning_count"],
        "unknown_warning_count": detail_failure_summary["unknown_warning_count"],
        "unknown_failure_count": detail_failure_summary["unknown_failure_count"],
        "unknown_failure_rows": detail_failure_summary["unknown_failure_rows"],
        "suspicious_ids_count": len(suspicious_rows),
        "detail_failures": detail_failures,
        "event_status_rows": event_status_rows,
        **parse_stats,
    }


def _count_csv_data_rows(path):
    if not path.exists():
        return 0
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return sum(1 for _ in csv.DictReader(f))


def _classify_detail_failure(row):
    stage = _norm(row.get("실패단계") or row.get("단계"))
    severity = _norm(row.get("심각도")).lower()
    if stage in KNOWN_WARNING_STAGES:
        return "known_warning"
    if severity == "warn":
        return "unknown_warning"
    return "unknown_failure"


def _summarize_detail_failures(rows):
    known_warning = 0
    unknown_warning = 0
    unknown_failure = 0
    unknown_failure_rows = []
    for row in rows:
        kind = _classify_detail_failure(row)
        if kind == "known_warning":
            known_warning += 1
            continue
        if kind == "unknown_warning":
            unknown_warning += 1
            continue
        unknown_failure += 1
        unknown_failure_rows.append(row)
    return {
        "known_warning_count": int(known_warning),
        "unknown_warning_count": int(unknown_warning),
        "unknown_failure_count": int(unknown_failure),
        "unknown_failure_rows": unknown_failure_rows,
    }


def _count_records_by_meet(path, meet_keys=None):
    counts = {}
    if not path.exists():
        return counts
    for row in _load_csv_rows(path):
        key = _meet_key(row.get("classCd"), row.get("toCd"))
        if key == ":":
            continue
        if meet_keys is not None and key not in meet_keys:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _invalidate_meet_cache(event):
    class_cd = _norm(event.get("classCd"))
    to_cd = _norm(event.get("toCd"))
    if not class_cd or not to_cd:
        return 0
    safe_class = _safe_fragment(class_cd)
    safe_to = _safe_fragment(to_cd)
    removed = 0
    targets = [_cache_path_inf301_kind(class_cd, to_cd)]
    targets.extend(RAW_DETAIL_AJAX_DIR.glob(f"{safe_class}_{safe_to}_*.json"))
    targets.extend(RAW_INF301_DIR.glob(f"{safe_class}_{safe_to}_*.html"))
    targets.extend(RAW_INF310_DIR.glob(f"{safe_class}_{safe_to}_*.html"))
    # legacy cache pattern purge (pre-classCd key)
    targets.extend(RAW_INF301_KIND_DIR.glob(f"{safe_to}.html"))
    targets.extend(RAW_INF301_DIR.glob(f"{safe_to}_*.html"))
    targets.extend(RAW_INF310_DIR.glob(f"{safe_to}_*.html"))
    for path in targets:
        if path.exists() and path.is_file():
            path.unlink()
            removed += 1
    return removed


def _load_retry_entries():
    return _load_csv_rows(MEET_FAILURES_CSV)


def _retry_failure_requests(retry_entries):
    if not retry_entries:
        print(f"[retry] {MEET_FAILURES_CSV}에 재시도 대상이 없습니다.")
        return set()
    retry_keys = set()
    for row in retry_entries:
        if _norm(row.get("event_status")) == "완료":
            continue
        class_cd = _norm(row.get("classCd"))
        to_cd = _norm(row.get("toCd"))
        if not class_cd or not to_cd:
            continue
        retry_keys.add(_meet_key(class_cd, to_cd))
    print(f"[retry] 대상 대회 {len(retry_keys)}개")
    return retry_keys


def _id_counts_from_records(path):
    counts = {}
    for row in _load_csv_rows(path):
        id_no = _norm(row.get("idNo"))
        if not id_no:
            continue
        counts[id_no] = counts.get(id_no, 0) + 1
    return counts


def _first_info_by_id(path):
    out = {}
    for row in _load_csv_rows(path):
        id_no = _norm(row.get("idNo"))
        if id_no and id_no not in out:
            out[id_no] = row
    return out


def _compare_resolved():
    required = [RESOLVED_CSV, RECORDS_CSV, ATHLETE_INFO_CSV, RECORDS_FULL_CSV, ATHLETE_INFO_FULL_CSV]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("[error] 회귀 비교에 필요한 파일이 없습니다:")
        for path in missing:
            print(f"  - {path}")
        return 1

    resolved_ids = sorted({_norm(row.get("idNo")) for row in _load_csv_rows(RESOLVED_CSV) if _norm(row.get("idNo"))})
    if not resolved_ids:
        print(f"[error] {RESOLVED_CSV}에 비교 대상 idNo가 없습니다.")
        return 1

    old_records = _id_counts_from_records(RECORDS_CSV)
    new_records = _id_counts_from_records(RECORDS_FULL_CSV)
    old_info = _first_info_by_id(ATHLETE_INFO_CSV)
    new_info = _first_info_by_id(ATHLETE_INFO_FULL_CSV)
    info_fields = ["이름", "성별", "출생년도", "종별", "소속팀", "팀코드", "시도"]

    record_decreases = []
    record_increases = []
    info_mismatches = []
    for id_no in resolved_ids:
        old_count = old_records.get(id_no, 0)
        new_count = new_records.get(id_no, 0)
        if new_count < old_count:
            record_decreases.append((id_no, old_count, new_count))
        elif new_count > old_count:
            record_increases.append((id_no, old_count, new_count))
        old_row = old_info.get(id_no)
        new_row = new_info.get(id_no)
        if old_row is None or new_row is None:
            info_mismatches.append((id_no, "행 누락", "old/new 중 하나가 없음"))
            continue
        for field in info_fields:
            if _norm(old_row.get(field)) != _norm(new_row.get(field)):
                info_mismatches.append((id_no, field, f"old={_norm(old_row.get(field))} / new={_norm(new_row.get(field))}"))

    print(f"[compare] 대상 {len(resolved_ids)}명")
    print(f"[compare] records 감소 {len(record_decreases)}건 / 증가 {len(record_increases)}건")
    print(f"[compare] athlete_info 불일치 {len(info_mismatches)}건")
    for id_no, old_count, new_count in record_decreases[:20]:
        print(f"  - records 감소 {id_no}: old={old_count}, new={new_count}")
    for id_no, old_count, new_count in record_increases[:20]:
        print(f"  - records 증가 {id_no}: old={old_count}, new={new_count}")
    for id_no, field, message in info_mismatches[:20]:
        print(f"  - info {id_no} [{field}] {message}")
    if record_decreases:
        return 1
    if any(field == "행 누락" for _, field, _ in info_mismatches):
        return 1
    print("[compare] 회귀 비교 통과 (records 감소 없음)")
    return 0


def _cleanup_raw_cache():
    if not RAW_ROOT_DIR.exists():
        print(f"[cleanup] 캐시 디렉터리가 없습니다: {RAW_ROOT_DIR}")
        return 0
    removed = 0
    for path in RAW_ROOT_DIR.rglob("*"):
        if path.is_file():
            path.unlink()
            removed += 1
    for path in sorted(RAW_ROOT_DIR.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if RAW_ROOT_DIR.exists() and not any(RAW_ROOT_DIR.iterdir()):
        RAW_ROOT_DIR.rmdir()
    print(f"[cleanup] raw HTML 삭제 완료: {removed}건")
    return 0


def _finalize_summary(progress, request_failures, meet_failures, mode, export_summary):
    request_total = int(progress["counters"].get("request_network_attempted", 0))
    request_failures_remaining = len(request_failures)
    meet_failures_remaining = len(meet_failures)
    request_success_rate = 100.0
    if request_total > 0:
        request_success_rate = (request_total - request_failures_remaining) / request_total * 100.0
    event_total = int(export_summary.get("event_complete_count", 0)) + int(export_summary.get("event_partial_count", 0)) + int(
        export_summary.get("event_failed_count", 0)
    )
    event_complete = int(export_summary.get("event_complete_count", 0))
    event_partial = int(export_summary.get("event_partial_count", 0))
    event_failed = int(export_summary.get("event_failed_count", 0))
    event_complete_rate = (event_complete / event_total * 100.0) if event_total else 0.0
    event_partial_inclusive_rate = ((event_complete + event_partial) / event_total * 100.0) if event_total else 0.0
    detail_total = int(export_summary.get("detail_class_count", 0))
    detail_success = int(export_summary.get("detail_success_count", 0))
    detail_success_rate = (detail_success / detail_total * 100.0) if detail_total else 0.0
    summary = {
        "mode": mode,
        "updated_at": _now_iso(),
        "request_network_attempted": request_total,
        "request_failures_remaining": request_failures_remaining,
        "meet_failures_remaining": meet_failures_remaining,
        "request_success_rate_percent": round(request_success_rate, 2),
        "event_complete_rate_percent": round(event_complete_rate, 2),
        "event_partial_inclusive_rate_percent": round(event_partial_inclusive_rate, 2),
        "detail_success_rate_percent": round(detail_success_rate, 2),
        "meets_95_percent": event_complete_rate >= 95.0,
        "export": export_summary,
    }
    meet_items = list(progress.get("meets", {}).values())
    meet_done = sum(1 for item in meet_items if _norm(item.get("상태")) == "done")
    meet_partial = sum(1 for item in meet_items if _norm(item.get("상태")) == "partial")
    meet_failed = sum(1 for item in meet_items if _norm(item.get("상태")) == "failed")
    meet_in_progress = sum(1 for item in meet_items if _norm(item.get("상태")) == "in_progress")
    summary["meet_done"] = meet_done
    summary["meet_partial"] = meet_partial
    summary["meet_failed"] = meet_failed
    summary["meet_in_progress"] = meet_in_progress
    progress["last_summary"] = summary
    _save_progress(progress)
    print(
        "[summary] 대회 상태 완료 {0:,} / 부분완료 {1:,} / 실패 {2:,} / 완료율 {3:.2f}% / 부분완료 포함 {4:.2f}% / 95% 기준 {5}".format(
            event_complete,
            event_partial,
            event_failed,
            event_complete_rate,
            event_partial_inclusive_rate,
            "충족" if event_complete_rate >= 95.0 else "미충족",
        )
    )
    print(
        "[summary] 세부종목 성공 {0:,}/{1:,} ({2:.2f}%) / 실패 {3:,} / 경고 {4:,}".format(
            detail_success,
            detail_total,
            detail_success_rate,
            int(export_summary.get("detail_failure_count", 0)),
            int(export_summary.get("detail_warning_count", 0)),
        )
    )
    print(
        "[summary] 요청시도 {0:,}건 / 요청실패 {1:,}건 / 요청 성공률 {2:.2f}% / 대회 실패(재시도 대상) {3:,}건".format(
            request_total,
            request_failures_remaining,
            request_success_rate,
            meet_failures_remaining,
        )
    )
    if meet_failures_remaining:
        print(f"[summary] 부분완료/실패 대회 목록 {meet_failures_remaining}건 → {MEET_FAILURES_CSV}")
    else:
        print("[summary] 부분완료/실패 대회 목록 없음")
    print(f"[summary] 진행상태 반영: 완료 {meet_done:,} / 부분완료 {meet_partial:,} / 실패 {meet_failed:,} / 진행중 {meet_in_progress:,}")
    if request_failures_remaining:
        print(f"[summary] 요청 실패 목록 잔여 {request_failures_remaining}건 → {REQUEST_FAILURES_CSV}")
    else:
        print("[summary] 요청 실패 목록 없음")


def _enforce_unknown_failure_policy(export_summary, *, fail_on_unknown_failures):
    unknown_count = int(export_summary.get("unknown_failure_count", 0))
    if unknown_count <= 0:
        return
    print(f"[summary] unknown failure {unknown_count}건 감지")
    for row in export_summary.get("unknown_failure_rows", [])[:10]:
        print(
            "  - classCd={0} toCd={1} kindCd={2} detailClassCd={3} stage={4} reason={5}".format(
                _norm(row.get("classCd")),
                _norm(row.get("toCd")),
                _norm(row.get("kindCd")),
                _norm(row.get("detailClassCd")),
                _norm(row.get("실패단계") or row.get("단계")),
                _norm(row.get("사유")),
            )
        )
    if fail_on_unknown_failures:
        raise RuntimeError(f"[error] unknown failure {unknown_count}건 감지")


def _build_arg_parser():
    parser = argparse.ArgumentParser(description="대회 중심( INF201→INF301/AJAX→INF310 ) + 전체 선수 INF503 보완 수집기")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="입출력 데이터 디렉터리 (기본: ./data, 또는 환경변수 SPLITS_DATA_DIR)",
    )
    parser.add_argument(
        "--request-gap",
        type=float,
        default=REQUEST_GAP_SECONDS,
        help="네트워크 요청 간격(초), 기본 1.0",
    )
    parser.add_argument(
        "--max-inf201-pages",
        type=int,
        default=None,
        help="테스트용: INF201 최대 페이지 수 제한",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="테스트용: classCd=2 대회 최대 처리 수 제한",
    )
    parser.add_argument(
        "--fail-on-unknown-failures",
        action="store_true",
        help="known warning을 제외한 신규 실패 유형이 있으면 종료 코드 1로 실패 처리",
    )

    sub = parser.add_subparsers(dest="command")
    collect_parser = sub.add_parser("collect", help="전수 수집 + 전체 선수 INF503 보완 + full CSV 생성")
    collect_parser.add_argument("--refresh", action="store_true", help="캐시 무시 후 전체 재수집")

    retry_parser = sub.add_parser("retry-failures", help="실패 대회 재시도 후 full CSV 재생성")
    retry_parser.add_argument("--refresh", action="store_true", help="재시도 시 캐시 무시")

    sub.add_parser("export", help="캐시 기반 full CSV 재생성 (네트워크 요청 없음)")
    weekly_parser = sub.add_parser("weekly-incremental", help="주간 증분 수집 (INF201 1페이지 기준 신규 대회만)")
    weekly_parser.add_argument(
        "--max-new-pages",
        type=int,
        default=5,
        help="신규 감지 시 추가 조회할 INF201 최대 페이지 수 (기본 5)",
    )
    weekly_parser.add_argument(
        "--summary-json",
        default=None,
        help="주간 실행 요약 JSON 출력 경로 (기본: data/weekly_incremental_summary.json)",
    )
    sub.add_parser("compare-resolved", help="기존 14명(resolved.csv) 기준 회귀 비교")
    sub.add_parser("cleanup-raw-cache", help="집계 후 raw HTML 캐시 정리")
    return parser


def _prepare_runtime(mode, data_dir, request_gap):
    _configure_data_paths(data_dir)
    progress = _load_progress()
    request_failures = _load_failures()
    meet_failures = _load_meet_failures()
    progress["last_mode"] = mode
    progress["request_gap_seconds"] = request_gap
    _save_progress(progress)
    return progress, request_failures, meet_failures


def _write_weekly_summary(payload, summary_json_path=None):
    target = pathlib.Path(summary_json_path).expanduser() if summary_json_path else WEEKLY_SUMMARY_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[weekly] 요약 저장: {target}")


def _run_weekly_incremental(args):
    if args.request_gap < 1.0:
        raise ValueError("[error] --request-gap은 1.0 이상이어야 합니다.")
    data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
    progress, failures, meet_failures = _prepare_runtime("weekly-incremental", data_dir=data_dir, request_gap=args.request_gap)
    print(f"[path] data_dir={DATA_DIR}")

    meet_index_rows, seeded = _ensure_meet_index_rows()
    known_meet_keys = {
        _meet_key(row.get("classCd"), row.get("toCd"))
        for row in meet_index_rows
        if _norm(row.get("classCd")) == "2" and _norm(row.get("toCd"))
    }
    print(f"[weekly] known meets(classCd=2): {len(known_meet_keys):,}")

    session = requests.Session()
    max_new_pages = max(1, int(args.max_new_pages or 1))
    fetched_class2_events = []
    new_events = []
    new_event_keys = set()
    fetched_pages = 0

    for page in range(1, max_new_pages + 1):
        page_events = _collect_inf201_page_events(
            session,
            page,
            refresh=True,
            request_gap_seconds=args.request_gap,
            progress=progress,
            failures=failures,
        )
        if not page_events:
            break
        fetched_pages += 1
        class2_page_events = [event for event in page_events if _norm(event.get("classCd")) == "2" and _norm(event.get("toCd"))]
        if not class2_page_events:
            break
        fetched_class2_events.extend(class2_page_events)

        page_new_count = 0
        for event in class2_page_events:
            key = _meet_key(event.get("classCd"), event.get("toCd"))
            if key in known_meet_keys or key in new_event_keys:
                continue
            new_event_keys.add(key)
            new_events.append(event)
            page_new_count += 1

        if page == 1 and page_new_count == 0:
            break
        if page > 1 and page_new_count == 0:
            break

    print(f"[weekly] INF201 조회 페이지: {fetched_pages} / 신규 대회: {len(new_events):,}")
    summary_payload = {
        "mode": "weekly-incremental",
        "updatedAt": _now_iso(),
        "seededMeetIndex": bool(seeded),
        "fetchedPages": int(fetched_pages),
        "fetchedClass2Events": int(len(fetched_class2_events)),
        "newEventCount": int(len(new_events)),
        "newEventKeys": sorted(new_event_keys),
        "hasNewEvents": bool(new_events),
        "recordsAnonAppended": 0,
        "recordsAnonDuplicateSkipped": 0,
        "recordsAnonTotalRows": 0,
        "unknownFailureCount": 0,
        "meetIndexUpdated": bool(seeded),
        "shouldCommit": bool(seeded),
    }

    if not new_events:
        _write_weekly_summary(summary_payload, summary_json_path=args.summary_json)
        return

    _collect_event_route(
        session,
        events=new_events,
        refresh=True,
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
        meet_failures=meet_failures,
    )
    base_records, _, winter_ids, _, _, _, _, _ = _build_base_records(new_events)
    inf310_ids = sorted({_norm(row.get("idNo")) for row in base_records if _norm(row.get("idNo"))})
    print(f"[weekly] 신규 대회 INF503 보완 대상(전체) {len(inf310_ids):,}명 / 동계체전 참가자 {len(winter_ids):,}명")
    _collect_inf503_for_ids(
        session,
        id_list=inf310_ids,
        refresh=False,
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
    )

    export_summary = _export_full_csv(new_events, progress=progress)
    _apply_event_status_rows(progress, meet_failures, export_summary.get("event_status_rows", []))
    _finalize_summary(progress, failures, meet_failures, mode="weekly-incremental", export_summary=export_summary)
    _enforce_unknown_failure_policy(
        export_summary,
        fail_on_unknown_failures=bool(args.fail_on_unknown_failures),
    )

    append_summary = _append_records_anon_from_full()
    merged_meet_index = _merge_meet_index_rows(meet_index_rows, fetched_class2_events)
    _save_meet_index_rows(merged_meet_index)

    summary_payload.update(
        {
            "recordsAnonAppended": int(append_summary["appended_rows"]),
            "recordsAnonDuplicateSkipped": int(append_summary["duplicate_skipped"]),
            "recordsAnonTotalRows": int(append_summary["total_rows"]),
            "unknownFailureCount": int(export_summary.get("unknown_failure_count", 0)),
            "meetIndexUpdated": True,
            "shouldCommit": bool(append_summary["appended_rows"] > 0 or len(new_events) > 0),
        }
    )
    _write_weekly_summary(summary_payload, summary_json_path=args.summary_json)


def _run_collect(args):
    if args.request_gap < 1.0:
        raise ValueError("[error] --request-gap은 1.0 이상이어야 합니다.")
    data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
    progress, failures, meet_failures = _prepare_runtime("collect", data_dir=data_dir, request_gap=args.request_gap)
    print(f"[path] data_dir={DATA_DIR}")

    session = requests.Session()
    events = _collect_inf201_events(
        session,
        refresh=bool(args.refresh),
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
        max_pages=args.max_inf201_pages,
    )
    if args.max_events is not None:
        events = events[: max(0, args.max_events)]
    print(f"[target] classCd=2 대회 {len(events)}개")

    _collect_event_route(
        session,
        events=events,
        refresh=bool(args.refresh),
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
        meet_failures=meet_failures,
    )

    base_records, _, winter_ids, _, _, _, _, _ = _build_base_records(events)
    inf310_ids = sorted({_norm(r.get("idNo")) for r in base_records if _norm(r.get("idNo"))})
    print(f"[target] INF310 기반 고유 선수 {len(inf310_ids):,}명")
    print(f"[target] INF503 보완 대상(전체) {len(inf310_ids):,}명 / 동계체전 참가자 {len(winter_ids):,}명")
    _collect_inf503_for_ids(
        session,
        id_list=inf310_ids,
        refresh=bool(args.refresh),
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
    )

    export_summary = _export_full_csv(events, progress=progress)
    _apply_event_status_rows(progress, meet_failures, export_summary.get("event_status_rows", []))
    _finalize_summary(progress, failures, meet_failures, mode="collect", export_summary=export_summary)
    _enforce_unknown_failure_policy(
        export_summary,
        fail_on_unknown_failures=bool(args.fail_on_unknown_failures),
    )


def _run_retry_failures(args):
    if args.request_gap < 1.0:
        raise ValueError("[error] --request-gap은 1.0 이상이어야 합니다.")
    data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
    progress, failures, meet_failures = _prepare_runtime("retry-failures", data_dir=data_dir, request_gap=args.request_gap)
    print(f"[path] data_dir={DATA_DIR}")

    session = requests.Session()
    retry_entries = _load_retry_entries()
    retry_keys = _retry_failure_requests(retry_entries=retry_entries)
    rows_before_total = _count_csv_data_rows(RECORDS_FULL_CSV)
    rows_before_by_meet = _count_records_by_meet(RECORDS_FULL_CSV, meet_keys=retry_keys) if retry_keys else {}

    # 실패 대회 목록만 다시 수집한다.
    events = _collect_inf201_events(
        session,
        refresh=False,
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
        max_pages=args.max_inf201_pages,
    )
    if args.max_events is not None:
        events = events[: max(0, args.max_events)]
    if retry_keys:
        events = [event for event in events if _meet_key(event.get("classCd"), event.get("toCd")) in retry_keys]
    else:
        events = []
    print(f"[retry] 재수집 대상 대회 {len(events)}개")
    invalidated = 0
    for event in events:
        invalidated += _invalidate_meet_cache(event)
    print(f"[retry] 대상 대회 캐시 무효화 {invalidated:,}건")
    if events and not bool(args.refresh):
        print("[retry] 재시도는 강제 재요청 모드로 실행됩니다 (target meet refresh=true).")
    _collect_event_route(
        session,
        events=events,
        refresh=True,
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
        meet_failures=meet_failures,
    )

    all_events = _load_events_from_inf201_cache()
    if args.max_events is not None:
        all_events = all_events[: max(0, args.max_events)]
    base_records_retry, _, winter_ids, _, _, _, _, _ = _build_base_records(all_events)
    inf310_ids_retry = sorted({_norm(r.get("idNo")) for r in base_records_retry if _norm(r.get("idNo"))})
    print(f"[retry] INF503 보완 대상(전체) {len(inf310_ids_retry):,}명 / 동계체전 참가자 {len(winter_ids):,}명")
    _collect_inf503_for_ids(
        session,
        id_list=inf310_ids_retry,
        refresh=False,
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
    )

    export_summary = _export_full_csv(all_events, progress=progress)
    _apply_event_status_rows(progress, meet_failures, export_summary.get("event_status_rows", []))
    rows_after_total = int(export_summary.get("records_total", 0))
    print(f"[retry] records_full 행수 변화: {rows_before_total:,} -> {rows_after_total:,} ({rows_after_total - rows_before_total:+,})")
    if retry_keys:
        rows_after_by_meet = _count_records_by_meet(RECORDS_FULL_CSV, meet_keys=retry_keys)
        changed_meets = 0
        for key in sorted(retry_keys):
            before = int(rows_before_by_meet.get(key, 0))
            after = int(rows_after_by_meet.get(key, 0))
            delta = after - before
            if delta != 0:
                changed_meets += 1
            class_cd, to_cd = key.split(":", 1)
            print(f"[retry] 대회 행수 변화 classCd={class_cd} toCd={to_cd}: {before:,} -> {after:,} ({delta:+,})")
        print(f"[retry] 행수 변화 발생 대회 {changed_meets:,}/{len(retry_keys):,}")
    _finalize_summary(progress, failures, meet_failures, mode="retry-failures", export_summary=export_summary)
    _enforce_unknown_failure_policy(
        export_summary,
        fail_on_unknown_failures=bool(args.fail_on_unknown_failures),
    )


def _run_export(args):
    data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
    progress, failures, meet_failures = _prepare_runtime("export", data_dir=data_dir, request_gap=args.request_gap)
    print(f"[path] data_dir={DATA_DIR}")
    events = _load_events_from_inf201_cache()
    if args.max_events is not None:
        events = events[: max(0, args.max_events)]
    if not events:
        raise FileNotFoundError(f"[error] INF201 캐시가 없습니다: {RAW_INF201_DIR}. 먼저 collect를 실행하세요.")
    export_summary = _export_full_csv(events, progress=progress)
    _apply_event_status_rows(progress, meet_failures, export_summary.get("event_status_rows", []))
    _finalize_summary(progress, failures, meet_failures, mode="export", export_summary=export_summary)
    _enforce_unknown_failure_policy(
        export_summary,
        fail_on_unknown_failures=bool(args.fail_on_unknown_failures),
    )


def main():
    load_local_env()
    parser = _build_arg_parser()
    args = parser.parse_args()
    command = args.command or "collect"

    try:
        if command == "collect":
            _run_collect(args)
            return
        if command == "retry-failures":
            _run_retry_failures(args)
            return
        if command == "export":
            _run_export(args)
            return
        if command == "weekly-incremental":
            _run_weekly_incremental(args)
            return
        if command == "compare-resolved":
            data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
            _configure_data_paths(data_dir)
            raise SystemExit(_compare_resolved())
        if command == "cleanup-raw-cache":
            data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
            _configure_data_paths(data_dir)
            raise SystemExit(_cleanup_raw_cache())
        raise SystemExit(f"[error] 알 수 없는 명령어: {command}")
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1)
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("[interrupt] 사용자 중단 감지: 현재까지 저장된 캐시/진행상태로 다음 실행에서 이어받을 수 있습니다.")


if __name__ == "__main__":
    main()
