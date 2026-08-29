# ADR 0005 — 백테스트 판정 (R-05)

- 상태: Proposed
- 작성시각: 2026-08-29T16:20:00
- 선행: `docs/adr/0004-glicko2-baseline.md`

## 문맥

- R-05는 정책 3종 × rating period 2종 × 엔진 2종(총 12설정)을 동일 하네스에서 비교해 GO/조건부/STOP을 판정합니다.
- 최종 수치와 판정은 `python -m rating.eval.backtest --ledger out/ledger --holdout-seasons 2 --all-configs --out out/backtest_report.md` 실행 시 이 문서를 자동 갱신합니다.

## 판정 규칙

| 조건 | 판정 |
| --- | --- |
| log loss 개선율 >= 5% AND calibration 양호 | GO |
| 1% <= 개선율 < 5% | 조건부 |
| 개선율 < 1% 또는 B3와 동등/열위 | STOP |

## 메모

- 캘리브레이션 양호 기준: ECE와 70% 구간 과신 여부를 함께 기록합니다.
- 판정 근거 표와 세그먼트 분해는 `out/backtest_report.md`를 단일 소스로 사용합니다.

