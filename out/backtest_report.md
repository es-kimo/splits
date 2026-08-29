# R-05 Backtest Report

- generated_at: 2026-08-29T16:42:39
- holdout_seasons: 2025, 2026
- configs: 12

## 모델 설정 요약

| policy | period | engine | n | log_loss | accuracy | brier | ece | B3 대비 개선율 | 70% 과신 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conservative | meet | glicko2 | 18,425 | 0.58325 | 0.6903 | 0.19910 | 0.03384 | 6.52% | N |
| conservative | month | glicko2 | 18,425 | 0.58524 | 0.6883 | 0.20008 | 0.03368 | 6.86% | N |
| conservative | meet | trueskill | 18,425 | 0.58877 | 0.7134 | 0.19410 | 0.07204 | 5.63% | Y |
| conservative | month | trueskill | 18,425 | 0.59542 | 0.7091 | 0.19657 | 0.07545 | 5.24% | Y |
| aggressive | meet | glicko2 | 20,777 | 0.60612 | 0.6689 | 0.20887 | 0.03964 | 5.79% | N |
| aggressive | month | glicko2 | 20,777 | 0.60749 | 0.6678 | 0.20958 | 0.03883 | 6.11% | N |
| aggressive | meet | trueskill | 20,777 | 0.61399 | 0.6831 | 0.20763 | 0.06840 | 4.57% | N |
| aggressive | month | trueskill | 20,777 | 0.61926 | 0.6791 | 0.20964 | 0.07293 | 4.29% | Y |
| place_only | meet | glicko2 | 4,864 | 0.66656 | 0.6016 | 0.23638 | 0.05910 | 2.33% | Y |
| place_only | month | glicko2 | 4,864 | 0.66685 | 0.6016 | 0.23654 | 0.05869 | 2.36% | Y |
| place_only | month | trueskill | 4,864 | 0.68092 | 0.6049 | 0.23927 | 0.07704 | 0.30% | Y |
| place_only | meet | trueskill | 4,864 | 0.68168 | 0.6073 | 0.23957 | 0.07613 | 0.11% | Y |

## 로그손실 95% 신뢰구간 (레이스 단위 블록 부트스트랩)

같은 레이스의 비교들은 독립이 아니므로 레이스를 통째로 리샘플링합니다.
구간이 겹치면 두 설정의 차이를 노이즈와 구분할 수 없습니다.

| policy | period | engine | log_loss | CI 하한 | CI 상한 | 최적 설정과 겹침 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| conservative | meet | glicko2 | 0.58325 | 0.57202 | 0.59454 | (최적) |
| conservative | month | glicko2 | 0.58524 | 0.57395 | 0.59658 | Y |
| conservative | meet | trueskill | 0.58877 | 0.57265 | 0.60395 | Y |
| conservative | month | trueskill | 0.59542 | 0.57933 | 0.61082 | Y |
| aggressive | meet | glicko2 | 0.60612 | 0.59627 | 0.61647 | N |
| aggressive | month | glicko2 | 0.60749 | 0.59758 | 0.61729 | N |
| aggressive | meet | trueskill | 0.61399 | 0.59982 | 0.62832 | N |
| aggressive | month | trueskill | 0.61926 | 0.60502 | 0.63296 | N |
| place_only | meet | glicko2 | 0.66656 | 0.64751 | 0.68509 | N |
| place_only | month | glicko2 | 0.66685 | 0.64779 | 0.68542 | N |
| place_only | month | trueskill | 0.68092 | 0.65602 | 0.70558 | N |
| place_only | meet | trueskill | 0.68168 | 0.65688 | 0.70612 | N |

## 12설정 × 4베이스라인 로그손실

