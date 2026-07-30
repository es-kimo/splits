"""
쇼트트랙 국가대표 선수 대회참가이력 스크래퍼
대한체육회 경기결과 사이트(result.sports.or.kr)에서 데이터를 수집한다.
"""

import time
from io import StringIO
import pathlib
import requests
import pandas as pd
from bs4 import BeautifulSoup

from athletes import ATHLETES

BASE_URL = "https://result.sports.or.kr"
HISTORY_ENDPOINT = f"{BASE_URL}/SK/INF503.do"
RAW_DIR = pathlib.Path("data/raw")
OUTPUT_CSV = pathlib.Path("data/records.csv")

COLUMNS = ["선수명", "idNo", "대회명", "일자", "종별", "세부종목", "라운드", "소속", "기록", "순위"]


def get_session():
    """세션 쿠키를 확보한 requests.Session을 반환한다."""
    session = requests.Session()
    session.get(BASE_URL, timeout=10)
    return session


def search_athlete_id(name: str, session: requests.Session) -> str:
    # TODO: 선수 이름으로 idNo를 검색하는 기능
    # 엔드포인트: INF701.do (추정) — 브라우저 개발자도구로 실제 요청 파라미터를 확인한 뒤 구현할 것.
    # POST 파라미터 구조 미확인.
    raise NotImplementedError(
        f"선수 검색 기능 미구현. '{name}'의 idNo를 athletes.py에 직접 입력하거나 "
        "INF701.do 엔드포인트의 파라미터 구조를 확인 후 이 함수를 완성하세요."
    )


def fetch_history_html(idNo: str, session: requests.Session) -> str:
    """대회참가이력 HTML을 가져온다. 캐시가 있으면 재요청하지 않는다."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"{idNo}.html"

    if cache_path.exists():
        print(f"[cache] {idNo}")
        return cache_path.read_text(encoding="utf-8")

    print(f"[fetch] {idNo}")
    resp = session.post(
        HISTORY_ENDPOINT,
        data={"pclassCd": "SK", "idNo": idNo, "pageIndex": "1"},
        timeout=10,
    )
    resp.raise_for_status()
    html = resp.text
    cache_path.write_text(html, encoding="utf-8")
    time.sleep(1)
    return html


def parse_history(html: str, name: str, idNo: str) -> pd.DataFrame:
    """HTML에서 대회참가이력 테이블을 파싱해 DataFrame으로 반환한다."""
    try:
        tables = pd.read_html(StringIO(html))
        if not tables:
            raise ValueError("테이블 없음")
        df = tables[0]
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None:
            print(f"[warn] {name}({idNo}): 테이블을 찾을 수 없습니다.")
            return pd.DataFrame(columns=COLUMNS)
        df = pd.read_html(StringIO(str(table)))[0]

    df.columns = [str(c) for c in df.columns]

    # 원본 컬럼명이 사이트마다 다를 수 있으므로 위치 기반으로 매핑
    # 컬럼 수가 맞지 않으면 원본 그대로 반환
    if len(df.columns) >= len(COLUMNS) - 2:
        col_map = {df.columns[i]: COLUMNS[i + 2] for i in range(min(len(df.columns), len(COLUMNS) - 2))}
        df = df.rename(columns=col_map)

    df.insert(0, "idNo", idNo)
    df.insert(0, "선수명", name)

    # COLUMNS에 없는 컬럼 제거, 없는 컬럼은 빈 값으로 추가
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]


def scrape_all() -> pd.DataFrame:
    """모든 선수의 이력을 수집해 합친 DataFrame을 반환한다."""
    session = get_session()
    frames = []

    for athlete in ATHLETES:
        name = athlete["name"]
        idNo = athlete["idNo"]

        if idNo is None:
            print(f"[skip] {name}: idNo 없음")
            continue

        html = fetch_history_html(idNo, session)
        df = parse_history(html, name, idNo)
        frames.append(df)

    if not frames:
        print("수집된 데이터가 없습니다.")
        return pd.DataFrame(columns=COLUMNS)

    return pd.concat(frames, ignore_index=True)


def main():
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = scrape_all()
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUTPUT_CSV} ({len(df)}행)")


if __name__ == "__main__":
    main()
