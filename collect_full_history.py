import argparse
import csv
import json
import os
import pathlib
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from event_participants import (
    _base_payload,
    _extract_participant_entries,
    _extract_result_headers,
    _find_table_by_caption,
    _parse_js_args,
    _read_pairs_from_table,
)
from scrape import parse_athlete_info, parse_history

BASE_URL = "https://result.sports.or.kr/SK"
INF201_ENDPOINT = f"{BASE_URL}/INF201.do"
INF202_ENDPOINT = f"{BASE_URL}/INF202.do"
INF301_ENDPOINT = f"{BASE_URL}/INF301.do"
INF310_ENDPOINT = f"{BASE_URL}/INF310.do"
INF503_ENDPOINT = f"{BASE_URL}/INF503.do"

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
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
RAW_INF202_DIR = RAW_ROOT_DIR / "inf202"
RAW_INF301_DIR = RAW_ROOT_DIR / "inf301"
RAW_INF310_DIR = RAW_ROOT_DIR / "inf310"
RAW_INF503_DIR = RAW_ROOT_DIR / "inf503"

PROGRESS_JSON = DATA_DIR / "collect_progress.json"
FAILURES_CSV = DATA_DIR / "collect_failures.csv"
INF202_EMPTY_EVENTS_CSV = DATA_DIR / "inf202_empty_events.csv"
RECORDS_FULL_CSV = DATA_DIR / "records_full.csv"
ATHLETE_INFO_FULL_CSV = DATA_DIR / "athlete_info_full.csv"
RECORDS_CSV = DATA_DIR / "records.csv"
ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"
RESOLVED_CSV = DATA_DIR / "resolved.csv"

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
INF202_EMPTY_FIELDS = ["classCd", "toCd", "inf201_대회명", "inf202_대회명", "원인", "비고"]
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
]

DATE_DIGITS_RE = re.compile(r"^(19|20)\d{2}(0[1-9]|1[0-2])([0-2]\d|3[01])$")
DATE_DOTTED_RE = re.compile(r"^((?:19|20)\d{2})[.\-/](0?[1-9]|1[0-2])[.\-/](0?[1-9]|[12]\d|3[01])$")
FIRST_DATE_RE = re.compile(r"((?:19|20)\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")
DIGITS_RE = re.compile(r"\d+")


def _configure_data_paths(base_dir):
    global DATA_DIR
    global RAW_ROOT_DIR
    global RAW_INF201_DIR
    global RAW_INF202_DIR
    global RAW_INF301_DIR
    global RAW_INF310_DIR
    global RAW_INF503_DIR
    global PROGRESS_JSON
    global FAILURES_CSV
    global INF202_EMPTY_EVENTS_CSV
    global RECORDS_FULL_CSV
    global ATHLETE_INFO_FULL_CSV
    global RECORDS_CSV
    global ATHLETE_INFO_CSV
    global RESOLVED_CSV

    DATA_DIR = pathlib.Path(base_dir).expanduser()
    RAW_ROOT_DIR = DATA_DIR / "raw"
    RAW_INF201_DIR = RAW_ROOT_DIR / "inf201"
    RAW_INF202_DIR = RAW_ROOT_DIR / "inf202"
    RAW_INF301_DIR = RAW_ROOT_DIR / "inf301"
    RAW_INF310_DIR = RAW_ROOT_DIR / "inf310"
    RAW_INF503_DIR = RAW_ROOT_DIR / "inf503"

    PROGRESS_JSON = DATA_DIR / "collect_progress.json"
    FAILURES_CSV = DATA_DIR / "collect_failures.csv"
    INF202_EMPTY_EVENTS_CSV = DATA_DIR / "inf202_empty_events.csv"
    RECORDS_FULL_CSV = DATA_DIR / "records_full.csv"
    ATHLETE_INFO_FULL_CSV = DATA_DIR / "athlete_info_full.csv"
    RECORDS_CSV = DATA_DIR / "records.csv"
    ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"
    RESOLVED_CSV = DATA_DIR / "resolved.csv"


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _norm(value):
    return str(value or "").strip()


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


