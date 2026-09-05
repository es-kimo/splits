# ADR 0009 — 연령 성장 모델 1차 결정 (R-06)

- 상태: Accepted
- 작성시각: 2026-08-30T00:10
- 선행: `docs/adr/0006-backtest-verdict-rerun.md`, `docs/adr/0007-sigma-inversion.md`

## 문맥

- R-06 목표는 신인 구간 약점(`n_games 0-5`)을 개선하면서, 기존 상위권 구간(`21+`) 성능을 훼손하지 않는 것입니다.
- 연령 정보는 `data/records_anon.csv`를 기준으로 점검했고, 결과는 `out/age_data_audit.md`에 고정했습니다.

## 데이터 입력 결정

| 항목 | 관측 |
| --- | --- |
| 출생연도 | 126,553/128,912 (98.17%), 선수 충돌 0 |
| 학년 | 26,385/128,912 (20.47%) |
| 학령구간 | 127,795/128,912 (99.13%) |
| 성별 | 128,846/128,912 (99.95%) |

결정:

1. 연령은 `age = season_year - birth_year`를 사용합니다.
2. 학년은 1차 입력에서 제외합니다(커버리지 부족).
3. 생월 부재로 인한 ±1세 오차를 한계로 명시합니다.

## 구현 결정

1. ledger에 `birth_year`, `division_text`를 추가하고, `athlete_meta.parquet`를 함께 생성합니다.
2. `rating.engine.age`에 다음을 추가했습니다.
   - `fit_debut_priors`
   - `debut_prior`
   - `build_debut_prior_provider`
   - `fit_age_baseline`, `fit_age_volatility`, `normalize`
3. `rating.eval.backtest`에 `--config {baseline,age_adjusted}`를 추가하고, `age_adjusted`에서는 TrueSkill 신인 초기값에 데뷔 사전분포를 주입합니다.
4. `out/rating_run.json`에 `debut_prior_digest`, `tau_by_age_band`, `age_meta_digest` 필드를 추가했습니다.

## 연령 정규화/신인 사전분포 산출

- `out/ratings_age_adjusted.parquet` 생성
- `out/age_curves.md` 생성(연령 베이스라인, 변동성, 이탈률, 데뷔 사전분포)
- 데뷔 사전분포는 셀 표본 `k<10`에서 성별 fallback으로 축소합니다.
  - 예: `오픈/여` 표본 8명 → `shrink_sex`

## 백테스트 관측 (동일 하네스, holdout 2025~2026)

best config 기준 비교:

| 구간 | baseline | age_adjusted | 변화 |
| --- | ---: | ---: | ---: |
| 전체 log loss | 0.56485 | 0.55677 | -0.00808 |
| `n_games 0-5` accuracy | 0.5480 | 0.5734 | +0.0254p |
| `21+` log loss | 0.56618 | 0.56167 | -0.00451 |

판정:

- 신인 구간 정확도는 개선됐지만, R-06 목표치(0.62)에는 아직 미달입니다.
- `21+` 구간은 악화되지 않았고 오히려 소폭 개선됐습니다.

## tau(age), 드리프트 항 결정

- 사전 고정한 연령 구간은 `<=12`, `13-15`, `16+`입니다. 전역 기준값은 모든
  구간 `tau=0.50`이며, 각 후보는 한 구간만 `0.25` 또는 `1.00`으로 변경했습니다.
  평가셋은 conservative 정책의 마지막 2시즌이고, 신인 사전분포와 Platt 보정은
  모든 후보에서 동일하게 적용했습니다.

| profile | tau <=12 | tau 13-15 | tau 16+ | log loss | 95% CI | 전역 CI와 겹침 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| global | 0.50 | 0.50 | 0.50 | 0.55677 | 0.54768–0.56624 | 기준 |
| growth-high | 0.50 | 1.00 | 0.50 | 0.55585 | 0.54666–0.56533 | 예 |
| growth-low | 0.50 | 0.25 | 0.50 | 0.55986 | 0.55092–0.56869 | 예 |
| older-high | 0.50 | 0.50 | 1.00 | 0.56116 | 0.55193–0.57047 | 예 |
| older-low | 0.50 | 0.50 | 0.25 | 0.55685 | 0.54779–0.56609 | 예 |
| younger-high | 1.00 | 0.50 | 0.50 | 0.55178 | 0.54196–0.56154 | 예 |
| younger-low | 0.25 | 0.50 | 0.50 | 0.56293 | 0.55419–0.57192 | 예 |

- `younger-high`가 log loss 0.55178로 가장 낮지만, 모든 후보의 95% 구간이 전역
  기준과 겹칩니다. 점추정 차이를 재현 가능한 연령별 파라미터로 승격할 근거가
  없으므로 **tau(age)는 기각(식별 불가)** 합니다.
- 프로덕션은 전역 tau를 유지하고 `tau_by_age_band`는 빈 값으로 둡니다. 상세 결과는
  `out/age_tau_report.md`에 기록합니다.
- 드리프트 항(`g(age)·Δ`)은 tau(age) 채택을 사전 조건으로 했습니다. 조건이
  충족되지 않았으므로 이번 범위에서는 적용하지 않습니다.

## 생존 편향 관측

- `out/age_curves.md`의 age→age+1 이탈률은 중등~고등 구간에서 20~35%대가 반복됩니다.
- 따라서 고연령 구간 중심값 상승은 성장과 선발/이탈 효과를 함께 해석해야 합니다.

## 재현

```bash
python3 scripts/audit_age_availability.py
make rating-age
make rating-age-tau
python -m rating.eval.backtest --ledger out/ledger_age_policies --all-configs --config baseline
python -m rating.eval.backtest --ledger out/ledger_age_policies --all-configs --config age_adjusted
```
