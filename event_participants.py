import argparse
import csv
import json
import pathlib
import re
import time
from urllib.parse import urljoin

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
HISTORY_ID_RE = re.compile(r"fn(?:PlayerHistory|ViewHistory)\(\s*['\"]?(\d{6,})['\"]?\s*\)")
DIGIT_RE = re.compile(r"\d+")
FORM_VALUE_ASSIGN_RE = re.compile(r"frm\.([A-Za-z0-9_]+)\.value\s*=\s*([^;]+);")
FORM_ACTION_ASSIGN_RE = re.compile(r"frm\.action\s*=\s*(['\"])(.*?)\1")
FORM_TARGET_ASSIGN_RE = re.compile(r"frm\.target\s*=\s*(['\"])(.*?)\1")
FORM_FIELD_REF_RE = re.compile(r"frm\.([A-Za-z0-9_]+)\.value")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def fetch_inf202_html(class_cd, to_cd, search_app_yn=""):
    payload = _base_payload()
    payload.update({"classCd": class_cd, "toCd": to_cd, "searchAppYn": search_app_yn})
    return _post(INF202_ENDPOINT, payload)


def _parse_inf202_details_from_soup(soup):
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
    return details


def fetch_inf202_details(class_cd, to_cd, search_app_yn=""):
    html = fetch_inf202_html(class_cd=class_cd, to_cd=to_cd, search_app_yn=search_app_yn)
    soup = BeautifulSoup(html, "html.parser")
    details = _parse_inf202_details_from_soup(soup)
    if not details:
        raise RuntimeError(f"INF202 세부종목 내역을 찾지 못했습니다. classCd={class_cd}, toCd={to_cd}")
    return details


def _extract_js_function(soup, fn_name):
    fn_header = re.compile(rf"function\s+{re.escape(fn_name)}\s*\(")
    for script in soup.find_all("script"):
        script_text = script.get_text("\n", strip=False)
        m = fn_header.search(script_text)
        if not m:
            continue
        paren_start = script_text.find("(", m.start())
        if paren_start < 0:
            continue
        depth = 0
        paren_end = -1
        for i in range(paren_start, len(script_text)):
            ch = script_text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    paren_end = i
                    break
        if paren_end < 0:
            continue
        body_start = script_text.find("{", paren_end)
        if body_start < 0:
            continue
        depth = 0
        quote = None
        escaped = False
        body_end = -1
        for i in range(body_start, len(script_text)):
            ch = script_text[i]
            if quote is not None:
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    continue
                if ch == quote:
                    quote = None
                continue
            if ch in ("'", '"'):
                quote = ch
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    body_end = i
                    break
        if body_end < 0:
            continue
        params = [p.strip() for p in script_text[paren_start + 1 : paren_end].split(",") if p.strip()]
        return {
            "name": fn_name,
            "parameters": params,
            "body": script_text[body_start + 1 : body_end],
        }
    return None


def _summarize_form_function(fn_meta):
    body = fn_meta["body"]
    action_matches = list(FORM_ACTION_ASSIGN_RE.finditer(body))
    target_matches = list(FORM_TARGET_ASSIGN_RE.finditer(body))
    value_assignments = []
    for m in FORM_VALUE_ASSIGN_RE.finditer(body):
        value_assignments.append({"field": m.group(1), "expr": m.group(2).strip()})
    return {
        "name": fn_meta["name"],
        "parameters": fn_meta["parameters"],
        "action": action_matches[-1].group(2).strip() if action_matches else "",
        "target": target_matches[-1].group(2).strip() if target_matches else "",
        "submits_form": "frm.submit" in body,
        "value_assignments": value_assignments,
    }


def _find_onclick_calls(soup, fn_name):
    calls = []
    for node in soup.find_all(attrs={"onclick": True}):
        args = _parse_js_args(node.get("onclick", ""), fn_name)
        if args is None:
            continue
        calls.append(args)
    return calls


def _collect_form_values(soup):
    values = {}
    for input_tag in soup.find_all("input"):
        name = (input_tag.get("name") or "").strip()
        if not name:
            continue
        values[name] = (input_tag.get("value") or "").strip()
    return values


