# R-05 Backtest Report

- generated_at: 2026-08-29T22:25:57
- holdout_seasons: 2025, 2026
- configs: 12

## 모델 설정 요약

| policy | period | engine | n | log_loss | accuracy | brier | ece | B3 대비 개선율 | 70% 과신 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conservative | meet | trueskill | 18,425 | 0.55510 | 0.7123 | 0.18800 | 0.01487 | 11.03% | N |
| conservative | month | trueskill | 18,425 | 0.55916 | 0.7078 | 0.18985 | 0.01292 | 10.38% | N |
| aggressive | meet | trueskill | 18,425 | 0.56454 | 0.7024 | 0.19209 | 0.01081 | 9.52% | N |
| aggressive | month | trueskill | 18,425 | 0.56867 | 0.6985 | 0.19389 | 0.01374 | 8.85% | N |
| conservative | meet | glicko2 | 18,425 | 0.57896 | 0.6912 | 0.19793 | 0.01122 | 7.20% | N |
| aggressive | meet | glicko2 | 18,425 | 0.58005 | 0.6892 | 0.19841 | 0.01199 | 7.03% | N |
| conservative | month | glicko2 | 18,425 | 0.58127 | 0.6894 | 0.19895 | 0.01306 | 6.83% | N |
| aggressive | month | glicko2 | 18,425 | 0.58246 | 0.6860 | 0.19945 | 0.01439 | 6.64% | N |
| place_only | meet | trueskill | 18,425 | 0.63877 | 0.6134 | 0.22461 | 0.02148 | -2.38% | N |
| place_only | month | trueskill | 18,425 | 0.63903 | 0.6131 | 0.22470 | 0.02166 | -2.42% | N |
| place_only | meet | glicko2 | 18,425 | 0.64315 | 0.6199 | 0.22652 | 0.01438 | -3.08% | N |
| place_only | month | glicko2 | 18,425 | 0.64342 | 0.6179 | 0.22663 | 0.01570 | -3.13% | N |

## 로그손실 95% 신뢰구간 (레이스 단위 블록 부트스트랩)

같은 레이스의 비교들은 독립이 아니므로 레이스를 통째로 리샘플링합니다.
구간이 겹치면 두 설정의 차이를 노이즈와 구분할 수 없습니다.

| policy | period | engine | log_loss | CI 하한 | CI 상한 | 최적 설정과 겹침 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| conservative | meet | trueskill | 0.55510 | 0.54525 | 0.56434 | (최적) |
| conservative | month | trueskill | 0.55916 | 0.54970 | 0.56830 | Y |
| aggressive | meet | trueskill | 0.56454 | 0.55500 | 0.57344 | Y |
| aggressive | month | trueskill | 0.56867 | 0.55963 | 0.57705 | Y |
| conservative | meet | glicko2 | 0.57896 | 0.57005 | 0.58771 | N |
| aggressive | meet | glicko2 | 0.58005 | 0.57106 | 0.58843 | N |
| conservative | month | glicko2 | 0.58127 | 0.57273 | 0.58987 | N |
| aggressive | month | glicko2 | 0.58246 | 0.57359 | 0.59099 | N |
| place_only | meet | trueskill | 0.63877 | 0.63267 | 0.64554 | N |
| place_only | month | trueskill | 0.63903 | 0.63320 | 0.64534 | N |
| place_only | meet | glicko2 | 0.64315 | 0.63721 | 0.64939 | N |
| place_only | month | glicko2 | 0.64342 | 0.63781 | 0.64950 | N |

## 12설정 × 4베이스라인 로그손실

| policy | period | engine | B0 | B1 | B2 | B3 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| aggressive | meet | glicko2 | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| aggressive | meet | trueskill | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| aggressive | month | glicko2 | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| aggressive | month | trueskill | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| conservative | meet | glicko2 | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| conservative | meet | trueskill | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| conservative | month | glicko2 | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| conservative | month | trueskill | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| place_only | meet | glicko2 | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| place_only | meet | trueskill | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| place_only | month | glicko2 | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| place_only | month | trueskill | 0.69315 | 0.63529 | 0.64839 | 0.62391 |

