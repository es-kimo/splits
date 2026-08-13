import argparse
import csv
import json
import pathlib
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://result.sports.or.kr"
INF201_ENDPOINT = f"{BASE_URL}/SK/INF201.do"
INF202_ENDPOINT = f"{BASE_URL}/SK/INF202.do"
INF301_ENDPOINT = f"{BASE_URL}/SK/INF301.do"
INF310_ENDPOINT = f"{BASE_URL}/SK/INF310.do"
INF503_ENDPOINT = f"{BASE_URL}/SK/INF503.do"

HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
SESSION = requests.Session()

PARTICIPANT_ID_RE = re.compile(r"fn\w*History\(\s*['\"]?(\d{6,})['\"]?\s*\)")
DIGIT_RE = re.compile(r"\d+")
MEET_TEXT_RE = re.compile(r"[^0-9a-z가-힣]+")


def _base_payload():
    return {
        "classCd": "",
        "toCd": "",
        "pclassCd": "SK",
        "eventCd": "",
        "movSeq": "",
        "teamCd": "",
        "idNo": "",
        "pageIndex": "1",
        "searchKeyword": "",
        "searchAppYn": "",
        "kindCd": "",
        "detailClassCd": "",
        "searchKindCd": "",
        "searchDetailClassCd": "",
        "baseClassCd": "",
        "baseClassNm": "",
        "rhCd": "",
        "rhNm": "",
        "pcntGbn": "",
        "useGbn": "",
        "searchApprovalGb": "",
        "searchEventNmGb": "",
        "searchEntryGb": "",
        "searchEventNm": "",
        "searchStartDt": "",
        "searchEndDt": "",
        "searchPlaceNm": "",
        "platform": "pc",
        "nslRound": "",
        "groupCd": "",
        "gameCd": "",
        "gubun": "",
    }


def _post(url, payload):
    try:
        resp = SESSION.post(url, data=payload, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:
        print(f"[error] 요청 실패: {url}")
        raise
    return resp.text


def _norm(value):
    return str(value or "").strip()


def _norm_meet(value):
    text = _norm(value).lower()
    return MEET_TEXT_RE.sub("", text)


def _same_meet(left, right):
    lval = _norm_meet(left)
    rval = _norm_meet(right)
    if not lval or not rval:
        return False
    if lval == rval:
        return True
    return (len(lval) >= 8 and lval in rval) or (len(rval) >= 8 and rval in lval)


def _parse_js_args(onclick, fn_name):
    text = onclick or ""
    idx = text.find(f"{fn_name}(")
    if idx < 0:
        return None
    start = idx + len(fn_name) + 1
    end = text.rfind(")")
    if end < start:
        return None
    arg_text = text[start:end]
    args, buf, quote = [], [], None
    for ch in arg_text:
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == ",":
            args.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    args.append("".join(buf).strip())
    return args


def _find_table_by_caption(soup, caption_text):
    for table in soup.find_all("table"):
        caption = table.find("caption")
        if caption and caption.get_text(" ", strip=True) == caption_text:
            return table
    return None


def _read_pairs_from_table(table):
    pairs = {}
    if not table:
        return pairs
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        values = [c.get_text(" ", strip=True) for c in cells]
        for idx in range(0, len(values) - 1, 2):
            key = _norm(values[idx])
            val = _norm(values[idx + 1])
            if key:
                pairs[key] = val
    return pairs


def _extract_result_headers(table):
    headers = []
    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        if not ths:
            continue
        if len(ths) == 1 and ths[0].get("colspan"):
            continue
        values = [_norm(th.get_text(" ", strip=True)) for th in ths]
        if "순위" in values and ("성명" in values or "선수명" in values):
            headers = values
            break
    return headers


def _extract_participant_id_and_name(tr, row_map):
    id_no = None
    name = _norm(row_map.get("성명") or row_map.get("선수명"))
    anchor = tr.find("a")
    if anchor:
        if not name:
            name = _norm(anchor.get_text(" ", strip=True))
        for raw in [anchor.get("href", ""), anchor.get("onclick", ""), tr.get("onclick", "")]:
            m = PARTICIPANT_ID_RE.search(raw or "")
            if m:
                id_no = m.group(1)
                break
    if not id_no:
        for node in tr.find_all(attrs={"onclick": True}):
            m = PARTICIPANT_ID_RE.search(node.get("onclick", "") or "")
            if m:
                id_no = m.group(1)
                break
    return id_no, name


def _parse_inf503_history(html, id_no):
    soup = BeautifulSoup(html, "html.parser")
    table = _find_table_by_caption(soup, "대회참가이력")
    if not table:
        return []
    rows = []
    current_meet = ""
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) == 1:
            current_meet = _norm(tds[0].get_text(" ", strip=True))
            continue
        if len(tds) != 7:
            continue
        values = [_norm(td.get_text(" ", strip=True)) for td in tds]
        rows.append(
            {
                "idNo": _norm(id_no),
                "대회명": current_meet,
                "일자": values[0],
                "종별": values[1],
                "세부종목": values[2],
                "라운드": values[3],
                "소속": values[4],
                "기록": values[5],
                "순위": values[6],
            }
        )
    return rows


