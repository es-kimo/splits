# splits

대한체육회 경기결과 사이트(result.sports.or.kr)에서 쇼트트랙 국가대표 선수들의 대회 참가 이력을 수집하는 스크래퍼.
`athletes.py`에 선수 목록(idNo 포함)을 채운 뒤 실행하면 `data/records.csv`에 결과가 저장된다.
최종 목적: 현 국가대표들이 초등부 시절 몇 등이었는지 분석.

```
pip install -r requirements.txt
python scrape.py
```