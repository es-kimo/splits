import csv
import pathlib
import re
import sys
import time
import requests
from bs4 import BeautifulSoup
from athletes import ATHLETES
BASE_URL = "https://result.sports.or.kr"
SEARCH_ENDPOINT = f"{BASE_URL}/SK/INF703.do"
HISTORY_ENDPOINT = f"{BASE_URL}/SK/INF503.do"
RAW_DIR = pathlib.Path("data/raw")
NO_ID_CSV = pathlib.Path("data/no_id_rows.csv")
CANDIDATES_CSV = pathlib.Path("data/candidates.csv")
RESOLVED_CSV = pathlib.Path("data/resolved.csv")
SESSION = requests.Session()
HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
IDNO_RE = re.compile(r'fnPlayerHistory\(\s*["\']?(\d{6,})')
REPORTED_COUNT_RE = re.compile(r"선수\s*정보\s*\(\s*([0-9,]+)\s*\)")
YYYYMM_RE = re.compile(r"(19|20)\d{2}(0[1-9]|1[0-2])$")
AFFILIATION_ALIAS_MAP = {"한국체대": "한국체육대학교", "단국대": "단국대학교", "경희대": "경희대학교", "고려대": "고려대학교", "용인대": "용인대학교", "경희사이버대": "경희사이버대학교"}
def _payload(name="", page=1, id_no=""):
    return {"classCd": "", "toCd": "", "pclassCd": "SK", "eventCd": "", "movSeq": "", "teamCd": "", "idNo": id_no, "pageIndex": str(page), "searchKeyword": name}
def _search_cache_path(name, page):
    safe_name = name.replace("/", "_").replace("\\", "_").strip() or "empty"
    return RAW_DIR / f"search_{safe_name}_{page}.html"
def fetch_search_page(name, page, refresh=False):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _search_cache_path(name, page)
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8")
    try:
        resp = SESSION.post(SEARCH_ENDPOINT, data=_payload(name=name, page=page), headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception:
        print(f"[error] INF703 요청 실패: name={name}, page={page}")
        raise
    html = resp.text
    cache_path.write_text(html, encoding="utf-8")
    return html
def _count_data_rows_from_tbody(tbody):
    count = 0
    if not tbody:
        return 0
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        if len(tds) == 1 and "검색 결과가 없습니다" in tds[0].get_text(" ", strip=True):
            continue
        count += 1
    return count
def parse_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    tbody = soup.find("tbody")
    if not tbody:
        return []
    rows = []
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        values = [td.get_text(" ", strip=True) for td in tds[:5]]
        onclick_values = [tr.get("onclick", "")] if tr.has_attr("onclick") else []
        onclick_values.extend(node.get("onclick", "") for node in tr.find_all(attrs={"onclick": True}))
        id_no = None
        for onclick in onclick_values:
            m = IDNO_RE.search(onclick or "")
            if m:
                id_no = m.group(1)
                break
        rows.append({"이름": values[0], "성별": values[1], "소속": values[2], "종별": values[3], "시도": values[4], "idNo": id_no})
    return rows
def parse_reported_count(html):
    # 화면 "선수 정보(N)" 값은 실측 행 수/고유 idNo와 불일치할 수 있어 참고용으로만 사용한다.
    m = REPORTED_COUNT_RE.search(html)
    return int(m.group(1).replace(",", "")) if m else None
def _append_no_id_rows(buffer):
    if not buffer:
        return
    NO_ID_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not NO_ID_CSV.exists()
    with NO_ID_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["검색이름", "페이지", "이름", "성별", "소속", "종별", "시도"])
        if write_header:
            writer.writeheader()
        for search_name, page, row in buffer:
            writer.writerow({"검색이름": search_name, "페이지": page, "이름": row["이름"], "성별": row["성별"], "소속": row["소속"], "종별": row["종별"], "시도": row["시도"]})
def search_all_pages(name, max_pages=20, refresh=False):
    all_rows, no_id_rows, reported_count, parsed_pages = [], [], None, 0
    for page in range(1, max_pages + 1):
        from_cache = _search_cache_path(name, page).exists() and not refresh
        html = fetch_search_page(name, page, refresh=refresh)
        if reported_count is None:
            reported_count = parse_reported_count(html)
        page_rows = parse_rows(html)
        if not page_rows:
            break
        parsed_pages += 1
        all_rows.extend(page_rows)
        no_id_rows.extend((name, page, r) for r in page_rows if r["idNo"] is None)
        if not from_cache:
            time.sleep(1)
    _append_no_id_rows(no_id_rows)
    unique_ids = len({row["idNo"] for row in all_rows if row["idNo"]})
    shown = reported_count if reported_count is not None else "?"
    print(f"{name}: 총 {len(all_rows)}행 / 고유 idNo {unique_ids}개 / 화면표시 {shown} / {parsed_pages}페이지")
    return all_rows
