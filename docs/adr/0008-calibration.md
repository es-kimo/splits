# ADR 0008 — 사후 보정 레이어 프로덕션화 (R-17)

- 상태: Accepted
- 작성시각: 2026-08-29T23:00
- 선행: `docs/adr/0006-backtest-verdict-rerun.md`, `docs/adr/0007-sigma-inversion.md`
- 연계 이슈: R-09(실행 레지스트리), R-12(파라미터 스윕)

## 문맥

R-05/R-20 기준 최적 설정(`conservative/meet/trueskill`)에서 Platt 보정은 로그 손실을 유의미하게 낮춥니다.
하지만 기존 구현은 `rating.eval.metrics` 내부 평가 헬퍼에 머물러 실행 산출물/버전 관리/재적합 프로토콜이 없었습니다.

R-17에서는 보정기를 프로덕션 경로로 승격하고, 보정 전/후 확률 재현성과 폴드 경계(누수 방지)를 코드로 강제합니다.

## 결정 1) 적합 폴드 위치

프로토콜 리포트(`out/calibration_report.md`)에서 다음 세 arm을 비교했습니다.

| arm | 설명 | holdout log loss | 비고 |
| --- | --- | ---: | --- |
| A | 직전 학습 시즌 적합 (`season=2024`) | 0.55510 | 현행 |
| B | 한 시즌 앞당긴 전용 폴드 (`season=2023`) | 0.55591 | 대체안 |
| C | 홀드아웃 직접 적합 | 0.55493 | 누수 참조값(판정 제외) |

사전 등록 규칙은 `|Δ(B-A)| <= 0.005`이면 현행 유지였습니다. 관측값은 `+0.00082`로 기준 이내이므로 **현행(A) 유지**로 결정합니다.

## 결정 2) 재적합 주기

최근 4개 시즌으로 계수 변동을 측정했습니다.

| fit_season | sample | slope | intercept | holdout log loss |
| ---: | ---: | ---: | ---: | ---: |
| 2021 | 13,477 | 0.58911 | -0.02408 | 0.55497 |
| 2022 | 12,458 | 0.62576 | +0.00215 | 0.55515 |
| 2023 | 14,098 | 0.66102 | -0.01258 | 0.55591 |
| 2024 | 15,465 | 0.57632 | +0.01911 | 0.55510 |

`slope span=0.08470`, `intercept span=0.04319`로 계수 이동이 작지 않으므로 **실행마다 재적합**을 기본 정책으로 채택합니다.
또한 엔진 파라미터(`tau`, 초기 분산, period 규약) 또는 학습 정책이 바뀌면 보정기를 반드시 재적합합니다.

## 결정 3) 세그먼트 분리 보정

sigma/n_games 구간별 전역 보정 성능과, 같은 구간에서 누수 참조 상한 이득을 비교했습니다.

| segment | n | global log loss | global ECE | 분리 이득 상한(누수 참조) |
| --- | ---: | ---: | ---: | ---: |
| sigma/high | 6,138 | 0.55678 | 0.03048 | 0.00324 |
| sigma/mid | 6,144 | 0.52507 | 0.03591 | 0.00353 |
| sigma/low | 6,143 | 0.58346 | 0.02729 | 0.00182 |
| n_games/0-5 | 2,192 | 0.66545 | 0.09616 | 0.00000 |
| n_games/6-20 | 3,776 | 0.45847 | 0.04495 | 0.00000 |
| n_games/21+ | 12,457 | 0.56497 | 0.02774 | 0.00000 |

판정 기준(표본 `n>=200`에서 상한 이득 `>0.01`)을 넘는 구간이 없어 **전역 보정 유지**로 결정합니다.

## 구현 결정

1. `rating/calibration/platt.py`를 단일 출처로 사용합니다.
   `fit(probs, labels, fold_id) -> Calibrator`, `Calibrator.apply(prob) -> prob`, `to_json()/from_json()/digest()`를 제공합니다.
2. 보정기 없이 확률을 반환하는 공개 경로를 금지합니다.
   `rating.eval.backtest.evaluate()`는 `calibrator`를 필수 인자로 받습니다.
3. 리플레이 산출물에 보정기를 포함합니다.
   - `out/calibrator.json`
   - `out/rating_run.json` (`run_id`, `calibrator_json`, `ledger_digest`, 보정 전/후 확률 digest)

## 누수 방지 규칙

- 보정기 적합은 홀드아웃 이전 시즌에서만 수행합니다.
- 홀드아웃 직접 적합은 참조값(C arm) 계산에만 사용하며 판정/배포 경로에서는 금지합니다.
- 예측은 항상 갱신 전에 계산합니다(선예측 후갱신 순서 유지).

## 재현

```bash
python -m rating.engine.runner --ledger /Users/kihyun/orgs/personal/splits/out/ledger --out out/ratings_baseline.parquet --report out/baseline_report.md
python -m rating.calibration.protocol --ledger /Users/kihyun/orgs/personal/splits/out/ledger --policy conservative --rating-period meet --engine trueskill --out out/calibration_report.md
```