베이스라인 로지스틱 스케일은 홀드아웃 이전 구간에서 log loss 최소화로 적합했습니다.

| policy | period | B2 scale | B2 적합표본 | B3 scale | B3 적합표본 |
| --- | --- | ---: | ---: | ---: | ---: |
| aggressive | meet | 0.07115 | 10,053 | 0.63719 | 121,190 |
| aggressive | month | 0.07115 | 10,053 | 0.63719 | 121,190 |
| conservative | meet | 0.07115 | 10,053 | 0.63719 | 121,190 |
| conservative | month | 0.07115 | 10,053 | 0.63719 | 121,190 |
| place_only | meet | 0.07115 | 10,053 | 0.63719 | 121,190 |
| place_only | month | 0.07115 | 10,053 | 0.63719 | 121,190 |

## 공통 부분집합 비교 (B1/B2 both-covered)

| policy | period | engine | subset_n | model | B0 | B1 | B2 | B3 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aggressive | meet | glicko2 | 10,552 | 0.56562 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| aggressive | meet | trueskill | 10,552 | 0.54800 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| aggressive | month | glicko2 | 10,552 | 0.56863 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| aggressive | month | trueskill | 10,552 | 0.55254 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| conservative | meet | glicko2 | 10,552 | 0.56303 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| conservative | meet | trueskill | 10,552 | 0.54547 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| conservative | month | glicko2 | 10,552 | 0.56568 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| conservative | month | trueskill | 10,552 | 0.54916 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| place_only | meet | glicko2 | 10,552 | 0.62131 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| place_only | meet | trueskill | 10,552 | 0.60691 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| place_only | month | glicko2 | 10,552 | 0.62268 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| place_only | month | trueskill | 10,552 | 0.60828 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |

## 사후 보정 (Platt scaling)

캘리브레이션은 사후 보정으로 고칠 수 있지만 판별력은 어떤 후처리로도 못 늘립니다.
보정 전 비교는 고칠 수 있는 약점과 못 고치는 약점을 같은 무게로 재게 되므로,
두 엔진에 동일한 보정을 적용한 뒤 비교합니다. 보정기는 홀드아웃 직전 시즌에서 적합했습니다.
단조 변환이라 정확도는 보정 전후가 같습니다.

| policy | period | engine | slope | intercept | log_loss 보정전 | 보정후 | ECE 보정전 | 보정후 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| conservative | meet | trueskill | 0.5763 | +0.0191 | 0.58584 | 0.55510 | 0.06728 | 0.01487 |
| conservative | month | trueskill | 0.5586 | +0.0197 | 0.59207 | 0.55916 | 0.07122 | 0.01292 |
| aggressive | meet | trueskill | 0.6592 | +0.0209 | 0.57857 | 0.56454 | 0.05181 | 0.01081 |
| aggressive | month | trueskill | 0.6196 | +0.0223 | 0.58399 | 0.56867 | 0.05610 | 0.01374 |
| conservative | meet | glicko2 | 0.7636 | +0.0222 | 0.58325 | 0.57896 | 0.03384 | 0.01122 |
| aggressive | meet | glicko2 | 0.8260 | +0.0225 | 0.58138 | 0.58005 | 0.02186 | 0.01199 |
| conservative | month | glicko2 | 0.7417 | +0.0220 | 0.58524 | 0.58127 | 0.03368 | 0.01306 |
| aggressive | month | glicko2 | 0.7985 | +0.0226 | 0.58344 | 0.58246 | 0.02135 | 0.01439 |
| place_only | meet | trueskill | 0.5883 | +0.0267 | 0.65489 | 0.63877 | 0.07294 | 0.02148 |
| place_only | month | trueskill | 0.5709 | +0.0264 | 0.65451 | 0.63903 | 0.07180 | 0.02166 |
| place_only | meet | glicko2 | 0.7272 | +0.0310 | 0.64702 | 0.64315 | 0.03603 | 0.01438 |
| place_only | month | glicko2 | 0.7092 | +0.0312 | 0.64702 | 0.64342 | 0.03518 | 0.01570 |

