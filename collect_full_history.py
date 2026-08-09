import argparse
import csv
import json
import os
import pathlib
import time
from datetime import datetime

import requests

from scrape import parse_athlete_info, parse_history

HISTORY_ENDPOINT = "https://result.sports.or.kr/SK/INF503.do"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "splits-history-collector/1.0 (+https://github.com/es-kimo/splits)",
}
TIMEOUT_SECONDS = 20
REQUEST_GAP_SECONDS = 1
RETRY_GAP_SECONDS = 5
MAX_RETRIES = 3

DEFAULT_DATA_DIR = pathlib.Path("data")
DATA_DIR = DEFAULT_DATA_DIR
RAW_HISTORY_DIR = DATA_DIR / "raw" / "history"
ATHLETE_INDEX_CSV = DATA_DIR / "athlete_index.csv"
ID_MERGES_CSV = DATA_DIR / "id_merges.csv"
RESOLVED_CSV = DATA_DIR / "resolved.csv"

PROGRESS_JSON = DATA_DIR / "collect_progress.json"
FAILURES_CSV = DATA_DIR / "collect_failures.csv"
RECORDS_FULL_CSV = DATA_DIR / "records_full.csv"
ATHLETE_INFO_FULL_CSV = DATA_DIR / "athlete_info_full.csv"
RECORDS_CSV = DATA_DIR / "records.csv"
ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"

FAILURE_FIELDS = ["idNo", "이름", "사유", "시도횟수", "최종실패시각"]
ATHLETE_INFO_FIELDS = ["idNo", "이름", "성별", "출생년도", "종별", "소속팀", "팀코드", "시도"]
RECORD_FIELDS = ["idNo", "대회명", "일자", "일자_정규화", "종별", "세부종목", "라운드", "소속", "기록", "순위"]


def _configure_data_paths(base_dir):
    global DATA_DIR
    global RAW_HISTORY_DIR
    global ATHLETE_INDEX_CSV
    global ID_MERGES_CSV
    global RESOLVED_CSV
    global PROGRESS_JSON
    global FAILURES_CSV
    global RECORDS_FULL_CSV
    global ATHLETE_INFO_FULL_CSV
    global RECORDS_CSV
    global ATHLETE_INFO_CSV

    DATA_DIR = pathlib.Path(base_dir).expanduser()
    RAW_HISTORY_DIR = DATA_DIR / "raw" / "history"
    ATHLETE_INDEX_CSV = DATA_DIR / "athlete_index.csv"
    ID_MERGES_CSV = DATA_DIR / "id_merges.csv"
    RESOLVED_CSV = DATA_DIR / "resolved.csv"
    PROGRESS_JSON = DATA_DIR / "collect_progress.json"
    FAILURES_CSV = DATA_DIR / "collect_failures.csv"
    RECORDS_FULL_CSV = DATA_DIR / "records_full.csv"
    ATHLETE_INFO_FULL_CSV = DATA_DIR / "athlete_info_full.csv"
    RECORDS_CSV = DATA_DIR / "records.csv"
    ATHLETE_INFO_CSV = DATA_DIR / "athlete_info.csv"


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _norm(value):
    return str(value or "").strip()


def _history_cache_path(id_no):
    return RAW_HISTORY_DIR / f"{_norm(id_no)}.html"


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


