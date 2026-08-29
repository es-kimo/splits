# ADR 0004 — Glicko-2 베이스라인 엔진과 공통 예측기 인터페이스 (R-04)

- 상태: Accepted
- 작성시각: 2026-08-29T15:45:00
- 선행: `docs/adr/0003-ledger-ordering.md`

## 문맥

- R-03까지 `race_ledger/pairwise_view/ranking_view` 입력이 결정화되었고, R-05 백테스트를 위해 실제 레이팅 리플레이 엔진이 필요합니다.
- 이번 단계는 알고리즘 최종 선택이 목적이 아니라, **동일 입력/동일 인터페이스로 Glicko-2와 TrueSkill을 비교 가능하게 만드는 것**이 목적입니다.
- 연령 보정(R-06), 기록 앵커(R-07), 파라미터 튜닝(R-12)은 범위 밖으로 두고 순수 베이스라인만 고정합니다.

## 결정

1. `rating/engine` 패키지에 공통 `Predictor` 인터페이스를 둡니다.
   - `predict_prob(a, b, as_of) -> float`
   - `update(state, race_results) -> state`
2. Glicko-2는 `rating/engine/glicko2.py`에서 직접 구현합니다.
   - 내부 계산은 Glickman 원문 스케일(`400 / ln(10)`)을 사용합니다.
   - volatility는 원문 반복 절차(Illinois)를 사용하고, 수렴 실패 시 예외를 발생시킵니다.
3. TrueSkill은 `rating/engine/trueskill_wrapper.py`에서 라이브러리 래퍼로 구현합니다.
   - 최종 선택용이 아니라 R-05 비교 기준 엔진입니다.
4. 리플레이 실행기는 `rating/engine/runner.py`로 고정합니다.
   - 기본 period: `meet` (`month` 옵션 지원)
   - 기본 엔진: `glicko2` (`trueskill`은 `--engine trueskill`로 별도 실행)
5. 다인전 pairwise 변환은 `w = 1/(N-1)` 가중치를 기본 반영합니다.
   - 라운드 가중치(`weight`)와 곱으로 결합합니다.
6. 출력은 `out/ratings_baseline.parquet`를 기본 산출물로 둡니다.
   - 컬럼: `athlete_id, valid_date, mu, phi, sigma, n_games`
   - 요약 리포트(`out/baseline_report.md`)에 `mu/phi/n_games` 분포, `phi>300` 비율, 실행 시간을 기록합니다.

## 비활동 처리 기준

- `meet` period에서는 빈 period를 명시적으로 순회하지 않으므로, **경과 월 수 기반**으로 불확실성 증가를 반영합니다.
- 구현은 기존 상태와 현재 period 사이 경과량을 계산해 `phi`를 증가시키고, 초기 불확실성 상한(350)을 넘지 않도록 제한합니다.

## 유보 사항

- 종목별(500/1000/1500) 분리 레이팅 여부는 이번 ADR에서 확정하지 않습니다.
- R-04는 종목 통합 단일 풀을 유지하고, R-05에서 예측 지표로 분리/통합 우열을 판단합니다.

