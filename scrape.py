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
SESSION = requests.Session()
HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
IDNO_RE = re.compile(r'fnPlayerHistory\(\s*["\']?(\d{6,})')
REPORTED_COUNT_RE = re.compile(r"선수\s*정보\s*\(\s*([0-9,]+)\s*\)")
YYYYMM_RE = re.compile(r"(19|20)\d{2}(0[1-9]|1[0-2])$")
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
            grouped[id_no] = {"이름": row["이름"], "idNo": id_no, "행수": 0, "소속목록": set(), "종별목록": set()}
        grouped[id_no]["행수"] += 1
        grouped[id_no]["소속목록"].add(row["소속"])
        grouped[id_no]["종별목록"].add(row["종별"])
    result = []
    for value in grouped.values():
        result.append({"이름": value["이름"], "idNo": value["idNo"], "행수": value["행수"], "소속목록": sorted(value["소속목록"]), "종별목록": sorted(value["종별목록"])})
    return sorted(result, key=lambda x: (-x["행수"], x["idNo"]))


def _expected_affiliation(athlete):
    for key in ("expected_affiliation", "expected_team", "team", "affiliation", "소속"):
        value = athlete.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _registration_yyyymm(id_no):
    prefix = (id_no or "")[:6]
    return prefix if YYYYMM_RE.fullmatch(prefix) else "?"


def resolve_athletes(refresh=False):
    # 하나의 idNo에 초/중/고/대 등록 이력이 연결되어 유년기 기록까지 함께 조회되는 케이스가 실측된다.
    fields = ["검색이름", "후보수", "후보순위", "idNo", "행수", "등록연월", "소속목록", "종별목록", "예상소속", "소속일치"]
    out_rows = []
    for athlete in ATHLETES:
        name = str(athlete.get("name", "")).strip()
        if not name:
            continue
        expected = _expected_affiliation(athlete)
        candidates = group_by_idno(search_all_pages(name, refresh=refresh))
        print(f"{name}: 후보 {len(candidates)}개")
        if not candidates:
            out_rows.append({"검색이름": name, "후보수": 0, "후보순위": "", "idNo": "", "행수": 0, "등록연월": "?", "소속목록": "", "종별목록": "", "예상소속": expected, "소속일치": "N"})
            continue
        for rank, c in enumerate(candidates, start=1):
            match = "Y" if expected and expected in c["소속목록"] else "N"
            out_rows.append(
                {
                    "검색이름": name,
                    "후보수": len(candidates),
                    "후보순위": rank,
                    "idNo": c["idNo"],
                    "행수": c["행수"],
                    "등록연월": _registration_yyyymm(c["idNo"]),
                    "소속목록": " | ".join(c["소속목록"]),
                    "종별목록": " | ".join(c["종별목록"]),
                    "예상소속": expected,
                    "소속일치": match,
                }
            )
            print(f"  {rank}. {c['idNo']} ({c['행수']}행) 소속일치={match}")
    CANDIDATES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with CANDIDATES_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"저장 완료: {CANDIDATES_CSV}")


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