def _split_js_concat(expr):
    parts = []
    buf = []
    quote = None
    escaped = False
    for ch in expr:
        if quote is not None:
            buf.append(ch)
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch == "+":
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf).strip())
    return [part for part in parts if part != ""]


def _strip_wrapping_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1], True
    return value, False


def _resolve_js_expression(expr, param_values, form_values):
    resolved_parts = []
    for token in _split_js_concat(expr):
        literal, is_literal = _strip_wrapping_quotes(token)
        if is_literal:
            resolved_parts.append(literal)
            continue
        field_ref = FORM_FIELD_REF_RE.fullmatch(token)
        if field_ref:
            resolved_parts.append(form_values.get(field_ref.group(1), ""))
            continue
        if token.isdigit():
            resolved_parts.append(token)
            continue
        if IDENT_RE.fullmatch(token):
            if token in param_values:
                resolved_parts.append(param_values[token])
                continue
            if token in form_values:
                resolved_parts.append(form_values[token])
                continue
        return None
    return "".join(resolved_parts)


def _resolve_action_url(action):
    raw = (action or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("/"):
        return urljoin(BASE_URL, raw)
    return urljoin(BASE_URL + "/", raw)


def _prepare_follow_request(summary, call_args, form_values):
    if not summary["submits_form"]:
        return None
    action_url = _resolve_action_url(summary["action"])
    if not action_url:
        return None
    param_values = {}
    for idx, param in enumerate(summary["parameters"]):
        param_values[param] = call_args[idx] if idx < len(call_args) else ""
    payload = dict(form_values)
    unresolved = []
    for assignment in summary["value_assignments"]:
        resolved = _resolve_js_expression(
            assignment["expr"],
            param_values=param_values,
            form_values=payload,
        )
        if resolved is None:
            unresolved.append(assignment)
            continue
        payload[assignment["field"]] = resolved
    return {
        "action_url": action_url,
        "payload": payload,
        "unresolved_assignments": unresolved,
        "parameters": param_values,
    }


def _analyze_response_html(html):
    id_values = sorted({m.group(1) for m in HISTORY_ID_RE.finditer(html)})
    soup = BeautifulSoup(html, "html.parser")
    headings = [h.get_text(" ", strip=True) for h in soup.find_all("h4")]
    return {
        "response_bytes": len(html.encode("utf-8")),
        "unique_history_id_count": len(id_values),
        "sample_history_ids": id_values[:10],
        "contains_fnPlayerHistory": "fnPlayerHistory(" in html,
        "contains_fnViewHistory": "fnViewHistory(" in html,
        "contains_fnEventSchedule": "fnEventSchedule(" in html,
        "contains_fnEventResult": "fnEventResult(" in html,
        "headings": headings[:8],
    }


def probe_inf202_actions(class_cd, to_cd, search_app_yn="", follow=True):
    html = fetch_inf202_html(class_cd=class_cd, to_cd=to_cd, search_app_yn=search_app_yn)
    soup = BeautifulSoup(html, "html.parser")
    form_values = _collect_form_values(soup)
    form_values["classCd"] = class_cd
    form_values["toCd"] = to_cd
    form_values["searchAppYn"] = search_app_yn
    result = {
        "classCd": class_cd,
        "toCd": to_cd,
        "searchAppYn": search_app_yn,
        "inf202_response_bytes": len(html.encode("utf-8")),
        "functions": [],
    }
    for fn_name in ("fnEventList", "fnEventVod"):
        fn_meta = _extract_js_function(soup, fn_name)
        if fn_meta is None:
            result["functions"].append({"name": fn_name, "found": False})
            continue
        summary = _summarize_form_function(fn_meta)
        callsites = _find_onclick_calls(soup, fn_name)
        selected_args = callsites[0] if callsites else []
        fn_result = {
            "name": fn_name,
            "found": True,
            "parameter_count": len(summary["parameters"]),
            "parameters": summary["parameters"],
            "action": summary["action"],
            "target": summary["target"],
            "submits_form": summary["submits_form"],
            "value_assignments": summary["value_assignments"],
            "callsite_count": len(callsites),
            "sample_call_args": selected_args,
        }
        if follow:
            request_meta = _prepare_follow_request(summary, selected_args, form_values)
            if request_meta:
                payload = request_meta["payload"]
                follow_preview = {
                    "action_url": request_meta["action_url"],
                    "payload_core": {
                        "classCd": payload.get("classCd", ""),
                        "toCd": payload.get("toCd", ""),
                        "searchAppYn": payload.get("searchAppYn", ""),
                        "kindCd": payload.get("kindCd", ""),
                        "detailClassCd": payload.get("detailClassCd", ""),
                        "eventCd": payload.get("eventCd", ""),
                        "movSeq": payload.get("movSeq", ""),
                    },
                    "unresolved_assignments": request_meta["unresolved_assignments"],
                }
                fn_result["follow_request"] = follow_preview
                try:
                    follow_html = _post(request_meta["action_url"], payload)
                except requests.RequestException as exc:
                    fn_result["follow_error"] = str(exc)
                else:
                    fn_result["follow_response"] = _analyze_response_html(follow_html)
        result["functions"].append(fn_result)
    return result


def summarize_inf202_variant(class_cd, to_cd, search_app_yn=""):
    html = fetch_inf202_html(class_cd=class_cd, to_cd=to_cd, search_app_yn=search_app_yn)
    soup = BeautifulSoup(html, "html.parser")
    details = _parse_inf202_details_from_soup(soup)
    headings = [h.get_text(" ", strip=True) for h in soup.find_all("h4")]
    captions = []
    for table in soup.find_all("table"):
        caption = table.find("caption")
        text = caption.get_text(" ", strip=True) if caption else ""
        if text:
            captions.append(text)
    fn_actions = {}
    for fn_name in ("fnEventList", "fnEventVod"):
        meta = _extract_js_function(soup, fn_name)
        if meta is None:
            fn_actions[fn_name] = ""
            continue
        fn_actions[fn_name] = _summarize_form_function(meta)["action"]
    detail_keys = sorted({(d["kindCd"], d["detailClassCd"]) for d in details})
    detail_labels = sorted({f"{d['종별']} | {d['세부종목']} | {d['구분']}" for d in details})
    return {
        "classCd": class_cd,
        "toCd": to_cd,
        "searchAppYn": search_app_yn,
        "response_bytes": len(html.encode("utf-8")),
        "detail_count": len(details),
        "unique_detail_key_count": len(detail_keys),
        "detail_keys": detail_keys,
        "detail_labels": detail_labels,
        "sample_detail_keys": detail_keys[:10],
        "sample_detail_labels": detail_labels[:10],
        "headings": headings[:8],
        "captions": captions[:8],
        "function_actions": fn_actions,
    }


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


def cmd_probe_inf202_actions(args):
    event = _resolve_event_from_args(args)
    class_cd = event["classCd"]
    to_cd = event["toCd"]
    search_app_yn = event["searchAppYn"]
    print(f"[start] probe INF202 actions classCd={class_cd}, toCd={to_cd}, searchAppYn={search_app_yn or '-'}")
    result = probe_inf202_actions(
        class_cd=class_cd,
        to_cd=to_cd,
        search_app_yn=search_app_yn,
        follow=not args.no_follow,
    )
    for fn_item in result["functions"]:
        if not fn_item.get("found"):
            print(f"[warn] {fn_item['name']} 함수 정의를 찾지 못했습니다.")
            continue
        action = fn_item.get("action") or "-"
        print(
            f"[fn] {fn_item['name']} action={action} submit={fn_item['submits_form']} "
            f"calls={fn_item['callsite_count']} params={fn_item['parameter_count']}"
        )
        follow_response = fn_item.get("follow_response")
        if follow_response:
            print(
                f"  ↳ follow bytes={follow_response['response_bytes']} "
                f"historyIds={follow_response['unique_history_id_count']} "
                f"fnPlayerHistory={follow_response['contains_fnPlayerHistory']}"
            )
        follow_error = fn_item.get("follow_error")
        if follow_error:
            print(f"  ↳ follow error: {follow_error}")
    if args.json_out:
        out_path = pathlib.Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] 저장: {out_path}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_compare_classcd(args):
    summary_a = summarize_inf202_variant(
        class_cd=args.class_cd_a,
        to_cd=args.to_cd,
        search_app_yn=args.search_app_yn,
    )
    summary_b = summarize_inf202_variant(
        class_cd=args.class_cd_b,
        to_cd=args.to_cd,
        search_app_yn=args.search_app_yn,
    )
    labels_a = set(summary_a["detail_labels"])
    labels_b = set(summary_b["detail_labels"])
    only_a = sorted(labels_a - labels_b)
    only_b = sorted(labels_b - labels_a)
    print(f"[compare] toCd={args.to_cd} searchAppYn={args.search_app_yn or '-'}")
    print(
        f"  classCd={args.class_cd_a}: bytes={summary_a['response_bytes']} "
        f"details={summary_a['detail_count']} uniqueKeys={summary_a['unique_detail_key_count']}"
    )
    print(
        f"  classCd={args.class_cd_b}: bytes={summary_b['response_bytes']} "
        f"details={summary_b['detail_count']} uniqueKeys={summary_b['unique_detail_key_count']}"
    )
    print(
        f"  delta(bytes)={summary_a['response_bytes'] - summary_b['response_bytes']} "
        f"delta(details)={summary_a['detail_count'] - summary_b['detail_count']}"
    )
    print(
        f"  fnEventList action: {args.class_cd_a}={summary_a['function_actions'].get('fnEventList') or '-'} | "
        f"{args.class_cd_b}={summary_b['function_actions'].get('fnEventList') or '-'}"
    )
    print(
        f"  fnEventVod action: {args.class_cd_a}={summary_a['function_actions'].get('fnEventVod') or '-'} | "
        f"{args.class_cd_b}={summary_b['function_actions'].get('fnEventVod') or '-'}"
    )
    print(f"  only classCd={args.class_cd_a} detail labels: {len(only_a)}개")
    for item in only_a[:10]:
        print(f"    - {item}")
    print(f"  only classCd={args.class_cd_b} detail labels: {len(only_b)}개")
    for item in only_b[:10]:
        print(f"    - {item}")
    payload = {
        "toCd": args.to_cd,
        "searchAppYn": args.search_app_yn,
        "classA": summary_a,
        "classB": summary_b,
        "onlyClassA": only_a,
        "onlyClassB": only_b,
    }
    if args.json_out:
        out_path = pathlib.Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] 저장: {out_path}")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


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

    probe_parser = sub.add_parser("probe-inf202-actions", help="INF202의 fnEventList/fnEventVod 경로를 추적합니다.")
    probe_parser.add_argument("--class-cd", dest="class_cd", help="대회 classCd")
    probe_parser.add_argument("--to-cd", dest="to_cd", help="대회 toCd")
    probe_parser.add_argument("--search-app-yn", dest="search_app_yn", default="", help="선택: searchAppYn 값")
    probe_parser.add_argument("--event-page", type=int, default=1, help="INF201 조회 페이지 (event-index 사용 시)")
    probe_parser.add_argument("--event-index", type=int, help="INF201 페이지 내 1-based 대회 인덱스")
    probe_parser.add_argument("--event-name", default="", help="출력용 대회명(직접 classCd/toCd 지정 시)")
    probe_parser.add_argument("--no-follow", action="store_true", help="후속 action 요청을 생략하고 함수 정의만 출력")
    probe_parser.add_argument("--json", action="store_true", help="결과 JSON을 stdout으로 출력")
    probe_parser.add_argument("--json-out", help="결과 JSON 저장 경로")
    probe_parser.set_defaults(func=cmd_probe_inf202_actions)

    compare_parser = sub.add_parser("compare-classcd", help="동일 toCd에서 classCd 간 INF202 응답 차이를 비교합니다.")
    compare_parser.add_argument("--to-cd", required=True, help="대회 toCd")
    compare_parser.add_argument("--search-app-yn", default="", help="선택: searchAppYn 값")
    compare_parser.add_argument("--class-cd-a", default="1", help="비교군 A classCd (기본값: 1)")
    compare_parser.add_argument("--class-cd-b", default="2", help="비교군 B classCd (기본값: 2)")
    compare_parser.add_argument("--json", action="store_true", help="결과 JSON을 stdout으로 출력")
    compare_parser.add_argument("--json-out", help="결과 JSON 저장 경로")
    compare_parser.set_defaults(func=cmd_compare_classcd)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