def group_by_idno(rows):
    grouped = {}
    for row in rows:
        id_no = row["idNo"]
        if not id_no:
            continue
        if id_no not in grouped:
            grouped[id_no] = {"이름": row["이름"], "idNo": id_no, "행수": 0, "소속목록": set(), "종별목록": set(), "성별목록": set()}
        grouped[id_no]["행수"] += 1
        grouped[id_no]["소속목록"].add(row["소속"])
        grouped[id_no]["종별목록"].add(row["종별"])
        grouped[id_no]["성별목록"].add(row["성별"])
    result = []
    for value in grouped.values():
        result.append({"이름": value["이름"], "idNo": value["idNo"], "id체계": "date" if value["idNo"][:2] in ("19", "20") else "other", "행수": value["행수"], "소속목록": sorted(value["소속목록"]), "종별목록": sorted(value["종별목록"]), "성별목록": sorted(value["성별목록"])})
    return sorted(result, key=lambda x: (-x["행수"], x["idNo"]))
def _expand_affiliation_aliases(raw_aliases):
    expanded = []
    for alias in raw_aliases:
        if not isinstance(alias, str):
            continue
        base = alias.strip()
        if not base:
            continue
        expanded.append(base)
        if base in AFFILIATION_ALIAS_MAP:
            expanded.append(AFFILIATION_ALIAS_MAP[base])
        for short, full in AFFILIATION_ALIAS_MAP.items():
            if base == full:
                expanded.append(short)
        if base.endswith("고") and not base.endswith("고등학교"):
            expanded.append(base + "등학교")
        if base.endswith("고등학교"):
            expanded.append(base[:-4] + "고")
    return sorted(set(expanded))
def _is_affiliation_match(expected_aliases, affiliations):
    for expected in expected_aliases:
        for actual in affiliations:
            if expected in actual or actual in expected:
                return True
    return False
def _registration_yyyymm(id_no):
    prefix = (id_no or "")[:6]
    return prefix if YYYYMM_RE.fullmatch(prefix) else "?"
def resolve_athletes(refresh=False):
    # 하나의 idNo에 초/중/고/대 등록 이력이 연결되어 유년기 기록까지 함께 조회되는 케이스가 실측된다.
    fields = ["검색이름", "성별", "후보수", "후보순위", "idNo", "id체계", "행수", "등록연월", "소속목록", "종별목록", "성별목록", "예상소속별칭", "소속일치", "성별일치", "판정"]
    out_rows = []
    resolved_rows = []
    per_name = {}
    counts = {"confirmed": 0, "likely": 0, "review": 0, "unlikely": 0}
    for athlete in ATHLETES:
        name = str(athlete.get("이름", "")).strip()
        gender = str(athlete.get("성별", "")).strip()
        aliases = _expand_affiliation_aliases(athlete.get("소속별칭", []))
        if not name or not gender:
            continue
        candidates = group_by_idno(search_all_pages(name, refresh=refresh))
        max_rows = max((c["행수"] for c in candidates), default=0)
        per_name[name] = {"aliases": aliases, "gender": gender, "rows": []}
        print(f"{name}: 후보 {len(candidates)}개")
        if not candidates:
            out_rows.append({"검색이름": name, "성별": gender, "후보수": 0, "후보순위": "", "idNo": "", "id체계": "", "행수": 0, "등록연월": "?", "소속목록": "", "종별목록": "", "성별목록": "", "예상소속별칭": " | ".join(aliases), "소속일치": "N", "성별일치": "N", "판정": "unlikely"})
            counts["unlikely"] += 1
            continue
        for rank, c in enumerate(candidates, start=1):
            aff_match = _is_affiliation_match(aliases, c["소속목록"])
            gender_match = gender in c["성별목록"]
            if aff_match and gender_match and c["행수"] == max_rows:
                verdict = "confirmed"
            elif aff_match and gender_match:
                verdict = "likely"
            elif not aff_match and c["행수"] >= 5:
                verdict = "review"
            else:
                verdict = "unlikely"
            row = {"검색이름": name, "성별": gender, "후보수": len(candidates), "후보순위": rank, "idNo": c["idNo"], "id체계": c["id체계"], "행수": c["행수"], "등록연월": _registration_yyyymm(c["idNo"]), "소속목록": " | ".join(c["소속목록"]), "종별목록": " | ".join(c["종별목록"]), "성별목록": " | ".join(c["성별목록"]), "예상소속별칭": " | ".join(aliases), "소속일치": "Y" if aff_match else "N", "성별일치": "Y" if gender_match else "N", "판정": verdict}
            out_rows.append(row)
            per_name[name]["rows"].append({"idNo": c["idNo"], "행수": c["행수"], "소속목록": c["소속목록"], "성별목록": c["성별목록"], "소속일치": row["소속일치"], "성별일치": row["성별일치"], "판정": verdict})
            counts[verdict] += 1
            if verdict == "confirmed":
                resolved_rows.append({"이름": name, "성별": gender, "idNo": c["idNo"], "행수": c["행수"], "소속목록": " | ".join(c["소속목록"])})
            print(f"  {rank}. {c['idNo']} ({c['행수']}행) 소속일치={row['소속일치']} 성별일치={row['성별일치']} 판정={verdict}")
    CANDIDATES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with CANDIDATES_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
    with RESOLVED_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["이름", "성별", "idNo", "행수", "소속목록"])
        writer.writeheader()
        writer.writerows(resolved_rows)
    print(f"저장 완료: {CANDIDATES_CSV}")
    print(f"저장 완료: {RESOLVED_CSV}")
    unresolved = [a["이름"] for a in ATHLETES if not any(r["판정"] == "confirmed" for r in per_name.get(a["이름"], {}).get("rows", []))]
    print(f"confirmed {counts['confirmed']}명 / likely {counts['likely']}명 / review {counts['review']}건 / unlikely {counts['unlikely']}건")
    print(f"미확정 선수: {', '.join(unresolved) if unresolved else '(없음)'}")
    ny_rows = per_name.get("남윤창", {}).get("rows", [])
    ny_ok = any(r["idNo"] == "201105000916" and r["소속일치"] == "Y" and r["판정"] == "confirmed" for r in ny_rows)
    if not ny_ok:
        ny_aliases = per_name.get("남윤창", {}).get("aliases", [])
        for r in ny_rows:
            if r["idNo"] == "201105000916":
                print(f"[check-fail] 남윤창 expected_aliases={ny_aliases}")
                print(f"[check-fail] 남윤창 affiliations={r['소속목록']} gender_list={r['성별목록']}")
                print(f"[check-fail] 남윤창 compare_result=소속일치:{r['소속일치']} 성별일치:{r['성별일치']} 판정:{r['판정']}")
    for target in ["김길리", "심석희", "최지현", "노아름", "임종언", "김태성", "배서찬"]:
        rows = per_name.get(target, {}).get("rows", [])
        if len(rows) == 1 and rows[0]["판정"] != "confirmed":
            print(f"[check-fail] {target} expected_aliases={per_name.get(target, {}).get('aliases', [])}")
            print(f"[check-fail] {target} affiliations={rows[0]['소속목록']} gender_list={rows[0]['성별목록']}")
            print(f"[check-fail] {target} compare_result=소속일치:{rows[0]['소속일치']} 성별일치:{rows[0]['성별일치']} 판정:{rows[0]['판정']}")