## ECE 유한표본 귀무분포

ECE는 유한표본에서 위로 편향됩니다. 완전히 캘리브레이션된 예측기도 0이 나오지 않으므로,
관측 ECE가 노이즈 바닥 위인지 확인해야 게이트를 해석할 수 있습니다.
예측 확률은 그대로 두고 라벨만 그 확률에서 뽑아 귀무분포를 만들었습니다.

| policy | period | engine | 관측 ECE | 귀무 p50 | 귀무 p95 | 귀무 p99 | 노이즈 초과 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| conservative | meet | trueskill | 0.01487 | 0.00740 | 0.01139 | 0.01251 | Y |
| conservative | month | trueskill | 0.01292 | 0.00750 | 0.01138 | 0.01333 | Y |
| aggressive | meet | trueskill | 0.01081 | 0.00745 | 0.01112 | 0.01216 | N |
| aggressive | month | trueskill | 0.01374 | 0.00740 | 0.01128 | 0.01323 | Y |
| conservative | meet | glicko2 | 0.01122 | 0.00759 | 0.01140 | 0.01364 | N |
| aggressive | meet | glicko2 | 0.01199 | 0.00766 | 0.01158 | 0.01268 | Y |
| conservative | month | glicko2 | 0.01306 | 0.00768 | 0.01130 | 0.01377 | Y |
| aggressive | month | glicko2 | 0.01439 | 0.00764 | 0.01143 | 0.01354 | Y |
| place_only | meet | trueskill | 0.02148 | 0.00711 | 0.01110 | 0.01296 | Y |
| place_only | month | trueskill | 0.02166 | 0.00710 | 0.01105 | 0.01278 | Y |
| place_only | meet | glicko2 | 0.01438 | 0.00709 | 0.01125 | 0.01317 | Y |
| place_only | month | glicko2 | 0.01570 | 0.00711 | 0.01081 | 0.01258 | Y |

## 예측 확률 분포와 불확실성

확률이 극단으로 몰리면(판별력은 있는데 스케일이 깨진 상태) 여기서 먼저 드러납니다.
tau는 홀드아웃 이전 구간에서 log loss로 골랐습니다.

| policy | period | engine | tau | p 표준편차 | p<0.1 또는 >0.9 | 불확실성 p50 | 불확실성 p10 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| conservative | meet | trueskill | 1.0000 | 0.2423 | 10.3% | 3.179 | 2.721 |
| conservative | month | trueskill | 1.0000 | 0.2373 | 9.3% | 3.194 | 2.737 |
| aggressive | meet | trueskill | 0.5000 | 0.2328 | 7.9% | 2.066 | 1.827 |
| aggressive | month | trueskill | 0.5000 | 0.2239 | 6.5% | 2.071 | 1.830 |
| conservative | meet | glicko2 | 0.2000 | 0.2207 | 4.8% | 68.708 | 43.075 |
| aggressive | meet | glicko2 | 0.2000 | 0.2191 | 4.5% | 65.403 | 41.823 |
| conservative | month | glicko2 | 1.2000 | 0.2145 | 3.7% | 69.124 | 41.983 |
| aggressive | month | glicko2 | 0.2000 | 0.2122 | 3.5% | 65.596 | 40.667 |
| place_only | meet | trueskill | 0.5000 | 0.1565 | 1.1% | 2.751 | 2.116 |
| place_only | month | trueskill | 0.5000 | 0.1520 | 0.9% | 2.756 | 2.119 |
| place_only | meet | glicko2 | 0.2000 | 0.1494 | 0.5% | 137.138 | 62.769 |
| place_only | month | glicko2 | 0.2000 | 0.1457 | 0.3% | 138.308 | 61.679 |

## 캘리브레이션 플롯