def _is_placeholder_text(text):
    value = _norm(text).replace(" ", "")
    return value in {"", "-", "~", "미등록", "N/A", "n/a"}


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
        "version": 2,
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
            "inf202_requests": 0,
            "inf202_empty_events": 0,
            "inf301_requests": 0,
            "inf310_requests": 0,
            "inf503_requests": 0,
            "records_inf310_rows": 0,
            "records_inf503_score_rows": 0,
        },
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
    return payload


def _save_progress(progress):
    progress["updated_at"] = _now_iso()
    PROGRESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PROGRESS_JSON)


def _bump_counter(progress, key, amount=1):
    progress["counters"][key] = int(progress["counters"].get(key, 0)) + int(amount)


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


def _load_failures():
    failures = {}
    for row in _load_csv_rows(FAILURES_CSV):
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
    _save_csv_rows(FAILURES_CSV, rows, FAILURE_FIELDS)


def _save_inf202_empty_events(rows):
    _save_csv_rows(INF202_EMPTY_EVENTS_CSV, rows, INF202_EMPTY_FIELDS)


def _is_retryable_http(status_code):
    return status_code == 429 or status_code >= 500


def _post_with_retry(session, endpoint, payload):
    last_reason = "unknown"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.post(endpoint, data=payload, headers=HEADERS, timeout=TIMEOUT_SECONDS)
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


def _cache_path_inf202(class_cd, to_cd):
    return RAW_INF202_DIR / f"{_safe_fragment(class_cd)}_{_safe_fragment(to_cd)}.html"


def _cache_path_inf301(to_cd, kind_cd, detail_class_cd):
    return RAW_INF301_DIR / f"{_safe_fragment(to_cd)}_{_safe_fragment(kind_cd)}_{_safe_fragment(detail_class_cd)}.html"


def _cache_path_inf310(to_cd, kind_cd, detail_class_cd, base_class_cd, rh_cd, pcnt_gbn):
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
):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not refresh:
        _bump_counter(progress, "request_cache_hit")
        _clear_failure(failures, request_key)
        _save_failures(failures)
        _save_progress(progress)
        return cache_path.read_text(encoding="utf-8"), True

    _bump_counter(progress, "request_network_attempted")
    html, attempts, reason = _post_with_retry(session, endpoint, payload)
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
        return None, False

    cache_path.write_text(html, encoding="utf-8")
    _bump_counter(progress, "request_success")
    _clear_failure(failures, request_key)
    _save_failures(failures)
    _save_progress(progress)
    if request_gap_seconds > 0:
        time.sleep(request_gap_seconds)
        _bump_counter(progress, "request_sleep_applied")
        _save_progress(progress)
    return html, False


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


def _parse_inf202_bundle_html(html, class_cd, to_cd):
    soup = BeautifulSoup(html, "html.parser")
    info_table = _find_table_by_caption(soup, "대회정보")
    event_info = _read_pairs_from_table(info_table)
    details = []
    for tr in soup.find_all("tr"):
        args = _parse_js_args(tr.get("onclick", ""), "fnEventSchedule")
        if not args or len(args) < 2:
            continue
        kind_cd = _norm(args[0])
        detail_class_cd = _norm(args[1])
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        participant_text = _norm(tds[3].get_text(" ", strip=True))
        match = DIGITS_RE.search(participant_text)
        participant_count = int(match.group(0)) if match else None
        details.append(
            {
                "kindCd": kind_cd,
                "detailClassCd": detail_class_cd,
                "종별": _norm(tds[0].get_text(" ", strip=True)),
                "세부종목": _norm(tds[1].get_text(" ", strip=True)),
                "구분": _norm(tds[2].get_text(" ", strip=True)),
                "참가선수수": participant_count,
            }
        )
    if details:
        return {"eventInfo": event_info, "details": details, "empty_reason": ""}

    event_name = _norm(event_info.get("대회명"))
    period = _norm(event_info.get("대회기간") or event_info.get("기간"))
    place = _norm(event_info.get("개최장소") or event_info.get("장소"))
    if _is_placeholder_text(event_name) and _is_placeholder_text(period) and _is_placeholder_text(place):
        reason = "source_blank_event_info"
    else:
        reason = "no_schedule_rows"
    return {"eventInfo": event_info, "details": [], "empty_reason": reason}


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