def _payload_for_inf503(id_no):
    return {"pclassCd": "SK", "idNo": _norm(id_no), "pageIndex": "1"}


def fetch_inf201_events(page_index=1):
    payload = _base_payload()
    payload["pageIndex"] = str(page_index)
    html = _post(INF201_ENDPOINT, payload)
    soup = BeautifulSoup(html, "html.parser")
    default_search_app_yn = ""
    search_app_input = soup.find("input", attrs={"name": "searchAppYn"})
    if search_app_input and search_app_input.has_attr("value"):
        default_search_app_yn = _norm(search_app_input.get("value", ""))
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
    if not events:
        raise RuntimeError("INF201에서 대회 목록을 찾지 못했습니다.")
    return events


def fetch_inf202_bundle(class_cd, to_cd, search_app_yn=""):
    payload = _base_payload()
    payload.update({"classCd": class_cd, "toCd": to_cd, "searchAppYn": search_app_yn})
    html = _post(INF202_ENDPOINT, payload)
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
        m = DIGIT_RE.search(participant_text)
        participant_count = int(m.group(0)) if m else None
        details.append(
            {
                "kindCd": kind_cd,
                "detailClassCd": detail_class_cd,
                "종별": _norm(tds[0].get_text(" ", strip=True)),
                "세부종목": _norm(tds[1].get_text(" ", strip=True)),
                "구분": _norm(tds[2].get_text(" ", strip=True)),
                "참가선수표시": participant_text,
                "참가선수수": participant_count,
            }
        )
    if not details:
        raise RuntimeError(f"INF202 세부종목 내역을 찾지 못했습니다. classCd={class_cd}, toCd={to_cd}")
    return {"eventInfo": event_info, "details": details}


def fetch_inf202_details(class_cd, to_cd, search_app_yn=""):
    return fetch_inf202_bundle(class_cd, to_cd, search_app_yn=search_app_yn)["details"]


def fetch_inf301_result_calls(class_cd, to_cd, search_app_yn, kind_cd, detail_class_cd):
    payload = _base_payload()
    payload.update(
        {
            "classCd": class_cd,
            "toCd": to_cd,
            "kindCd": kind_cd,
            "detailClassCd": detail_class_cd,
            "searchKindCd": kind_cd,
            "searchDetailClassCd": detail_class_cd,
            "searchAppYn": search_app_yn,
        }
    )
    html = _post(INF301_ENDPOINT, payload)
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