| policy | period | engine | B0 | B1 | B2 | B3 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| aggressive | meet | glicko2 | 0.69315 | 0.64972 | 0.65615 | 0.64340 |
| aggressive | meet | trueskill | 0.69315 | 0.64972 | 0.65615 | 0.64340 |
| aggressive | month | glicko2 | 0.69315 | 0.65091 | 0.65615 | 0.64699 |
| aggressive | month | trueskill | 0.69315 | 0.65091 | 0.65615 | 0.64699 |
| conservative | meet | glicko2 | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| conservative | meet | trueskill | 0.69315 | 0.63529 | 0.64839 | 0.62391 |
| conservative | month | glicko2 | 0.69315 | 0.63720 | 0.64839 | 0.62832 |
| conservative | month | trueskill | 0.69315 | 0.63720 | 0.64839 | 0.62832 |
| place_only | meet | glicko2 | 0.69315 | 0.67855 | 0.68882 | 0.68245 |
| place_only | meet | trueskill | 0.69315 | 0.67855 | 0.68882 | 0.68245 |
| place_only | month | glicko2 | 0.69315 | 0.67791 | 0.68882 | 0.68299 |
| place_only | month | trueskill | 0.69315 | 0.67791 | 0.68882 | 0.68299 |

베이스라인 로지스틱 스케일은 홀드아웃 이전 구간에서 log loss 최소화로 적합했습니다.

| policy | period | B2 scale | B2 적합표본 | B3 scale | B3 적합표본 |
| --- | --- | ---: | ---: | ---: | ---: |
| aggressive | meet | 0.08629 | 11,696 | 0.78492 | 139,564 |
| aggressive | month | 0.08629 | 11,696 | 0.82922 | 137,427 |
| conservative | meet | 0.07115 | 10,053 | 0.63719 | 121,190 |
| conservative | month | 0.07115 | 10,053 | 0.67348 | 119,302 |
| place_only | meet | 0.40407 | 1,897 | 1.41782 | 30,310 |
| place_only | month | 0.40407 | 1,897 | 1.48183 | 29,809 |

## 공통 부분집합 비교 (B1/B2 both-covered)

| policy | period | engine | subset_n | model | B0 | B1 | B2 | B3 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| aggressive | meet | glicko2 | 12,152 | 0.58631 | 0.69315 | 0.64300 | 0.64530 | 0.64926 |
| aggressive | meet | trueskill | 12,152 | 0.57788 | 0.69315 | 0.64300 | 0.64530 | 0.64926 |
| aggressive | month | glicko2 | 12,073 | 0.58812 | 0.69315 | 0.64388 | 0.64550 | 0.65345 |
| aggressive | month | trueskill | 12,073 | 0.58241 | 0.69315 | 0.64388 | 0.64550 | 0.65345 |
| conservative | meet | glicko2 | 10,552 | 0.55980 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| conservative | meet | trueskill | 10,552 | 0.56326 | 0.69315 | 0.62368 | 0.63666 | 0.62740 |
| conservative | month | glicko2 | 10,480 | 0.56163 | 0.69315 | 0.62541 | 0.63695 | 0.63326 |
| conservative | month | trueskill | 10,480 | 0.56870 | 0.69315 | 0.62541 | 0.63695 | 0.63326 |
| place_only | meet | glicko2 | 1,973 | 0.64146 | 0.69315 | 0.68618 | 0.68394 | 0.68582 |
| place_only | meet | trueskill | 1,973 | 0.64734 | 0.69315 | 0.68618 | 0.68394 | 0.68582 |
| place_only | month | glicko2 | 1,962 | 0.64221 | 0.69315 | 0.68603 | 0.68413 | 0.68595 |
| place_only | month | trueskill | 1,962 | 0.64805 | 0.69315 | 0.68603 | 0.68413 | 0.68595 |

## 예측 확률 분포와 불확실성

확률이 극단으로 몰리면(판별력은 있는데 스케일이 깨진 상태) 여기서 먼저 드러납니다.
tau는 홀드아웃 이전 구간에서 log loss로 골랐습니다.