def probe_search_pagination(name, refresh=False):
    for page in range(1, 6):
        from_cache = _search_cache_path(name, page).exists() and not refresh
        rows = parse_rows(fetch_search_page(name, page, refresh=refresh))
        print(f"{name} page {page}: {len(rows)}행 / 고유id {len({r['idNo'] for r in rows if r['idNo']})}개")
        if not from_cache and page < 5:
            time.sleep(1)
def probe_history_pagination(idNo):
    for page in range(1, 6):
        try:
            resp = SESSION.post(HISTORY_ENDPOINT, data=_payload(id_no=str(idNo), page=page), headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception:
            print(f"[error] INF503 요청 실패: idNo={idNo}, page={page}")
            raise
        soup = BeautifulSoup(resp.text, "html.parser")
        print(f"INF503 {idNo} page {page}: {_count_data_rows_from_tbody(soup.find('tbody'))}행")
        if page < 5:
            time.sleep(1)
def _print_rows_table(rows):
    print("No | 이름 | 성별 | 소속 | 종별 | 시도 | idNo")
    for i, r in enumerate(rows, start=1):
        print(f"{i} | {r['이름']} | {r['성별']} | {r['소속']} | {r['종별']} | {r['시도']} | {r['idNo'] or ''}")
    if not rows:
        print("(검색 결과 없음)")
def _print_usage():
    print("사용법: python scrape.py search <이름> [--refresh]")
    print("       python scrape.py resolve [--refresh]")
    print("       python scrape.py probe <이름> [--refresh]")
def main():
    raw_args = sys.argv[1:]
    refresh = "--refresh" in raw_args
    args = [a for a in raw_args if a != "--refresh"]
    if not args:
        _print_usage()
        return
    if args[0] == "search" and len(args) >= 2:
        _print_rows_table(search_all_pages(" ".join(args[1:]), refresh=refresh))
        return
    if args[0] == "resolve":
        resolve_athletes(refresh=refresh)
        return
    if args[0] == "probe" and len(args) >= 2:
        probe_search_pagination(" ".join(args[1:]), refresh=refresh)
        return
    _print_usage()
if __name__ == "__main__":
    main()