def fetch_inf310_result_rows(class_cd, to_cd, search_app_yn, kind_cd, detail_class_cd, result_call):
    payload = _base_payload()
    payload.update(
        {
            "classCd": class_cd,
            "toCd": to_cd,
            "kindCd": kind_cd,
            "detailClassCd": detail_class_cd,
            "searchKindCd": kind_cd,
            "searchDetailClassCd": detail_class_cd,
            "searchAppYn": search_app_yn,
            "baseClassCd": result_call["baseClassCd"],
            "rhCd": result_call["rhCd"],
            "rhNm": result_call["rhNm"],
            "baseClassNm": result_call["baseClassNm"],
            "pcntGbn": result_call["pcntGbn"],
            "useGbn": result_call["useGbn"],
        }
    )
    html = _post(INF310_ENDPOINT, payload)
    soup = BeautifulSoup(html, "html.parser")
    table = _find_table_by_caption(soup, "경기결과")
    if not table:
        return []
    headers = _extract_result_headers(table)
    rows = []
    seen = set()
    current_round = _norm(result_call.get("rhNm"))
    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        if len(ths) == 1 and ths[0].get("colspan"):
            header_round = _norm(ths[0].get_text(" ", strip=True))
            if header_round:
                current_round = header_round
            continue
        tds = tr.find_all("td")
        if not tds:
            continue
        values = [_norm(td.get_text(" ", strip=True)) for td in tds]
        row_map = {}
        for idx, value in enumerate(values):
            key = headers[idx] if idx < len(headers) and headers[idx] else f"col{idx}"
            row_map[key] = value
        id_no, name = _extract_participant_id_and_name(tr, row_map)
        if not id_no:
            continue
        rank = _norm(row_map.get("순위"))
        bib = _norm(row_map.get("BIB"))
        lane = _norm(row_map.get("레인"))
        grade = _norm(row_map.get("학년"))
        record = _norm(row_map.get("기록"))
        reason = _norm(row_map.get("사유"))
        record_gap = _norm(row_map.get("기록차"))
        unique_key = (id_no, name, current_round, rank, record, result_call["baseClassCd"], result_call["rhCd"])
        if unique_key in seen:
            continue
        seen.add(unique_key)
        rows.append(
            {
                "idNo": id_no,
                "이름": name,
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
    return rows


def collect_participants_for_event(class_cd, to_cd, search_app_yn="", sleep_seconds=0.2):
    bundle = fetch_inf202_bundle(class_cd, to_cd, search_app_yn=search_app_yn)
    details = bundle["details"]
    event_info = bundle["eventInfo"]
    occurrences = []
    unique = {}
    seen_result_calls = set()
    inf301_calls = 0
    inf310_calls = 0
    pcnt_counts = {}
    kind_counts = {}
    detail_tracker = {}
    for detail in details:
        detail_key = (detail["kindCd"], detail["detailClassCd"])
        detail_tracker[detail_key] = {
            "kindCd": detail["kindCd"],
            "detailClassCd": detail["detailClassCd"],
            "종별": detail["종별"],
            "세부종목": detail["세부종목"],
            "구분": detail["구분"],
            "INF202_참가선수수": detail["참가선수수"],
            "INF301_라운드목록": set(),
            "INF301_채점종합노출": False,
            "INF310_고유id": set(),
        }
        result_calls = fetch_inf301_result_calls(
            class_cd=class_cd,
            to_cd=to_cd,
            search_app_yn=search_app_yn,
            kind_cd=detail["kindCd"],
            detail_class_cd=detail["detailClassCd"],
        )
        inf301_calls += 1
        kind_counts[detail["kindCd"]] = kind_counts.get(detail["kindCd"], 0) + 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        for call in result_calls:
            detail_tracker[detail_key]["INF301_라운드목록"].add(call["rhNm"])
            if "채점종합" in call["rhNm"]:
                detail_tracker[detail_key]["INF301_채점종합노출"] = True
            pcnt = call["pcntGbn"] or "(empty)"
            pcnt_counts[pcnt] = pcnt_counts.get(pcnt, 0) + 1
            key = (
                detail["kindCd"],
                detail["detailClassCd"],
                call["baseClassCd"],
                call["rhCd"],
                call["rhNm"],
                call["baseClassNm"],
                call["pcntGbn"],
                call["useGbn"],
            )
            if key in seen_result_calls:
                continue
            seen_result_calls.add(key)
            rows = fetch_inf310_result_rows(
                class_cd=class_cd,
                to_cd=to_cd,
                search_app_yn=search_app_yn,
                kind_cd=detail["kindCd"],
                detail_class_cd=detail["detailClassCd"],
                result_call=call,
            )
            inf310_calls += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            for row in rows:
                occurrence = {
                    "idNo": row["idNo"],
                    "이름": row["이름"],
                    "kindCd": detail["kindCd"],
                    "detailClassCd": detail["detailClassCd"],
                    "종별": detail["종별"],
                    "세부종목": detail["세부종목"],
                    "구분": detail["구분"],
                    "baseClassCd": call["baseClassCd"],
                    "baseClassNm": call["baseClassNm"],
                    "rhCd": call["rhCd"],
                    "rhNm": call["rhNm"],
                    "pcntGbn": call["pcntGbn"],
                    "useGbn": call["useGbn"],
                    "라운드": row["라운드"],
                    "순위": row["순위"],
                    "기록": row["기록"],
                    "학년": row["학년"],
                    "레인": row["레인"],
                    "BIB": row["BIB"],
                    "사유": row["사유"],
                    "기록차": row["기록차"],
                }
                occurrences.append(occurrence)
                detail_tracker[detail_key]["INF310_고유id"].add(row["idNo"])
                if row["idNo"] not in unique:
                    unique[row["idNo"]] = {
                        "idNo": row["idNo"],
                        "이름": row["이름"],
                        "출현건수": 0,
                        "세부종목": set(),
                    }
                unique[row["idNo"]]["출현건수"] += 1
                unique[row["idNo"]]["세부종목"].add((detail["kindCd"], detail["detailClassCd"]))
    unique_rows = []
    for row in unique.values():
        unique_rows.append(
            {
                "idNo": row["idNo"],
                "이름": row["이름"],
                "출현건수": row["출현건수"],
                "세부종목수": len(row["세부종목"]),
            }
        )
    unique_rows.sort(key=lambda x: x["idNo"])
    detail_metrics = []
    for key in sorted(detail_tracker.keys()):
        item = detail_tracker[key]
        inf202_count = item["INF202_참가선수수"]
        inf310_count = len(item["INF310_고유id"])
        diff = None if inf202_count is None else inf202_count - inf310_count
        detail_metrics.append(
            {
                "kindCd": item["kindCd"],
                "detailClassCd": item["detailClassCd"],
                "종별": item["종별"],
                "세부종목": item["세부종목"],
                "구분": item["구분"],
                "INF202_참가선수수": inf202_count,
                "INF310_고유id수": inf310_count,
                "A_참가인원차이_INF202-INF310": diff,
                "INF301_라운드목록": " | ".join(sorted(v for v in item["INF301_라운드목록"] if v)),
                "INF301_채점종합노출": "Y" if item["INF301_채점종합노출"] else "N",
            }
        )
    return {
        "eventInfo": event_info,
        "details": details,
        "detail_metrics": detail_metrics,
        "occurrences": occurrences,
        "participants": unique_rows,
        "stats": {
            "inf202_detail_count": len(details),
            "inf301_call_count": inf301_calls,
            "inf310_call_count": inf310_calls,
            "unique_result_call_count": len(seen_result_calls),
            "occurrence_count": len(occurrences),
            "unique_id_count": len(unique_rows),
            "kindCd_counts": dict(sorted(kind_counts.items())),
            "pcntGbn_counts": dict(sorted(pcnt_counts.items())),
            "채점종합노출_세부종목수": sum(1 for row in detail_metrics if row["INF301_채점종합노출"] == "Y"),
        },
    }


def _write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_csv_rows(path):
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _load_merge_map(data_dir):
    mapping = {}
    merge_csv = data_dir / "id_merges.csv"
    for row in _load_csv_rows(merge_csv):
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


def _load_surname_ids(data_dir, merge_map):
    rows = _load_csv_rows(data_dir / "athlete_index.csv")
    if not rows:
        raise FileNotFoundError(f"[error] 파일이 없습니다: {data_dir / 'athlete_index.csv'}")
    out = set()
    for row in rows:
        id_no = _resolve_id(merge_map, _norm(row.get("idNo")))
        if id_no:
            out.add(id_no)
    return out


def _load_public_figure_ids(data_dir, merge_map):
    rows = _load_csv_rows(data_dir / "public_figures.csv")
    out = set()
    for row in rows:
        if _norm(row.get("상태", "active")) != "active":
            continue
        id_no = _resolve_id(merge_map, _norm(row.get("idNo")))
        if id_no:
            out.add(id_no)
    return out


def _pick_records_source(data_dir):
    preferred = [data_dir / "records_full.csv", data_dir / "records.csv"]
    for path in preferred:
        if path.exists():
            return path
    return None


def _build_records_index(records_path, merge_map):
    by_id = {}
    meet_norms_by_id = {}
    with records_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            id_no = _resolve_id(merge_map, _norm(row.get("idNo")))
            if not id_no:
                continue
            item = {
                "idNo": id_no,
                "대회명": _norm(row.get("대회명")),
                "세부종목": _norm(row.get("세부종목")),
                "라운드": _norm(row.get("라운드")),
                "기록": _norm(row.get("기록")),
                "순위": _norm(row.get("순위")),
            }
            by_id.setdefault(id_no, []).append(item)
            meet_norm = _norm_meet(item["대회명"])
            if meet_norm:
                meet_norms_by_id.setdefault(id_no, set()).add(meet_norm)
    return by_id, meet_norms_by_id


def _event_tuple_from_occurrence(row):
    return (
        _norm_meet(row.get("baseClassNm") or row.get("세부종목")),
        _norm_meet(row.get("라운드") or row.get("rhNm")),
        _norm(row.get("순위")),
        _norm(row.get("기록")),
    )


def _event_tuple_from_record(row):
    return (
        _norm_meet(row.get("세부종목")),
        _norm_meet(row.get("라운드")),
        _norm(row.get("순위")),
        _norm(row.get("기록")),
    )


def _classify_with_records(id_no, event_name, records_by_id, meet_norms_by_id):
    rows = records_by_id.get(id_no, [])
    if not rows:
        return "no_history", 0
    target = _norm_meet(event_name)
    meet_norms = meet_norms_by_id.get(id_no, set())
    matched = False
    for value in meet_norms:
        if _same_meet(target, value):
            matched = True
            break
    if matched:
        return "has_target_meet_record", len(rows)
    return "other_meets_only", len(rows)


def _live_inf503_history_rows(id_no, cache_dir, refresh=False):
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{id_no}.html"
    if cache_path.exists() and not refresh:
        html = cache_path.read_text(encoding="utf-8")
    else:
        html = _post(INF503_ENDPOINT, _payload_for_inf503(id_no))
        cache_path.write_text(html, encoding="utf-8")
    return _parse_inf503_history(html, id_no)


def _parse_event_spec(text):
    parts = [p.strip() for p in (text or "").split(",")]
    if len(parts) < 4:
        raise ValueError("--event 형식 오류: classCd,toCd,searchAppYn,대회명")
    class_cd = parts[0]
    to_cd = parts[1]
    search_app_yn = parts[2]
    event_name = ",".join(parts[3:]).strip()
    if not class_cd or not to_cd or not event_name:
        raise ValueError("--event 값 누락: classCd,toCd,searchAppYn,대회명")
    return {"classCd": class_cd, "toCd": to_cd, "searchAppYn": search_app_yn, "eventName": event_name}


def _resolve_event_from_args(args):
    if args.class_cd and args.to_cd:
        return {
            "classCd": args.class_cd,
            "toCd": args.to_cd,
            "searchAppYn": args.search_app_yn or "",
            "대회명": args.event_name or "",
            "pageIndex": "",
        }
    if args.event_index is None:
        raise ValueError("--class-cd/--to-cd 또는 --event-index 중 하나는 반드시 지정해야 합니다.")
    events = fetch_inf201_events(page_index=args.event_page)
    index = args.event_index - 1
    if index < 0 or index >= len(events):
        raise ValueError(f"--event-index 범위 오류: 1~{len(events)}")
    return events[index]


def cmd_events(args):
    events = fetch_inf201_events(page_index=args.page)
    print(f"INF201 page {args.page}: {len(events)}개 대회")
    for i, event in enumerate(events, start=1):
        print(
            f"{i}. classCd={event['classCd']} toCd={event['toCd']} "
            f"searchAppYn={event['searchAppYn'] or '-'} | {event['대회명']} | {event['기간']} | {event['장소']}"
        )


def cmd_collect(args):
    event = _resolve_event_from_args(args)
    class_cd = event["classCd"]
    to_cd = event["toCd"]
    search_app_yn = event["searchAppYn"]
    event_name = event.get("대회명", "")
    print(f"[start] classCd={class_cd}, toCd={to_cd}, searchAppYn={search_app_yn or '-'}")
    if event_name:
        print(f"[event] {event_name}")
    result = collect_participants_for_event(
        class_cd=class_cd,
        to_cd=to_cd,
        search_app_yn=search_app_yn,
        sleep_seconds=args.sleep,
    )
    participants = result["participants"]
    occurrences = result["occurrences"]
    detail_metrics = result["detail_metrics"]
    stats = result["stats"]
    if not participants:
        raise RuntimeError("참가자 idNo를 추출하지 못했습니다.")
    out_dir = pathlib.Path(args.out_dir)
    unique_path = out_dir / f"event_{class_cd}_{to_cd}_participants.csv"
    occ_path = out_dir / f"event_{class_cd}_{to_cd}_participant_occurrences.csv"
    detail_path = out_dir / f"event_{class_cd}_{to_cd}_detail_metrics.csv"
    _write_csv(unique_path, participants, ["idNo", "이름", "출현건수", "세부종목수"])
    _write_csv(
        occ_path,
        occurrences,
        [
            "idNo",
            "이름",
            "kindCd",
            "detailClassCd",
            "종별",
            "세부종목",
            "구분",
            "baseClassCd",
            "baseClassNm",
            "rhCd",
            "rhNm",
            "pcntGbn",
            "useGbn",
            "라운드",
            "순위",
            "기록",
            "학년",
            "레인",
            "BIB",
            "사유",
            "기록차",
        ],
    )
    _write_csv(
        detail_path,
        detail_metrics,
        [
            "kindCd",
            "detailClassCd",
            "종별",
            "세부종목",
            "구분",
            "INF202_참가선수수",
            "INF310_고유id수",
            "A_참가인원차이_INF202-INF310",
            "INF301_라운드목록",
            "INF301_채점종합노출",
        ],
    )
    print(
        "[done] INF202 세부종목 {0}개 / INF301 호출 {1}회 / INF310 호출 {2}회 / 결과호출 키 {3}개".format(
            stats["inf202_detail_count"],
            stats["inf301_call_count"],
            stats["inf310_call_count"],
            stats["unique_result_call_count"],
        )
    )
    print(f"[done] 참가자 행 {stats['occurrence_count']}건 / 고유 idNo {stats['unique_id_count']}개")
    print(f"[done] kindCd 분포: {stats['kindCd_counts']}")
    print(f"[done] pcntGbn 분포: {stats['pcntGbn_counts']}")
    print(f"[done] INF301 채점종합 노출 세부종목 수: {stats['채점종합노출_세부종목수']}")
    print(f"[ok] 저장: {unique_path}")
    print(f"[ok] 저장: {occ_path}")
    print(f"[ok] 저장: {detail_path}")


def cmd_validate_route(args):
    specs = [_parse_event_spec(raw) for raw in args.event]
    if len(specs) != 3:
        raise ValueError("--event는 정확히 3개를 지정해야 합니다 (대형/중형/소형 표본).")
    data_dir = pathlib.Path(args.data_dir)
    out_root = pathlib.Path(args.out_dir) if args.out_dir else data_dir / "route_validation"
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    merge_map = _load_merge_map(data_dir)
    surname_ids = _load_surname_ids(data_dir, merge_map)
    public_figure_ids = _load_public_figure_ids(data_dir, merge_map)
    records_source = _pick_records_source(pathlib.Path(args.compare_data_dir))
    records_by_id = {}
    meet_norms_by_id = {}
    unresolved_notes = []
    if records_source:
        print(f"[info] 비교 원천 사용: {records_source}")
        records_by_id, meet_norms_by_id = _build_records_index(records_source, merge_map)
    else:
        unresolved_notes.append("records_full.csv/records.csv가 없어 C·D 일부 판정이 제한됩니다.")
        if not args.allow_live_inf503:
            unresolved_notes.append("--allow-live-inf503 미지정으로 INF503 실시간 보강을 수행하지 않았습니다.")

    all_a_rows = []
    all_b_rows = []
    all_c_rows = []
    all_d_rows = []
    event_summaries = []
    harmful_missing_total = 0
    live_cache_dir = run_dir / "inf503_cache"

    for index, spec in enumerate(specs, start=1):
        class_cd = spec["classCd"]
        to_cd = spec["toCd"]
        search_app_yn = spec["searchAppYn"]
        event_name = spec["eventName"]
        event_key = f"{class_cd}_{to_cd}"
        event_dir = run_dir / f"event_{event_key}"
        event_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/3] 표본 수집 시작: classCd={class_cd}, toCd={to_cd}, searchAppYn={search_app_yn or '-'} | {event_name}")
        result = collect_participants_for_event(
            class_cd=class_cd,
            to_cd=to_cd,
            search_app_yn=search_app_yn,
            sleep_seconds=args.sleep,
        )
        participants = result["participants"]
        occurrences = result["occurrences"]
        detail_metrics = result["detail_metrics"]
        stats = result["stats"]

        _write_csv(event_dir / "participants.csv", participants, ["idNo", "이름", "출현건수", "세부종목수"])
        _write_csv(
            event_dir / "occurrences.csv",
            occurrences,
            [
                "idNo",
                "이름",
                "kindCd",
                "detailClassCd",
                "종별",
                "세부종목",
                "구분",
                "baseClassCd",
                "baseClassNm",
                "rhCd",
                "rhNm",
                "pcntGbn",
                "useGbn",
                "라운드",
                "순위",
                "기록",
                "학년",
                "레인",
                "BIB",
                "사유",
                "기록차",
            ],
        )
        _write_csv(
            event_dir / "detail_metrics.csv",
            detail_metrics,
            [
                "kindCd",
                "detailClassCd",
                "종별",
                "세부종목",
                "구분",
                "INF202_참가선수수",
                "INF310_고유id수",
                "A_참가인원차이_INF202-INF310",
                "INF301_라운드목록",
                "INF301_채점종합노출",
            ],
        )

        event_ids = set()
        for row in participants:
            canonical = _resolve_id(merge_map, _norm(row.get("idNo")))
            if canonical:
                event_ids.add(canonical)

        intersection = sorted(event_ids.intersection(surname_ids))
        event_minus = sorted(event_ids - surname_ids)
        surname_minus = sorted(surname_ids - event_ids)
        b_row = {
            "eventKey": event_key,
            "대회명": event_name,
            "대회경로_id수": len(event_ids),
            "성씨경로_id수": len(surname_ids),
            "교집합": len(intersection),
            "대회경로-성씨경로": len(event_minus),
            "성씨경로-대회경로": len(surname_minus),
        }
        all_b_rows.append(b_row)

        c_counts = {"no_history": 0, "has_target_meet_record": 0, "other_meets_only": 0, "unknown": 0}
        if surname_minus:
            if records_by_id:
                for id_no in surname_minus:
                    category, rec_count = _classify_with_records(id_no, event_name, records_by_id, meet_norms_by_id)
                    c_counts[category] = c_counts.get(category, 0) + 1
                    all_c_rows.append(
                        {
                            "eventKey": event_key,
                            "대회명": event_name,
                            "idNo": id_no,
                            "분류": category,
                            "기록건수": rec_count,
                        }
                    )
            elif args.allow_live_inf503:
                if len(surname_minus) > args.live_inf503_max:
                    raise RuntimeError(
                        f"[error] INF503 실시간 분류 한도 초과: {len(surname_minus)}명 > --live-inf503-max {args.live_inf503_max}"
                    )
                for idx_live, id_no in enumerate(surname_minus, start=1):
                    rows = _live_inf503_history_rows(id_no=id_no, cache_dir=live_cache_dir, refresh=bool(args.refresh_live_inf503))
                    if args.live_inf503_sleep > 0 and idx_live < len(surname_minus):
                        time.sleep(args.live_inf503_sleep)
                    if not rows:
                        category = "no_history"
                    elif any(_same_meet(row.get("대회명", ""), event_name) for row in rows):
                        category = "has_target_meet_record"
                    else:
                        category = "other_meets_only"
                    c_counts[category] = c_counts.get(category, 0) + 1
                    all_c_rows.append(
                        {
                            "eventKey": event_key,
                            "대회명": event_name,
                            "idNo": id_no,
                            "분류": category,
                            "기록건수": len(rows),
                        }
                    )
            else:
                c_counts["unknown"] = len(surname_minus)
                for id_no in surname_minus:
                    all_c_rows.append(
                        {
                            "eventKey": event_key,
                            "대회명": event_name,
                            "idNo": id_no,
                            "분류": "unknown",
                            "기록건수": "",
                        }
                    )
        harmful_missing = c_counts.get("has_target_meet_record", 0)
        harmful_missing_total += harmful_missing

        public_in_event = sorted(event_ids.intersection(public_figure_ids))
        d_counts = {"match": 0, "match_except_score_round": 0, "mismatch": 0, "baseline_missing": 0, "baseline_meet_not_found": 0}
        occurrences_by_id = {}
        for row in occurrences:
            cid = _resolve_id(merge_map, _norm(row.get("idNo")))
            if cid:
                occurrences_by_id.setdefault(cid, []).append(row)
        for id_no in public_in_event:
            event_rows = occurrences_by_id.get(id_no, [])
            event_tuples = set(_event_tuple_from_occurrence(row) for row in event_rows)
            if not records_by_id:
                status = "baseline_missing"
                baseline_tuples = set()
                baseline_score_only_tuples = set()
            else:
                baseline_rows = [row for row in records_by_id.get(id_no, []) if _same_meet(row.get("대회명", ""), event_name)]
                baseline_tuples = set(_event_tuple_from_record(row) for row in baseline_rows)
                baseline_core_tuples = set(_event_tuple_from_record(row) for row in baseline_rows if "채점종합" not in _norm(row.get("라운드")))
                baseline_score_only_tuples = set(_event_tuple_from_record(row) for row in baseline_rows if "채점종합" in _norm(row.get("라운드")))
                if not baseline_rows:
                    status = "baseline_meet_not_found"
                elif event_tuples == baseline_tuples:
                    status = "match"
                elif event_tuples == baseline_core_tuples and baseline_score_only_tuples:
                    status = "match_except_score_round"
                else:
                    status = "mismatch"
            d_counts[status] = d_counts.get(status, 0) + 1
            all_d_rows.append(
                {
                    "eventKey": event_key,
                    "대회명": event_name,
                    "idNo": id_no,
                    "상태": status,
                    "대회경로_튜플수": len(event_tuples),
                    "기존데이터_튜플수": len(baseline_tuples),
                    "기존데이터_채점종합튜플수": len(baseline_score_only_tuples),
                }
            )

        a_mismatch_count = sum(1 for row in detail_metrics if row["A_참가인원차이_INF202-INF310"] not in (0, None))
        for row in detail_metrics:
            all_a_rows.append({"eventKey": event_key, "대회명": event_name, **row})
        event_summary = {
            "eventKey": event_key,
            "대회명": event_name,
            "classCd": class_cd,
            "toCd": to_cd,
            "searchAppYn": search_app_yn,
            "A_세부종목_불일치수": a_mismatch_count,
            "B_교집합": len(intersection),
            "B_대회경로-성씨경로": len(event_minus),
            "B_성씨경로-대회경로": len(surname_minus),
            "C_no_history": c_counts.get("no_history", 0),
            "C_has_target_meet_record": c_counts.get("has_target_meet_record", 0),
            "C_other_meets_only": c_counts.get("other_meets_only", 0),
            "D_match": d_counts.get("match", 0),
            "D_match_except_score_round": d_counts.get("match_except_score_round", 0),
            "D_mismatch": d_counts.get("mismatch", 0),
            "D_baseline_missing": d_counts.get("baseline_missing", 0),
            "D_baseline_meet_not_found": d_counts.get("baseline_meet_not_found", 0),
            "kindCd_counts": stats["kindCd_counts"],
            "pcntGbn_counts": stats["pcntGbn_counts"],
            "INF301_채점종합노출_세부종목수": stats["채점종합노출_세부종목수"],
            "요청수_INF202": stats["inf202_detail_count"],
            "요청수_INF301": stats["inf301_call_count"],
            "요청수_INF310": stats["inf310_call_count"],
        }
        event_summaries.append(event_summary)
        _write_json(event_dir / "summary.json", event_summary)
        print(f"[ok] 표본 완료: {event_name} | 핵심손실(C_has_target_meet_record)={harmful_missing}")

    _write_csv(
        run_dir / "A_detail_comparison.csv",
        all_a_rows,
        [
            "eventKey",
            "대회명",
            "kindCd",
            "detailClassCd",
            "종별",
            "세부종목",
            "구분",
            "INF202_참가선수수",
            "INF310_고유id수",
            "A_참가인원차이_INF202-INF310",
            "INF301_라운드목록",
            "INF301_채점종합노출",
        ],
    )
    _write_csv(
        run_dir / "B_set_comparison.csv",
        all_b_rows,
        ["eventKey", "대회명", "대회경로_id수", "성씨경로_id수", "교집합", "대회경로-성씨경로", "성씨경로-대회경로"],
    )
    _write_csv(run_dir / "C_diff_classification.csv", all_c_rows, ["eventKey", "대회명", "idNo", "분류", "기록건수"])
    _write_csv(
        run_dir / "D_public_figures_check.csv",
        all_d_rows,
        ["eventKey", "대회명", "idNo", "상태", "대회경로_튜플수", "기존데이터_튜플수", "기존데이터_채점종합튜플수"],
    )
    _write_json(
        run_dir / "summary.json",
        {
            "runId": run_id,
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "recordsSource": str(records_source) if records_source else None,
            "eventSummaries": event_summaries,
            "harmfulMissingTotal": harmful_missing_total,
            "unresolvedNotes": unresolved_notes,
            "finalVerdict": "가능" if harmful_missing_total == 0 and not unresolved_notes else "조건부",
        },
    )

    report_lines = [
        "# Issue #47 대회 경로 검증 결과",
        "",
        f"- 생성시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- runId: `{run_id}`",
        f"- 결과 디렉터리: `{run_dir}`",
        f"- 비교 원천: `{records_source}`" if records_source else "- 비교 원천: 없음",
        "",
        "## 표본 대회 요약",
        "",
        "| eventKey | 대회명 | A 불일치수 | B 대회-성씨 | B 성씨-대회 | C 핵심손실 | D 일치 | D 채점종합제외일치 | D 불일치 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in event_summaries:
        report_lines.append(
            f"| {summary['eventKey']} | {summary['대회명']} | "
            f"{summary['A_세부종목_불일치수']} | {summary['B_대회경로-성씨경로']} | {summary['B_성씨경로-대회경로']} | "
            f"{summary['C_has_target_meet_record']} | "
            f"{summary['D_match']} | {summary['D_match_except_score_round']} | {summary['D_mismatch']} |"
        )
    report_lines.extend(["", "## 함께 확인 항목", ""])
    for summary in event_summaries:
        kind_keys = ", ".join(sorted(summary["kindCd_counts"].keys()))
        report_lines.extend(
            [
                f"### {summary['eventKey']} {summary['대회명']}",
                f"- kindCd 관측값: {kind_keys or '(없음)'}",
                f"- pcntGbn 분포: {summary['pcntGbn_counts']}",
                f"- INF301 채점종합 노출 세부종목 수: {summary['INF301_채점종합노출_세부종목수']}",
                f"- 요청 수: INF202={summary['요청수_INF202']}, INF301={summary['요청수_INF301']}, INF310={summary['요청수_INF310']}",
                "",
            ]
        )
    report_lines.extend(
        [
            "## 최종 판정",
            "",
            f"- 핵심 누락 수(기록이 있는데 대회 경로 미포착): **{harmful_missing_total}**",
            f"- 판정: **{'가능' if harmful_missing_total == 0 and not unresolved_notes else '조건부'}**",
        ]
    )
    if unresolved_notes:
        report_lines.extend(["", "## 제한/보류", ""])
        for note in unresolved_notes:
            report_lines.append(f"- {note}")
    report_path = pathlib.Path(args.reference_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"[ok] 저장: {run_dir}")
    print(f"[ok] 저장: {report_path}")


def build_parser():
    parser = argparse.ArgumentParser(description="INF201→INF202→INF301→INF310 경로로 대회 참가자 idNo를 수집/검증합니다.")
    sub = parser.add_subparsers(dest="command", required=True)

    events_parser = sub.add_parser("events", help="INF201 대회 목록을 조회합니다.")
    events_parser.add_argument("--page", type=int, default=1, help="INF201 페이지 번호 (기본값: 1)")
    events_parser.set_defaults(func=cmd_events)

    collect_parser = sub.add_parser("collect", help="대회 1개의 참가자 idNo를 수집합니다.")
    collect_parser.add_argument("--class-cd", dest="class_cd", help="대회 classCd")
    collect_parser.add_argument("--to-cd", dest="to_cd", help="대회 toCd")
    collect_parser.add_argument("--search-app-yn", dest="search_app_yn", default="", help="선택: searchAppYn 값")
    collect_parser.add_argument("--event-page", type=int, default=1, help="INF201 조회 페이지 (event-index 사용 시)")
    collect_parser.add_argument("--event-index", type=int, help="INF201 페이지 내 1-based 대회 인덱스")
    collect_parser.add_argument("--event-name", default="", help="출력용 대회명(직접 classCd/toCd 지정 시)")
    collect_parser.add_argument("--sleep", type=float, default=0.2, help="요청 간 sleep 초 (기본값: 0.2)")
    collect_parser.add_argument("--out-dir", default="data", help="CSV 저장 디렉터리 (기본값: data)")
    collect_parser.set_defaults(func=cmd_collect)

    validate_parser = sub.add_parser("validate-route", help="이슈 #47 기준 A~D 검증을 표본 3개 대회로 수행합니다.")
    validate_parser.add_argument(
        "--event",
        action="append",
        required=True,
        help="표본 대회 지정: classCd,toCd,searchAppYn,대회명 (정확히 3개 필요)",
    )
    validate_parser.add_argument("--data-dir", default="data", help="성씨 경로 데이터 디렉터리 (기본값: data)")
    validate_parser.add_argument(
        "--compare-data-dir",
        default="/Users/kihyun/orgs/personal/splits/data",
        help="records_full/records 비교 원천 디렉터리 (기본값: /Users/kihyun/orgs/personal/splits/data)",
    )
    validate_parser.add_argument("--out-dir", default="", help="검증 산출물 디렉터리 (기본값: <data-dir>/route_validation)")
    validate_parser.add_argument("--run-id", default="", help="실행 식별자(미지정 시 timestamp)")
    validate_parser.add_argument("--sleep", type=float, default=0.2, help="요청 간 sleep 초 (기본값: 0.2)")
    validate_parser.add_argument("--allow-live-inf503", action="store_true", help="records 원천이 없을 때 INF503 실시간 분류 허용")
    validate_parser.add_argument(
        "--live-inf503-max",
        type=int,
        default=300,
        help="INF503 실시간 분류 최대 idNo 수 (기본값: 300)",
    )
    validate_parser.add_argument(
        "--live-inf503-sleep",
        type=float,
        default=1.0,
        help="INF503 실시간 분류 요청 간 sleep 초 (기본값: 1.0)",
    )
    validate_parser.add_argument(
        "--refresh-live-inf503",
        action="store_true",
        help="INF503 캐시가 있어도 강제로 재요청",
    )
    validate_parser.add_argument(
        "--reference-report",
        default="reference/data/issue-47-route-validation.md",
        help="판정 결과를 저장할 reference 문서 경로",
    )
    validate_parser.set_defaults(func=cmd_validate_route)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