- `aggressive/meet/glicko2`: ![](backtest_calibration/aggressive-meet-glicko2.svg)
- `aggressive/meet/trueskill`: ![](backtest_calibration/aggressive-meet-trueskill.svg)
- `aggressive/month/glicko2`: ![](backtest_calibration/aggressive-month-glicko2.svg)
- `aggressive/month/trueskill`: ![](backtest_calibration/aggressive-month-trueskill.svg)
- `conservative/meet/glicko2`: ![](backtest_calibration/conservative-meet-glicko2.svg)
- `conservative/meet/trueskill`: ![](backtest_calibration/conservative-meet-trueskill.svg)
- `conservative/month/glicko2`: ![](backtest_calibration/conservative-month-glicko2.svg)
- `conservative/month/trueskill`: ![](backtest_calibration/conservative-month-trueskill.svg)
- `place_only/meet/glicko2`: ![](backtest_calibration/place_only-meet-glicko2.svg)
- `place_only/meet/trueskill`: ![](backtest_calibration/place_only-meet-trueskill.svg)
- `place_only/month/glicko2`: ![](backtest_calibration/place_only-month-glicko2.svg)
- `place_only/month/trueskill`: ![](backtest_calibration/place_only-month-trueskill.svg)

## 세그먼트 분해 (best config)

### n_games

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| 21+ | 12,457 | 0.56497 | 0.7113 | 0.19082 |
| 6-20 | 3,776 | 0.45847 | 0.7842 | 0.14978 |
| 0-5 | 2,192 | 0.66545 | 0.5940 | 0.23782 |

### sigma

sigma는 레이팅의 불확실성입니다. 값이 클수록 그 선수의 실력을 아직 덜 안다는 뜻이고, 쌍에서는 두 선수 중 큰 쪽을 씁니다. sigma-오차 역전의 원인 분석은 `docs/adr/0007-sigma-inversion.md`에 있습니다.

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| high(> 3.5) | 6,263 | 0.55269 | 0.7097 | 0.18711 |
| low(<= 3.0) | 6,100 | 0.58437 | 0.6892 | 0.19984 |
| mid(3.0~3.5) | 6,062 | 0.52813 | 0.7382 | 0.17701 |

### round

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| semifinal | 5,754 | 0.55234 | 0.7178 | 0.18663 |
| quarterfinal | 5,410 | 0.52596 | 0.7316 | 0.17660 |
| final | 3,449 | 0.61411 | 0.6729 | 0.21103 |
| heat | 2,900 | 0.51594 | 0.7379 | 0.17290 |
| final_b | 912 | 0.64673 | 0.6305 | 0.22521 |

### grade

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| 3 | 4,100 | 0.51578 | 0.7488 | 0.17149 |
| 6 | 3,587 | 0.50664 | 0.7474 | 0.16893 |
| 2 | 3,326 | 0.59441 | 0.6879 | 0.20267 |
| 4 | 2,387 | 0.57063 | 0.6879 | 0.19623 |
| (unknown-grade) | 2,214 | 0.57317 | 0.6847 | 0.19610 |
| 1 | 1,607 | 0.59776 | 0.6857 | 0.20433 |
| 5 | 1,204 | 0.60379 | 0.6852 | 0.20752 |

### event

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| 1500M | 7,016 | 0.55438 | 0.7115 | 0.18817 |
| 500M | 5,162 | 0.54912 | 0.7164 | 0.18544 |
| 1000M | 4,656 | 0.56520 | 0.7025 | 0.19177 |
| 3000M | 921 | 0.54440 | 0.7307 | 0.18204 |
| 2000M | 645 | 0.54821 | 0.7349 | 0.18591 |
| 1000M S.F | 25 | 0.68092 | 0.6400 | 0.24134 |

### source_status

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| FIN-FIN | 18,425 | 0.55510 | 0.7123 | 0.18800 |


## GO/STOP 판정

- best_config: `conservative/meet/trueskill`
- best_log_loss: **0.55510**
- B3_log_loss: **0.62391**
- improvement_vs_B3: **11.03%**
- holdout 비율: **18,425 / 165,399** (11.1%)
- verdict: **GO**

| 조건 | 관측값 | 통과 |
| --- | ---: | --- |
| 개선율 >= 5% | 11.03% | Y |
| ECE <= 0.03 | 0.01487 | Y |
| 70% 과신 없음 | N | Y |