def _load_progress():
    if not PROGRESS_JSON.exists():
        return {"version": 1, "updated_at": "", "last_mode": "", "target_total": 0, "success_ids": [], "failure_ids": [], "last_summary": {}}
    try:
        payload = json.loads(PROGRESS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[warn] {PROGRESS_JSON} 파싱 실패: 새 진행 상태로 시작합니다.")
        return {"version": 1, "updated_at": "", "last_mode": "", "target_total": 0, "success_ids": [], "failure_ids": [], "last_summary": {}}
    payload.setdefault("version", 1)
    payload.setdefault("updated_at", "")
    payload.setdefault("last_mode", "")
    payload.setdefault("target_total", 0)
    payload.setdefault("success_ids", [])
    payload.setdefault("failure_ids", [])
    payload.setdefault("last_summary", {})
    return payload


def _save_progress(progress):
    progress["updated_at"] = _now_iso()
    progress["success_ids"] = sorted(set(_norm(v) for v in progress.get("success_ids", []) if _norm(v)))
    progress["failure_ids"] = sorted(set(_norm(v) for v in progress.get("failure_ids", []) if _norm(v)))
    PROGRESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PROGRESS_JSON.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(PROGRESS_JSON)


def _load_failures():
    items = {}
    for row in _load_csv_rows(FAILURES_CSV):
        id_no = _norm(row.get("idNo"))
        if not id_no:
            continue
        items[id_no] = {
            "idNo": id_no,
            "이름": _norm(row.get("이름")),
            "사유": _norm(row.get("사유")),
            "시도횟수": _norm(row.get("시도횟수")),
            "최종실패시각": _norm(row.get("최종실패시각")),
        }
    return items


def _save_failures(failures_map):
    rows = [failures_map[key] for key in sorted(failures_map.keys())]
    _save_csv_rows(FAILURES_CSV, rows, FAILURE_FIELDS)


def _load_merge_map():
    mapping = {}
    for row in _load_csv_rows(ID_MERGES_CSV):
        sub_id = _norm(row.get("부idNo"))
        main_id = _norm(row.get("주idNo"))
        if sub_id and main_id and sub_id != main_id:
            mapping[sub_id] = main_id
    return mapping


def _resolve_id(mapping, id_no):
    cur = _norm(id_no)
    seen = set()
    while cur in mapping and cur not in seen:
        seen.add(cur)
        cur = mapping[cur]
    return cur


def _build_targets():
    if not ATHLETE_INDEX_CSV.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {ATHLETE_INDEX_CSV}")
    merge_map = _load_merge_map()
    names_by_id = {}
    merged_from_count = 0
    for row in _load_csv_rows(ATHLETE_INDEX_CSV):
        raw_id = _norm(row.get("idNo"))
        if not raw_id:
            continue
        canonical_id = _resolve_id(merge_map, raw_id)
        if canonical_id != raw_id:
            merged_from_count += 1
        name = _norm(row.get("이름"))
        names_by_id.setdefault(canonical_id, set())
        if name:
            names_by_id[canonical_id].add(name)
    target_ids = sorted(names_by_id.keys())
    display_names = {id_no: " | ".join(sorted(names_by_id[id_no])) for id_no in target_ids}
    return target_ids, display_names, merged_from_count, len(merge_map)


def _existing_cache_ids():
    if not RAW_HISTORY_DIR.exists():
        return set()
    ids = set()
    for path in RAW_HISTORY_DIR.glob("*.html"):
        id_no = _norm(path.stem)
        if id_no:
            ids.add(id_no)
    return ids


def _is_retryable_http(status_code):
    return status_code == 429 or status_code >= 500


def _fetch_history_with_retry(session, id_no):
    payload = {"pclassCd": "SK", "idNo": str(id_no), "pageIndex": "1"}
    last_reason = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.post(HISTORY_ENDPOINT, data=payload, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        except requests.Timeout:
            last_reason = "timeout"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_GAP_SECONDS)
                continue
            return None, attempt, last_reason
        except requests.RequestException as exc:
            last_reason = f"network_error: {exc.__class__.__name__}"
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
    return None, MAX_RETRIES, last_reason or "unknown"


def _collect_ids(target_ids, names_by_id, refresh, mode):
    RAW_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    progress = _load_progress()
    failures = _load_failures()

    cache_ids = _existing_cache_ids()
    progress["success_ids"] = sorted(set(progress.get("success_ids", [])).union(cache_ids))
    progress["failure_ids"] = [id_no for id_no in progress.get("failure_ids", []) if id_no in failures]
    progress["target_total"] = len(target_ids)
    progress["last_mode"] = mode
    _save_progress(progress)

    pending_ids = list(target_ids)
    if not refresh:
        pending_ids = [id_no for id_no in target_ids if id_no not in cache_ids]

    requested_count = 0
    success_count = 0
    failure_count = 0

    print(f"[collect] mode={mode} refresh={refresh} 대상 {len(target_ids)}명 / 요청 필요 {len(pending_ids)}명")
    session = requests.Session()

    for idx, id_no in enumerate(pending_ids, start=1):
        name = names_by_id.get(id_no, "")
        requested_count += 1
        html, attempts, reason = _fetch_history_with_retry(session, id_no)
        if html is None:
            failure_count += 1
            failures[id_no] = {
                "idNo": id_no,
                "이름": name,
                "사유": reason,
                "시도횟수": str(attempts),
                "최종실패시각": _now_iso(),
            }
            progress["failure_ids"] = sorted(set(progress.get("failure_ids", [])).union({id_no}))
            progress["success_ids"] = [v for v in progress.get("success_ids", []) if v != id_no]
            _save_failures(failures)
            _save_progress(progress)
            print(f"[{idx}/{len(pending_ids)}] 실패 {name} {id_no} (사유={reason}, 시도={attempts})")
            continue

        _history_cache_path(id_no).write_text(html, encoding="utf-8")
        success_count += 1
        if id_no in failures:
            failures.pop(id_no)
        progress["success_ids"] = sorted(set(progress.get("success_ids", [])).union({id_no}))
        progress["failure_ids"] = [v for v in progress.get("failure_ids", []) if v != id_no]
        _save_failures(failures)
        _save_progress(progress)
        print(f"[{idx}/{len(pending_ids)}] 성공 {name} {id_no} (시도={attempts})")
        time.sleep(REQUEST_GAP_SECONDS)

    cache_after = _existing_cache_ids()
    available_count = len([id_no for id_no in target_ids if id_no in cache_after])
    target_total = len(target_ids)
    success_rate = (available_count / target_total * 100.0) if target_total else 0.0
    meets_threshold = success_rate >= 95.0

    summary = {
        "mode": mode,
        "refresh": refresh,
        "target_total": target_total,
        "requested_count": requested_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "available_count": available_count,
        "success_rate_percent": round(success_rate, 2),
        "meets_95_percent": meets_threshold,
    }
    progress["last_summary"] = summary
    progress["target_total"] = target_total
    progress["success_ids"] = sorted(set(progress.get("success_ids", [])).intersection(set(cache_after)))
    progress["failure_ids"] = sorted(set(progress.get("failure_ids", [])).intersection(set(failures.keys())))
    _save_progress(progress)
    print(
        "[summary] 대상 {0}명 / 캐시 보유 {1}명 / 성공률 {2:.2f}% / 95% 기준 {3}".format(
            target_total,
            available_count,
            success_rate,
            "충족" if meets_threshold else "미충족",
        )
    )
    if failures:
        print(f"[summary] 실패 목록 잔여 {len(failures)}건 → {FAILURES_CSV}")
    else:
        print("[summary] 실패 목록 없음")


def _export_full_csv(target_ids, names_by_id):
    RECORDS_FULL_CSV.parent.mkdir(parents=True, exist_ok=True)
    ATHLETE_INFO_FULL_CSV.parent.mkdir(parents=True, exist_ok=True)

    total_records = 0
    info_count = 0
    missing_ids = []

    with RECORDS_FULL_CSV.open("w", newline="", encoding="utf-8-sig") as records_file, ATHLETE_INFO_FULL_CSV.open(
        "w", newline="", encoding="utf-8-sig"
    ) as info_file:
        records_writer = csv.DictWriter(records_file, fieldnames=RECORD_FIELDS)
        info_writer = csv.DictWriter(info_file, fieldnames=ATHLETE_INFO_FIELDS)
        records_writer.writeheader()
        info_writer.writeheader()

        for id_no in target_ids:
            cache_path = _history_cache_path(id_no)
            if not cache_path.exists():
                missing_ids.append(id_no)
                continue
            html = cache_path.read_text(encoding="utf-8")
            info = parse_athlete_info(html)
            info_writer.writerow(
                {
                    "idNo": id_no,
                    "이름": _norm(info.get("이름")) or _norm(names_by_id.get(id_no)),
                    "성별": _norm(info.get("성별")),
                    "출생년도": _norm(info.get("출생년도")),
                    "종별": _norm(info.get("종별")),
                    "소속팀": _norm(info.get("소속팀")),
                    "팀코드": _norm(info.get("팀코드")),
                    "시도": _norm(info.get("시도")),
                }
            )
            info_count += 1

            rows = parse_history(html, id_no)
            for row in rows:
                records_writer.writerow(
                    {
                        "idNo": _norm(row.get("idNo")),
                        "대회명": _norm(row.get("대회명")),
                        "일자": _norm(row.get("일자")),
                        "일자_정규화": _norm(row.get("일자_정규화")),
                        "종별": _norm(row.get("종별")),
                        "세부종목": _norm(row.get("세부종목")),
                        "라운드": _norm(row.get("라운드")),
                        "소속": _norm(row.get("소속")),
                        "기록": _norm(row.get("기록")),
                        "순위": _norm(row.get("순위")),
                    }
                )
            total_records += len(rows)

    print(f"[export] 선수 {info_count}명 / 기록 {total_records:,}건")
    print(f"[export] 저장 완료: {ATHLETE_INFO_FULL_CSV}")
    print(f"[export] 저장 완료: {RECORDS_FULL_CSV}")
    if missing_ids:
        print(f"[export] 캐시 미보유 {len(missing_ids)}명")
    else:
        print("[export] 전체 대상 캐시 보유")


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

    resolved_ids = []
    for row in _load_csv_rows(RESOLVED_CSV):
        id_no = _norm(row.get("idNo"))
        if id_no:
            resolved_ids.append(id_no)
    resolved_ids = sorted(set(resolved_ids))
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


def _load_retry_ids():
    failure_rows = _load_csv_rows(FAILURES_CSV)
    ids = []
    for row in failure_rows:
        id_no = _norm(row.get("idNo"))
        if id_no:
            ids.append(id_no)
    return sorted(set(ids))


def _build_arg_parser():
    parser = argparse.ArgumentParser(description="전체 선수 INF503 기록 수집기")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="입출력 데이터 디렉터리 (기본: ./data, 또는 환경변수 SPLITS_DATA_DIR)",
    )
    subparsers = parser.add_subparsers(dest="command")

    collect_parser = subparsers.add_parser("collect", help="전체 대상 수집 후 full CSV 생성")
    collect_parser.add_argument("--refresh", action="store_true", help="전체 재수집")

    retry_parser = subparsers.add_parser("retry-failures", help="실패 목록만 재시도 후 full CSV 생성")
    retry_parser.add_argument("--refresh", action="store_true", help="실패 목록도 캐시 무시 후 재수집")

    subparsers.add_parser("export", help="캐시 기반 full CSV만 재생성")
    subparsers.add_parser("compare-resolved", help="기존 14명(resolved.csv) 기준 회귀 비교")
    return parser


