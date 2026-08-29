# ADR 0003 — race_ledger 스키마와 결정적 정렬 키 (R-03)

- 상태: Accepted
- 작성시각: 2026-08-29T13:20:00
- 선행: `docs/adr/0002-comparison-extraction.md`

## 문맥

- R-02는 정책별 pairwise 비교를 생성하지만, 레이팅 재생성을 위해서는 **경기 단위 원본 레저**와 **결정적 처리 순서**가 먼저 고정되어야 합니다.
- Glicko-2/TrueSkill 모두 입력 순서가 바뀌면 결과가 바뀔 수 있으므로, 동점 없는 전순서 키가 필요합니다.
- 원천 데이터(`records_anon.csv` 헤더)에는 `race_seq` 전용 필드가 없어, 경기 순번은 대체 규칙이 필요합니다.

## 결정

1. 기본 저장 단위를 pairwise가 아닌 `race_ledger`로 전환합니다.
   - 핵심 컬럼: `ordering_key, race_id, athlete_id, rank, status` (+ 메타 컬럼)
2. `ordering_key`는 **행 단위 유일 키**로 고정합니다.
   - 포맷: `{race_date}|{meet_id}|{race_seq:04d}|{race_id}|{rank:04d}|{athlete_id}`
3. `race_seq`는 원천 값이 있으면 우선 사용하고, 없으면 다음 정렬 기준으로 대체합니다.
   - `(event, round_class, heat_no, round_kind, distance_text, race_id)` 사전순
4. 파생 뷰를 분리합니다.
   - `pairwise_view`: Glicko-2 업데이트용
   - `ranking_view`: TrueSkill 업데이트용
5. 시즌 경계는 `7월 시작 ~ 다음해 6월 종료`로 확정합니다.
   - `rating/ledger/season.py` 상수로 관리하고, `data/season_month_histogram.csv`를 근거로 유지합니다.
6. 레저 저장은 시즌 파티션을 사용합니다.
   - `out/ledger/race_ledger/season=YYYY/part.parquet`
   - 재생성 시 이전 산출물과 해시가 다르면 경고를 출력합니다.

## 근거

- 월별 대회 분포에서 6~8월 사이 공백이 가장 크고, 7~12월이 시즌 시작 구간으로 관측되어 시즌 경계를 7월로 두는 것이 안정적입니다.
- 행 단위 유일 키를 쓰면 동일 경기 내 다중 선수 행에서도 충돌 없이 정렬 안정성을 보장할 수 있습니다.
- 파생 뷰 분리는 레이팅 엔진별 입력 형태를 분리하면서도 단일 원천(`race_ledger`)을 유지하게 해 재현성을 높입니다.

## 결과

- 레저 검증에서 `ordering_key` 유일성, null 금지, 허용 round/status 값 강제가 가능해집니다.
- 같은 입력을 두 번 빌드했을 때 해시 비교로 결정성 회귀를 자동 감시할 수 있습니다.
- 동일 경기 순위 정보가 `race_ledger -> pairwise_view/ranking_view`로 손실 없이 전달되는지 테스트로 보장합니다.