| policy | period | engine | tau | p 표준편차 | p<0.1 또는 >0.9 | 불확실성 p50 | 불확실성 p10 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| conservative | meet | glicko2 | 0.2000 | 0.2620 | 12.5% | 68.708 | 43.075 |
| conservative | month | glicko2 | 1.2000 | 0.2601 | 12.1% | 69.123 | 41.983 |
| conservative | meet | trueskill | 1.0000 | 0.3218 | 30.1% | 2.489 | 2.344 |
| conservative | month | trueskill | 1.0000 | 0.3221 | 30.2% | 2.490 | 2.343 |
| aggressive | meet | glicko2 | 0.2000 | 0.2465 | 9.1% | 63.698 | 41.725 |
| aggressive | month | glicko2 | 0.2000 | 0.2448 | 8.8% | 63.796 | 40.607 |
| aggressive | meet | trueskill | 0.5000 | 0.2910 | 20.7% | 1.704 | 1.626 |
| aggressive | month | trueskill | 0.5000 | 0.2916 | 20.9% | 1.705 | 1.626 |
| place_only | meet | glicko2 | 0.2000 | 0.1916 | 2.2% | 107.038 | 59.532 |
| place_only | month | glicko2 | 0.2000 | 0.1906 | 2.2% | 107.074 | 58.365 |
| place_only | month | trueskill | 0.5000 | 0.2204 | 5.9% | 1.735 | 1.599 |
| place_only | meet | trueskill | 0.5000 | 0.2217 | 6.0% | 1.735 | 1.600 |

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
| 21+ | 16,298 | 0.56115 | 0.7077 | 0.19021 |
| 0-5 | 1,341 | 0.92118 | 0.4303 | 0.33479 |
| 6-20 | 786 | 0.46515 | 0.7723 | 0.15192 |

### phi

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| high(> 93.3) | 6,253 | 0.56595 | 0.7024 | 0.19208 |
| low(<= 51.7) | 6,093 | 0.63211 | 0.6480 | 0.22020 |
| mid(51.7~93.3) | 6,079 | 0.55209 | 0.7202 | 0.18517 |

### round

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| semifinal | 5,754 | 0.58046 | 0.6920 | 0.19792 |
| quarterfinal | 5,410 | 0.55685 | 0.7150 | 0.18770 |
| final | 3,449 | 0.63845 | 0.6399 | 0.22240 |
| heat | 2,900 | 0.54735 | 0.7169 | 0.18480 |
| final_b | 912 | 0.66297 | 0.6382 | 0.23153 |

### grade

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| 3 | 4,100 | 0.55297 | 0.7112 | 0.18724 |
| 6 | 3,587 | 0.54347 | 0.7271 | 0.18142 |
| 2 | 3,326 | 0.60904 | 0.6618 | 0.21059 |
| 4 | 2,387 | 0.59245 | 0.6829 | 0.20305 |
| (unknown-grade) | 2,214 | 0.59150 | 0.6825 | 0.20353 |
| 1 | 1,607 | 0.60568 | 0.6727 | 0.20816 |
| 5 | 1,204 | 0.67035 | 0.6404 | 0.23236 |

### event

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| 1500M | 7,016 | 0.58211 | 0.6863 | 0.19941 |
| 500M | 5,162 | 0.58118 | 0.6947 | 0.19791 |
| 1000M | 4,656 | 0.58517 | 0.6929 | 0.19929 |
| 3000M | 921 | 0.57351 | 0.6895 | 0.19547 |
| 2000M | 645 | 0.61049 | 0.6822 | 0.20816 |
| 1000M S.F | 25 | 0.63244 | 0.6400 | 0.22235 |

### source_status

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| FIN-FIN | 18,425 | 0.58325 | 0.6903 | 0.19910 |


## GO/STOP 판정

- best_config: `conservative/meet/glicko2`
- best_log_loss: **0.58325**
- B3_log_loss: **0.62391**
- improvement_vs_B3: **6.52%**
- holdout 비율: **18,425 / 165,399** (11.1%)
- verdict: **조건부**

| 조건 | 관측값 | 통과 |
| --- | ---: | --- |
| 개선율 >= 5% | 6.52% | Y |
| ECE <= 0.03 | 0.03384 | N |
| 70% 과신 없음 | N | Y |

GO를 막은 조건: ECE <= 0.03 (관측 0.03384)