def main():
    parser = _build_arg_parser()
    args = parser.parse_args()
    command = args.command or "collect"
    data_dir = args.data_dir or os.environ.get("SPLITS_DATA_DIR", str(DEFAULT_DATA_DIR))
    _configure_data_paths(data_dir)
    print(f"[path] data_dir={DATA_DIR}")

    target_ids, names_by_id, merged_from_count, merge_edges = _build_targets()
    print(f"[target] athlete_index 고유 대상 {len(target_ids)}명 / id_merges 매핑 {merge_edges}건 / 병합 치환 원본행 {merged_from_count}건")

    try:
        if command == "collect":
            _collect_ids(target_ids, names_by_id, refresh=bool(args.refresh), mode="collect")
            _export_full_csv(target_ids, names_by_id)
            return
        if command == "retry-failures":
            retry_ids = _load_retry_ids()
            if not retry_ids:
                print(f"[retry] {FAILURES_CSV}에 재시도 대상이 없습니다.")
            else:
                retry_name_map = {id_no: names_by_id.get(id_no, "") for id_no in retry_ids}
                _collect_ids(retry_ids, retry_name_map, refresh=bool(args.refresh), mode="retry-failures")
            _export_full_csv(target_ids, names_by_id)
            return
        if command == "export":
            _export_full_csv(target_ids, names_by_id)
            return
        if command == "compare-resolved":
            raise SystemExit(_compare_resolved())
        raise SystemExit(f"[error] 알 수 없는 명령어: {command}")
    except KeyboardInterrupt:
        print("[interrupt] 사용자 중단 감지: 현재까지 저장된 캐시/진행상태로 다음 실행에서 이어받을 수 있습니다.")


if __name__ == "__main__":
    main()
