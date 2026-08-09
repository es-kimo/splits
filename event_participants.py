import argparse
import csv
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://result.sports.or.kr"
INF201_ENDPOINT = f"{BASE_URL}/SK/INF201.do"
INF202_ENDPOINT = f"{BASE_URL}/SK/INF202.do"
INF301_ENDPOINT = f"{BASE_URL}/SK/INF301.do"
INF310_ENDPOINT = f"{BASE_URL}/SK/INF310.do"

HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
SESSION = requests.Session()

PARTICIPANT_ID_RE = re.compile(r"fnViewHistory\(\s*['\"]?(\d{6,})['\"]?\s*\)")
DIGIT_RE = re.compile(r"\d+")


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


def fetch_inf201_events(page_index=1):
    payload = _base_payload()
    payload["pageIndex"] = str(page_index)
    html = _post(INF201_ENDPOINT, payload)
    soup = BeautifulSoup(html, "html.parser")
    default_search_app_yn = ""
    search_app_input = soup.find("input", attrs={"name": "searchAppYn"})
    if search_app_input and search_app_input.has_attr("value"):
        default_search_app_yn = search_app_input.get("value", "").strip()
    events = []
    for tr in soup.find_all("tr"):
        args = _parse_js_args(tr.get("onclick", ""), "fnEventInfo")
        if not args or len(args) < 2:
            continue
        class_cd = args[0]
        to_cd = args[1]
        search_app_yn = args[2] if len(args) >= 3 else default_search_app_yn
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        event_name = tds[1].get_text(" ", strip=True)
        place = tds[2].get_text(" ", strip=True)
        period = tds[3].get_text(" ", strip=True)
        status = tds[4].get_text(" ", strip=True) if len(tds) >= 5 else ""
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


def fetch_inf202_details(class_cd, to_cd, search_app_yn=""):
    payload = _base_payload()
    payload.update({"classCd": class_cd, "toCd": to_cd, "searchAppYn": search_app_yn})
    html = _post(INF202_ENDPOINT, payload)
    soup = BeautifulSoup(html, "html.parser")
    details = []
    for tr in soup.find_all("tr"):
        args = _parse_js_args(tr.get("onclick", ""), "fnEventSchedule")
        if not args or len(args) < 2:
            continue
        kind_cd = args[0]
        detail_class_cd = args[1]
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        participant_text = tds[3].get_text(" ", strip=True)
        m = DIGIT_RE.search(participant_text)
        participant_count = int(m.group(0)) if m else None
        details.append(
            {
                "kindCd": kind_cd,
                "detailClassCd": detail_class_cd,
                "종별": tds[0].get_text(" ", strip=True),
                "세부종목": tds[1].get_text(" ", strip=True),
                "구분": tds[2].get_text(" ", strip=True),
                "참가선수표시": participant_text,
                "참가선수수": participant_count,
            }
        )
    if not details:
        raise RuntimeError(f"INF202 세부종목 내역을 찾지 못했습니다. classCd={class_cd}, toCd={to_cd}")
    return details


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
            "useGbn": args[0],
            "pcntGbn": args[1],
            "baseClassCd": args[2],
            "rhCd": args[3],
            "rhNm": args[4],
            "baseClassNm": args[5],
        }
        key = tuple(item.values())
        if key in seen:
            continue
        seen.add(key)
        calls.append(item)
    return calls


def fetch_inf310_players(class_cd, to_cd, search_app_yn, kind_cd, detail_class_cd, result_call):
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
    rows = []
    seen = set()
    for anchor in soup.find_all("a"):
        attrs = [anchor.get("href", ""), anchor.get("onclick", "")]
        id_no = None
        for raw in attrs:
            m = PARTICIPANT_ID_RE.search(raw or "")
            if m:
                id_no = m.group(1)
                break
        if not id_no:
            continue
        name = anchor.get_text(" ", strip=True)
        key = (id_no, name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"idNo": id_no, "이름": name})
    return rows


def collect_participants_for_event(class_cd, to_cd, search_app_yn="", sleep_seconds=0.2):
    details = fetch_inf202_details(class_cd, to_cd, search_app_yn=search_app_yn)
    occurrences = []
    unique = {}
    seen_result_calls = set()
    inf301_calls = 0
    inf310_calls = 0
    for detail in details:
        result_calls = fetch_inf301_result_calls(
            class_cd=class_cd,
            to_cd=to_cd,
            search_app_yn=search_app_yn,
            kind_cd=detail["kindCd"],
            detail_class_cd=detail["detailClassCd"],
        )
        inf301_calls += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        for call in result_calls:
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
            players = fetch_inf310_players(
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
            for p in players:
                occurrence = {
                    "idNo": p["idNo"],
                    "이름": p["이름"],
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
                }
                occurrences.append(occurrence)
                if p["idNo"] not in unique:
                    unique[p["idNo"]] = {
                        "idNo": p["idNo"],
                        "이름": p["이름"],
                        "출현건수": 0,
                        "종별수": set(),
                    }
                unique[p["idNo"]]["출현건수"] += 1
                unique[p["idNo"]]["종별수"].add((detail["kindCd"], detail["detailClassCd"]))
    unique_rows = []
    for row in unique.values():
        unique_rows.append(
            {
                "idNo": row["idNo"],
                "이름": row["이름"],
                "출현건수": row["출현건수"],
                "세부종목수": len(row["종별수"]),
            }
        )
    unique_rows.sort(key=lambda x: x["idNo"])
    return {
        "details": details,
        "occurrences": occurrences,
        "participants": unique_rows,
        "stats": {
            "inf202_detail_count": len(details),
            "inf301_call_count": inf301_calls,
            "inf310_call_count": inf310_calls,
            "unique_result_call_count": len(seen_result_calls),
            "occurrence_count": len(occurrences),
            "unique_id_count": len(unique_rows),
        },
    }


def _write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def cmd_events(args):
    events = fetch_inf201_events(page_index=args.page)
    print(f"INF201 page {args.page}: {len(events)}개 대회")
    for i, event in enumerate(events, start=1):
        print(
            f"{i}. classCd={event['classCd']} toCd={event['toCd']} "
            f"searchAppYn={event['searchAppYn'] or '-'} | {event['대회명']} | {event['기간']} | {event['장소']}"
        )


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
    stats = result["stats"]
    if not participants:
        raise RuntimeError("참가자 idNo를 추출하지 못했습니다.")
    out_dir = pathlib.Path(args.out_dir)
    unique_path = out_dir / f"event_{class_cd}_{to_cd}_participants.csv"
    occ_path = out_dir / f"event_{class_cd}_{to_cd}_participant_occurrences.csv"
    _write_csv(unique_path, participants, ["idNo", "이름", "출현건수", "세부종목수"])
    _write_csv(
        occ_path,
        occurrences,
        ["idNo", "이름", "kindCd", "detailClassCd", "종별", "세부종목", "구분", "baseClassCd", "baseClassNm", "rhCd", "rhNm", "pcntGbn", "useGbn"],
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
    print(f"[ok] 저장: {unique_path}")
    print(f"[ok] 저장: {occ_path}")


def build_parser():
    parser = argparse.ArgumentParser(description="INF201→INF202→INF301→INF310 경로로 대회 참가자 idNo를 수집합니다.")
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

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