def _parse_inf310_rows_html(html, result_call):
    soup = BeautifulSoup(html, "html.parser")
    table = _find_table_by_caption(soup, "경기결과")
    if not table:
        return {
            "rows": [],
            "stats": {
                "header_detected": False,
                "data_row_count": 0,
                "category_row_count": 0,
                "row_with_participant_count": 0,
                "row_without_participant_count": 0,
                "row_without_participant_likely_result_count": 0,
                "participant_entry_count": 0,
            },
        }

    headers = _extract_result_headers(table)
    header_detected = bool(headers)
    rows = []
    seen = set()

    current_round = _norm(result_call.get("rhNm"))
    current_category = ""
    data_row_count = 0
    category_row_count = 0
    row_with_participant_count = 0
    row_without_participant_count = 0
    row_without_participant_likely_result_count = 0
    participant_entry_count = 0

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

        participants = _extract_participant_entries(tr, row_map)
        if not participants:
            row_without_participant_count += 1
            if rank or record or row_name:
                row_without_participant_likely_result_count += 1
            continue

        row_with_participant_count += 1
        participant_entry_count += len(participants)
        for participant in participants:
            id_no = _norm(participant.get("idNo"))
            if not id_no:
                continue
            unique_key = (
                id_no,
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
                    "이름": _norm(participant.get("name")) or row_name,
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
            "header_detected": header_detected,
            "data_row_count": data_row_count,
            "category_row_count": category_row_count,
            "row_with_participant_count": row_with_participant_count,
            "row_without_participant_count": row_without_participant_count,
            "row_without_participant_likely_result_count": row_without_participant_likely_result_count,
            "participant_entry_count": participant_entry_count,
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
        html, _ = _fetch_with_cache(
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
):
    total_events = len(events)
    seen_inf310 = set()
    inf202_empty_events = []
    for idx, event in enumerate(events, start=1):
        class_cd = _norm(event.get("classCd"))
        to_cd = _norm(event.get("toCd"))
        search_app_yn = _norm(event.get("searchAppYn"))
        event_name = _norm(event.get("대회명"))
        print(f"[event {idx}/{total_events}] classCd={class_cd} toCd={to_cd} | {event_name}")

        payload_202 = _base_payload()
        payload_202.update({"classCd": class_cd, "toCd": to_cd, "searchAppYn": search_app_yn})
        html_202, _ = _fetch_with_cache(
            session,
            request_type="inf202",
            request_key=f"inf202:{class_cd}:{to_cd}",
            endpoint=INF202_ENDPOINT,
            payload=payload_202,
            cache_path=_cache_path_inf202(class_cd, to_cd),
            context=f"classCd={class_cd} toCd={to_cd}",
            refresh=refresh,
            request_gap_seconds=request_gap_seconds,
            progress=progress,
            failures=failures,
        )
        _bump_counter(progress, "inf202_requests")
        _save_progress(progress)
        if html_202 is None:
            continue
        bundle = _parse_inf202_bundle_html(html_202, class_cd=class_cd, to_cd=to_cd)
        details = bundle["details"]
        if not details:
            reason = _norm(bundle.get("empty_reason"))
            reason_text = "원천 대회정보 공백" if reason == "source_blank_event_info" else "세부종목 미노출"
            inf202_name = _norm(bundle["eventInfo"].get("대회명"))
            print(
                "[info] INF202 세부종목 미수집: classCd={0}, toCd={1}, 원인={2}".format(
                    class_cd, to_cd, reason_text
                )
            )
            inf202_empty_events.append(
                {
                    "classCd": class_cd,
                    "toCd": to_cd,
                    "inf201_대회명": event_name,
                    "inf202_대회명": inf202_name,
                    "원인": reason_text,
                    "비고": "INF201 목록에는 있으나 INF202 상세가 비어 INF301/INF310 진행 불가",
                }
            )
            _bump_counter(progress, "inf202_empty_events")
            _save_progress(progress)
            continue
        for detail in details:
            kind_cd = _norm(detail.get("kindCd"))
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
            html_301, _ = _fetch_with_cache(
                session,
                request_type="inf301",
                request_key=f"inf301:{to_cd}:{kind_cd}:{detail_class_cd}",
                endpoint=INF301_ENDPOINT,
                payload=payload_301,
                cache_path=_cache_path_inf301(to_cd, kind_cd, detail_class_cd),
                context=f"toCd={to_cd} kindCd={kind_cd} detailClassCd={detail_class_cd}",
                refresh=refresh,
                request_gap_seconds=request_gap_seconds,
                progress=progress,
                failures=failures,
            )
            _bump_counter(progress, "inf301_requests")
            _save_progress(progress)
            if html_301 is None:
                continue

            calls = _parse_inf301_result_calls_html(html_301)
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
                html_310, _ = _fetch_with_cache(
                    session,
                    request_type="inf310",
                    request_key=f"inf310:{to_cd}:{kind_cd}:{detail_class_cd}:{base_class_cd}:{rh_cd}:{pcnt_gbn}:{use_gbn or '-'}",
                    endpoint=INF310_ENDPOINT,
                    payload=payload_310,
                    cache_path=_cache_path_inf310(
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
                if html_310 is None:
                    continue

    _save_inf202_empty_events(inf202_empty_events)
    print(
        "[summary] INF202 세부종목 미수집 대회 {0:,}건 → {1}".format(
            len(inf202_empty_events), INF202_EMPTY_EVENTS_CSV
        )
    )
    return inf202_empty_events


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
    parse_stats = {
        "events_total": len(events),
        "events_winter": 0,
        "inf202_detail_count": 0,
        "inf202_empty_event_count": 0,
        "inf202_empty_source_blank_count": 0,
        "inf202_empty_no_schedule_count": 0,
        "inf301_call_count": 0,
        "inf310_call_count": 0,
        "inf310_header_missing_call_count": 0,
        "inf310_data_row_count": 0,
        "inf310_category_row_count": 0,
        "inf310_row_without_participant_count": 0,
        "inf310_row_without_participant_likely_result_count": 0,
        "inf310_participant_entry_count": 0,
    }

    for event in events:
        class_cd = _norm(event.get("classCd"))
        to_cd = _norm(event.get("toCd"))
        event_name = _norm(event.get("대회명"))
        is_winter = "동계체" in event_name
        if is_winter:
            parse_stats["events_winter"] += 1
        if event_name:
            to_cd_by_meet.setdefault(event_name, set()).add(to_cd)

        cache_202 = _cache_path_inf202(class_cd, to_cd)
        if not cache_202.exists():
            continue
        html_202 = cache_202.read_text(encoding="utf-8")
        bundle = _parse_inf202_bundle_html(html_202, class_cd=class_cd, to_cd=to_cd)
        details = bundle["details"]
        if not details:
            parse_stats["inf202_empty_event_count"] += 1
            if _norm(bundle.get("empty_reason")) == "source_blank_event_info":
                parse_stats["inf202_empty_source_blank_count"] += 1
            else:
                parse_stats["inf202_empty_no_schedule_count"] += 1
            continue
        event_info = bundle["eventInfo"]
        _, event_date_norm = _extract_event_date(event_info)
        parse_stats["inf202_detail_count"] += len(details)

        for detail in details:
            kind_cd = _norm(detail.get("kindCd"))
            detail_class_cd = _norm(detail.get("detailClassCd"))
            detail_category = _norm(detail.get("종별"))
            detail_name = _norm(detail.get("세부종목"))

            cache_301 = _cache_path_inf301(to_cd, kind_cd, detail_class_cd)
            if not cache_301.exists():
                continue
            calls = _parse_inf301_result_calls_html(cache_301.read_text(encoding="utf-8"))
            parse_stats["inf301_call_count"] += len(calls)
            for call in calls:
                pcnt_gbn = _norm(call.get("pcntGbn")) or "-"
                cache_310 = _cache_path_inf310(
                    to_cd=to_cd,
                    kind_cd=kind_cd,
                    detail_class_cd=detail_class_cd,
                    base_class_cd=_norm(call.get("baseClassCd")),
                    rh_cd=_norm(call.get("rhCd")),
                    pcnt_gbn=pcnt_gbn,
                )
                if not cache_310.exists():
                    continue
                cache_key = str(cache_310)
                if cache_key in seen_inf310_cache:
                    continue
                seen_inf310_cache.add(cache_key)
                inf310 = _parse_inf310_rows_html(cache_310.read_text(encoding="utf-8"), call)
                rows = inf310["rows"]
                stats = inf310["stats"]
                parse_stats["inf310_call_count"] += 1
                if not stats["header_detected"]:
                    parse_stats["inf310_header_missing_call_count"] += 1
                parse_stats["inf310_data_row_count"] += stats["data_row_count"]
                parse_stats["inf310_category_row_count"] += stats["category_row_count"]
                parse_stats["inf310_row_without_participant_count"] += stats["row_without_participant_count"]
                parse_stats["inf310_row_without_participant_likely_result_count"] += stats["row_without_participant_likely_result_count"]
                parse_stats["inf310_participant_entry_count"] += stats["participant_entry_count"]

                for row in rows:
                    record_key = (
                        _norm(row.get("idNo")),
                        event_name,
                        detail_name,
                        _norm(row.get("라운드")),
                        _norm(row.get("순위")),
                        _norm(row.get("기록")),
                        _norm(row.get("소속")),
                    )
                    if not record_key[0]:
                        continue
                    if record_key in seen_records:
                        continue
                    seen_records.add(record_key)
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

    for id_no, item in id_seed.items():
        if not item["성별"]:
            item["성별"] = _infer_gender(item["종별목록"])
        item["종별목록"] = sorted(item["종별목록"])
        item["소속목록"] = sorted(item["소속목록"])

    to_cd_final = {}
    for meet_name, values in to_cd_by_meet.items():
        to_cd_final[meet_name] = next(iter(values)) if len(values) == 1 else ""
    return records, id_seed, sorted(winter_ids), to_cd_final, parse_stats


def _collect_inf503_for_ids(session, id_list, refresh, request_gap_seconds, progress, failures):
    total = len(id_list)
    print(f"[inf503] 대상 {total}명")
    for idx, id_no in enumerate(id_list, start=1):
        payload = {"pclassCd": "SK", "idNo": id_no, "pageIndex": "1"}
        html, _ = _fetch_with_cache(
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


def _build_athlete_info_and_score_supplement(id_seed, winter_ids, to_cd_by_meet):
    winter_id_set = set(winter_ids)
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
            if id_no in winter_id_set:
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

        if id_no not in winter_id_set or not html:
            continue
        for row in parse_history(html, id_no):
            meet_name = _norm(row.get("대회명"))
            round_name = _norm(row.get("라운드"))
            if "채점종합" not in round_name:
                continue
            if "동계체" not in meet_name:
                continue
            date_raw = _norm(row.get("일자"))
            date_norm = _normalize_date_text(_norm(row.get("일자_정규화")) or date_raw)
            key = (
                id_no,
                meet_name,
                _norm(row.get("세부종목")),
                round_name,
                _norm(row.get("순위")),
                _norm(row.get("기록")),
                _norm(row.get("소속")),
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
                }
            )

    return athlete_rows, supplement_rows, birth_year_ok, inf503_cache_missing


def _export_full_csv(events, progress):
    base_records, id_seed, winter_ids, to_cd_by_meet, parse_stats = _build_base_records(events)
    athlete_rows, supplement_rows, birth_year_ok, inf503_cache_missing = _build_athlete_info_and_score_supplement(
        id_seed=id_seed,
        winter_ids=winter_ids,
        to_cd_by_meet=to_cd_by_meet,
    )

    existing_keys = {
        (
            _norm(row.get("idNo")),
            _norm(row.get("대회명")),
            _norm(row.get("세부종목")),
            _norm(row.get("라운드")),
            _norm(row.get("순위")),
            _norm(row.get("기록")),
            _norm(row.get("소속")),
        )
        for row in base_records
    }
    merged_records = list(base_records)
    supplement_added = 0
    for row in supplement_rows:
        key = (
            _norm(row.get("idNo")),
            _norm(row.get("대회명")),
            _norm(row.get("세부종목")),
            _norm(row.get("라운드")),
            _norm(row.get("순위")),
            _norm(row.get("기록")),
            _norm(row.get("소속")),
        )
        if key in existing_keys:
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

    _bump_counter(progress, "records_inf310_rows", len(base_records))
    _bump_counter(progress, "records_inf503_score_rows", supplement_added)
    _save_progress(progress)

    print(
        "[export] 기록 {0:,}건 (INF310 {1:,} + INF503 채점종합 추가 {2:,})".format(
            len(merged_records),
            len(base_records),
            supplement_added,
        )
    )
    print(f"[export] 선수 {len(athlete_rows):,}명 / 출생년도 확보 {birth_year_ok:,}명")
    print(f"[export] 동계체전 참가자 idNo {len(winter_ids):,}명 / INF503 캐시 미보유 {inf503_cache_missing:,}명")
    print(
        "[export] INF310 파싱: data row {0:,} / 구분행 {1:,} / 참가자 없음 row {2:,}(결과행 추정 {3:,}) / header 미감지 {4:,}".format(
            parse_stats["inf310_data_row_count"],
            parse_stats["inf310_category_row_count"],
            parse_stats["inf310_row_without_participant_count"],
            parse_stats["inf310_row_without_participant_likely_result_count"],
            parse_stats["inf310_header_missing_call_count"],
        )
    )
    print(
        "[export] 요청 구조: events {0:,}(동계체 {1:,}) / INF202 detail {2:,} / INF301 call {3:,} / INF310 call {4:,}".format(
            parse_stats["events_total"],
            parse_stats["events_winter"],
            parse_stats["inf202_detail_count"],
            parse_stats["inf301_call_count"],
            parse_stats["inf310_call_count"],
        )
    )
    print(
        "[export] INF202 미수집 대회 {0:,}건 (원천 대회정보 공백 {1:,}, 세부종목 미노출 {2:,})".format(
            parse_stats["inf202_empty_event_count"],
            parse_stats["inf202_empty_source_blank_count"],
            parse_stats["inf202_empty_no_schedule_count"],
        )
    )
    return {
        "records_total": len(merged_records),
        "records_inf310": len(base_records),
        "records_inf503_added": supplement_added,
        "athletes_total": len(athlete_rows),
        "birth_year_covered": birth_year_ok,
        "winter_ids": len(winter_ids),
        "inf503_cache_missing": inf503_cache_missing,
        **parse_stats,
    }


def _load_retry_entries():
    return _load_csv_rows(FAILURES_CSV)


def _retry_failure_requests(session, retry_entries, refresh, request_gap_seconds, progress, failures):
    if not retry_entries:
        print(f"[retry] {FAILURES_CSV}에 재시도 대상이 없습니다.")
        return
    print(f"[retry] 대상 {len(retry_entries)}건")
    for idx, row in enumerate(retry_entries, start=1):
        request_key = _norm(row.get("requestKey"))
        request_type = _norm(row.get("requestType"))
        endpoint = _norm(row.get("endpoint"))
        payload_text = _norm(row.get("payloadJson"))
        cache_path_text = _norm(row.get("cachePath"))
        context = _norm(row.get("context"))
        if not request_key or not endpoint or not payload_text or not cache_path_text:
            print(f"[retry {idx}/{len(retry_entries)}] 스킵: 필수 필드 누락 (requestKey={request_key})")
            continue
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            print(f"[retry {idx}/{len(retry_entries)}] 스킵: payloadJson 파싱 실패 (requestKey={request_key})")
            continue
        _fetch_with_cache(
            session,
            request_type=request_type or "unknown",
            request_key=request_key,
            endpoint=endpoint,
            payload=payload,
            cache_path=pathlib.Path(cache_path_text),
            context=context or f"retry={request_key}",
            refresh=refresh,
            request_gap_seconds=request_gap_seconds,
            progress=progress,
            failures=failures,
        )


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

    record_mismatches = []
    info_mismatches = []
    for id_no in resolved_ids:
        old_count = old_records.get(id_no, 0)
        new_count = new_records.get(id_no, 0)
        if old_count != new_count:
            record_mismatches.append((id_no, old_count, new_count))
        old_row = old_info.get(id_no)
        new_row = new_info.get(id_no)
        if old_row is None or new_row is None:
            info_mismatches.append((id_no, "행 누락", "old/new 중 하나가 없음"))
            continue
        for field in info_fields:
            if _norm(old_row.get(field)) != _norm(new_row.get(field)):
                info_mismatches.append((id_no, field, f"old={_norm(old_row.get(field))} / new={_norm(new_row.get(field))}"))

    print(f"[compare] 대상 {len(resolved_ids)}명")
    print(f"[compare] records 건수 불일치 {len(record_mismatches)}건")
    print(f"[compare] athlete_info 불일치 {len(info_mismatches)}건")
    for id_no, old_count, new_count in record_mismatches[:20]:
        print(f"  - records {id_no}: old={old_count}, new={new_count}")
    for id_no, field, message in info_mismatches[:20]:
        print(f"  - info {id_no} [{field}] {message}")
    if record_mismatches or info_mismatches:
        return 1
    print("[compare] 회귀 비교 일치")
    return 0


def _cleanup_raw_cache():
    if not RAW_ROOT_DIR.exists():
        print(f"[cleanup] 캐시 디렉터리가 없습니다: {RAW_ROOT_DIR}")
        return 0
    removed = 0
    for path in RAW_ROOT_DIR.rglob("*.html"):
        path.unlink()
        removed += 1
    for path in sorted(RAW_ROOT_DIR.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if RAW_ROOT_DIR.exists() and not any(RAW_ROOT_DIR.iterdir()):
        RAW_ROOT_DIR.rmdir()
    print(f"[cleanup] raw HTML 삭제 완료: {removed}건")
    return 0


def _finalize_summary(progress, failures, mode, export_summary):
    request_total = int(progress["counters"].get("request_network_attempted", 0))
    failures_remaining = len(failures)
    success_rate = 100.0
    if request_total > 0:
        success_rate = (request_total - failures_remaining) / request_total * 100.0
    summary = {
        "mode": mode,
        "updated_at": _now_iso(),
        "request_network_attempted": request_total,
        "failures_remaining": failures_remaining,
        "success_rate_percent": round(success_rate, 2),
        "meets_95_percent": success_rate >= 95.0,
        "export": export_summary,
    }
    progress["last_summary"] = summary
    _save_progress(progress)
    print(
        "[summary] 요청시도 {0:,}건 / 잔여 실패 {1:,}건 / 성공률 {2:.2f}% / 95% 기준 {3}".format(
            request_total,
            failures_remaining,
            success_rate,
            "충족" if success_rate >= 95.0 else "미충족",
        )
    )
    if failures_remaining:
        print(f"[summary] 실패 목록 잔여 {failures_remaining}건 → {FAILURES_CSV}")
    else:
        print("[summary] 실패 목록 없음")


def _build_arg_parser():
    parser = argparse.ArgumentParser(description="대회 중심( INF201→INF310 ) + 동계체 INF503 보완 전체 수집기")
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

    sub = parser.add_subparsers(dest="command")
    collect_parser = sub.add_parser("collect", help="전수 수집 + 동계체 INF503 보완 + full CSV 생성")
    collect_parser.add_argument("--refresh", action="store_true", help="캐시 무시 후 전체 재수집")

    retry_parser = sub.add_parser("retry-failures", help="실패 요청 재시도 후 full CSV 재생성")
    retry_parser.add_argument("--refresh", action="store_true", help="재시도 시 캐시 무시")

    sub.add_parser("export", help="캐시 기반 full CSV 재생성 (네트워크 요청 없음)")
    sub.add_parser("compare-resolved", help="기존 14명(resolved.csv) 기준 회귀 비교")
    sub.add_parser("cleanup-raw-cache", help="집계 후 raw HTML 캐시 정리")
    return parser


def _prepare_runtime(mode, data_dir, request_gap):
    _configure_data_paths(data_dir)
    progress = _load_progress()
    failures = _load_failures()
    progress["last_mode"] = mode
    progress["request_gap_seconds"] = request_gap
    _save_progress(progress)
    return progress, failures


def _run_collect(args):
    if args.request_gap < 1.0:
        raise ValueError("[error] --request-gap은 1.0 이상이어야 합니다.")
    data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
    progress, failures = _prepare_runtime("collect", data_dir=data_dir, request_gap=args.request_gap)
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
    )

    base_records, _, winter_ids, _, _ = _build_base_records(events)
    print(f"[target] INF310 기반 고유 선수 {len({_norm(r.get('idNo')) for r in base_records if _norm(r.get('idNo'))}):,}명")
    print(f"[target] 동계체전 보완 대상 {len(winter_ids):,}명")
    _collect_inf503_for_ids(
        session,
        id_list=winter_ids,
        refresh=bool(args.refresh),
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
    )

    export_summary = _export_full_csv(events, progress=progress)
    _finalize_summary(progress, failures, mode="collect", export_summary=export_summary)


def _run_retry_failures(args):
    if args.request_gap < 1.0:
        raise ValueError("[error] --request-gap은 1.0 이상이어야 합니다.")
    data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
    progress, failures = _prepare_runtime("retry-failures", data_dir=data_dir, request_gap=args.request_gap)
    print(f"[path] data_dir={DATA_DIR}")

    session = requests.Session()
    retry_entries = _load_retry_entries()
    _retry_failure_requests(
        session,
        retry_entries=retry_entries,
        refresh=bool(args.refresh),
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
    )

    # 실패 요청 재시도 이후, 캐시 기반으로 누락 요청을 이어받아 채운다.
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
    _collect_event_route(
        session,
        events=events,
        refresh=False,
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
    )

    _, _, winter_ids, _, _ = _build_base_records(events)
    _collect_inf503_for_ids(
        session,
        id_list=winter_ids,
        refresh=False,
        request_gap_seconds=args.request_gap,
        progress=progress,
        failures=failures,
    )

    export_summary = _export_full_csv(events, progress=progress)
    _finalize_summary(progress, failures, mode="retry-failures", export_summary=export_summary)


def _run_export(args):
    data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
    progress, failures = _prepare_runtime("export", data_dir=data_dir, request_gap=args.request_gap)
    print(f"[path] data_dir={DATA_DIR}")
    events = _load_events_from_inf201_cache()
    if args.max_events is not None:
        events = events[: max(0, args.max_events)]
    if not events:
        raise FileNotFoundError(f"[error] INF201 캐시가 없습니다: {RAW_INF201_DIR}. 먼저 collect를 실행하세요.")
    export_summary = _export_full_csv(events, progress=progress)
    _finalize_summary(progress, failures, mode="export", export_summary=export_summary)


def main():
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
    except KeyboardInterrupt:
        print("[interrupt] 사용자 중단 감지: 현재까지 저장된 캐시/진행상태로 다음 실행에서 이어받을 수 있습니다.")


if __name__ == "__main__":
    main()
