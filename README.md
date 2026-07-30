# splits

대한체육회 경기결과 사이트(result.sports.or.kr)에서 쇼트트랙 선수 검색과 idNo 후보 확정을 돕는 스크래퍼.

```
pip install -r requirements.txt
python scrape.py search 남윤창
python scrape.py probe 남윤창
python scrape.py resolve
python scrape.py search 남윤창 --refresh
```

- `search`: INF703 선수 검색 결과를 페이지 끝까지 수집해 표로 출력
- `probe`: 1~5페이지의 행 수/고유 idNo 분포 진단 출력
- `resolve`: `athletes.py` 목록을 순회해 `data/candidates.csv` 생성