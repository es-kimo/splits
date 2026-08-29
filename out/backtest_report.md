# R-05 Backtest Report

- generated_at: 2026-08-29T23:57:13
- holdout_seasons: 2025, 2026
- configs: 12

## 모델 설정 요약

| config | policy | period | engine | n | log_loss | accuracy | brier | ece | B3 대비 개선율 | 70% 과신 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| age_adjusted | aggressive | meet | trueskill | 19,051 | 0.55677 | 0.7088 | 0.18894 | 0.01735 | 12.05% | N |
| age_adjusted | conservative | meet | trueskill | 19,051 | 0.55677 | 0.7088 | 0.18894 | 0.01735 | 12.05% | N |
| age_adjusted | aggressive | month | trueskill | 19,051 | 0.55847 | 0.7072 | 0.18958 | 0.01809 | 11.78% | N |
| age_adjusted | conservative | month | trueskill | 19,051 | 0.55847 | 0.7072 | 0.18958 | 0.01809 | 11.78% | N |
| age_adjusted | aggressive | meet | glicko2 | 19,051 | 0.58094 | 0.6883 | 0.19879 | 0.01387 | 8.23% | N |
| age_adjusted | conservative | meet | glicko2 | 19,051 | 0.58094 | 0.6883 | 0.19879 | 0.01387 | 8.23% | N |
| age_adjusted | aggressive | month | glicko2 | 19,051 | 0.58322 | 0.6866 | 0.19976 | 0.01750 | 7.87% | N |
| age_adjusted | conservative | month | glicko2 | 19,051 | 0.58322 | 0.6866 | 0.19976 | 0.01750 | 7.87% | N |
| age_adjusted | place_only | meet | glicko2 | 19,051 | 0.64166 | 0.6216 | 0.22584 | 0.01391 | -1.36% | N |
| age_adjusted | place_only | meet | trueskill | 19,051 | 0.64178 | 0.6127 | 0.22609 | 0.01668 | -1.38% | N |
| age_adjusted | place_only | month | glicko2 | 19,051 | 0.64202 | 0.6218 | 0.22599 | 0.01370 | -1.42% | N |
| age_adjusted | place_only | month | trueskill | 19,051 | 0.64203 | 0.6125 | 0.22617 | 0.01630 | -1.42% | N |

## 로그손실 95% 신뢰구간 (레이스 단위 블록 부트스트랩)

같은 레이스의 비교들은 독립이 아니므로 레이스를 통째로 리샘플링합니다.
구간이 겹치면 두 설정의 차이를 노이즈와 구분할 수 없습니다.

| config | policy | period | engine | log_loss | CI 하한 | CI 상한 | 최적 설정과 겹침 |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| age_adjusted | aggressive | meet | trueskill | 0.55677 | 0.54768 | 0.56624 | (최적) |
| age_adjusted | conservative | meet | trueskill | 0.55677 | 0.54768 | 0.56624 | Y |
| age_adjusted | aggressive | month | trueskill | 0.55847 | 0.54886 | 0.56836 | Y |
| age_adjusted | conservative | month | trueskill | 0.55847 | 0.54886 | 0.56836 | Y |
| age_adjusted | aggressive | meet | glicko2 | 0.58094 | 0.57310 | 0.58936 | N |
| age_adjusted | conservative | meet | glicko2 | 0.58094 | 0.57310 | 0.58936 | N |
| age_adjusted | aggressive | month | glicko2 | 0.58322 | 0.57575 | 0.59111 | N |
| age_adjusted | conservative | month | glicko2 | 0.58322 | 0.57575 | 0.59111 | N |
| age_adjusted | place_only | meet | glicko2 | 0.64166 | 0.63586 | 0.64777 | N |
| age_adjusted | place_only | meet | trueskill | 0.64178 | 0.63602 | 0.64797 | N |
| age_adjusted | place_only | month | glicko2 | 0.64202 | 0.63635 | 0.64786 | N |
| age_adjusted | place_only | month | trueskill | 0.64203 | 0.63635 | 0.64824 | N |

## 12설정 × 4베이스라인 로그손실

| config | policy | period | engine | B0 | B1 | B2 | B3 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| age_adjusted | aggressive | meet | glicko2 | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | aggressive | meet | trueskill | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | aggressive | month | glicko2 | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | aggressive | month | trueskill | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | conservative | meet | glicko2 | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | conservative | meet | trueskill | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | conservative | month | glicko2 | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | conservative | month | trueskill | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | place_only | meet | glicko2 | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | place_only | meet | trueskill | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | place_only | month | glicko2 | 0.69315 | 0.63722 | 0.67664 | 0.63306 |
| age_adjusted | place_only | month | trueskill | 0.69315 | 0.63722 | 0.67664 | 0.63306 |

베이스라인 로지스틱 스케일은 홀드아웃 이전 구간에서 log loss 최소화로 적합했습니다.

| config | policy | period | B2 scale | B2 적합표본 | B3 scale | B3 적합표본 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| age_adjusted | aggressive | meet | 0.10816 | 6,253 | 0.60657 | 90,758 |
| age_adjusted | aggressive | month | 0.10816 | 6,253 | 0.60657 | 90,758 |
| age_adjusted | conservative | meet | 0.10816 | 6,253 | 0.60657 | 90,758 |
| age_adjusted | conservative | month | 0.10816 | 6,253 | 0.60657 | 90,758 |
| age_adjusted | place_only | meet | 0.10816 | 6,253 | 0.60657 | 90,758 |
| age_adjusted | place_only | month | 0.10816 | 6,253 | 0.60657 | 90,758 |

## 공통 부분집합 비교 (B1/B2 both-covered)

| config | policy | period | engine | subset_n | model | B0 | B1 | B2 | B3 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| age_adjusted | aggressive | meet | glicko2 | 7,863 | 0.56813 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | aggressive | meet | trueskill | 7,863 | 0.53873 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | aggressive | month | glicko2 | 7,863 | 0.57151 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | aggressive | month | trueskill | 7,863 | 0.54701 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | conservative | meet | glicko2 | 7,863 | 0.56813 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | conservative | meet | trueskill | 7,863 | 0.53873 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | conservative | month | glicko2 | 7,863 | 0.57151 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | conservative | month | trueskill | 7,863 | 0.54701 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | place_only | meet | glicko2 | 7,863 | 0.62201 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | place_only | meet | trueskill | 7,863 | 0.61413 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | place_only | month | glicko2 | 7,863 | 0.62355 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |
| age_adjusted | place_only | month | trueskill | 7,863 | 0.61486 | 0.69315 | 0.63367 | 0.65922 | 0.62270 |

## 사후 보정 (Platt scaling)

캘리브레이션은 사후 보정으로 고칠 수 있지만 판별력은 어떤 후처리로도 못 늘립니다.
보정 전 비교는 고칠 수 있는 약점과 못 고치는 약점을 같은 무게로 재게 되므로,
두 엔진에 동일한 보정을 적용한 뒤 비교합니다. 보정기는 홀드아웃 직전 시즌에서 적합했습니다.
단조 변환이라 정확도는 보정 전후가 같습니다.

| config | policy | period | engine | slope | intercept | log_loss 보정전 | 보정후 | ECE 보정전 | 보정후 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| age_adjusted | aggressive | meet | trueskill | 0.6309 | +0.0372 | 0.57067 | 0.55677 | 0.05220 | 0.01735 |
| age_adjusted | conservative | meet | trueskill | 0.6309 | +0.0372 | 0.57067 | 0.55677 | 0.05220 | 0.01735 |
| age_adjusted | aggressive | month | trueskill | 0.5944 | +0.0407 | 0.58196 | 0.55847 | 0.06245 | 0.01809 |
| age_adjusted | conservative | month | trueskill | 0.5944 | +0.0407 | 0.58196 | 0.55847 | 0.06245 | 0.01809 |
| age_adjusted | aggressive | meet | glicko2 | 0.7465 | +0.0307 | 0.58386 | 0.58094 | 0.03183 | 0.01387 |
| age_adjusted | conservative | meet | glicko2 | 0.7465 | +0.0307 | 0.58386 | 0.58094 | 0.03183 | 0.01387 |
| age_adjusted | aggressive | month | glicko2 | 0.7248 | +0.0310 | 0.58550 | 0.58322 | 0.03060 | 0.01750 |
| age_adjusted | conservative | month | glicko2 | 0.7248 | +0.0310 | 0.58550 | 0.58322 | 0.03060 | 0.01750 |
| age_adjusted | place_only | meet | glicko2 | 0.6975 | +0.0290 | 0.64661 | 0.64166 | 0.04169 | 0.01391 |
| age_adjusted | place_only | meet | trueskill | 0.6254 | +0.0260 | 0.65280 | 0.64178 | 0.06144 | 0.01668 |
| age_adjusted | place_only | month | glicko2 | 0.6826 | +0.0296 | 0.64661 | 0.64202 | 0.04094 | 0.01370 |
| age_adjusted | place_only | month | trueskill | 0.6147 | +0.0269 | 0.65276 | 0.64203 | 0.06118 | 0.01630 |

## ECE 유한표본 귀무분포

ECE는 유한표본에서 위로 편향됩니다. 완전히 캘리브레이션된 예측기도 0이 나오지 않으므로,
관측 ECE가 노이즈 바닥 위인지 확인해야 게이트를 해석할 수 있습니다.
예측 확률은 그대로 두고 라벨만 그 확률에서 뽑아 귀무분포를 만들었습니다.

| config | policy | period | engine | 관측 ECE | 귀무 p50 | 귀무 p95 | 귀무 p99 | 노이즈 초과 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| age_adjusted | aggressive | meet | trueskill | 0.01735 | 0.00730 | 0.01073 | 0.01164 | Y |
| age_adjusted | conservative | meet | trueskill | 0.01735 | 0.00730 | 0.01073 | 0.01164 | Y |
| age_adjusted | aggressive | month | trueskill | 0.01809 | 0.00736 | 0.01079 | 0.01244 | Y |
| age_adjusted | conservative | month | trueskill | 0.01809 | 0.00736 | 0.01079 | 0.01244 | Y |
| age_adjusted | aggressive | meet | glicko2 | 0.01387 | 0.00764 | 0.01164 | 0.01364 | Y |
| age_adjusted | conservative | meet | glicko2 | 0.01387 | 0.00764 | 0.01164 | 0.01364 | Y |
| age_adjusted | aggressive | month | glicko2 | 0.01750 | 0.00747 | 0.01174 | 0.01316 | Y |
| age_adjusted | conservative | month | glicko2 | 0.01750 | 0.00747 | 0.01174 | 0.01316 | Y |
| age_adjusted | place_only | meet | glicko2 | 0.01391 | 0.00693 | 0.01092 | 0.01272 | Y |
| age_adjusted | place_only | meet | trueskill | 0.01668 | 0.00697 | 0.01064 | 0.01251 | Y |
| age_adjusted | place_only | month | glicko2 | 0.01370 | 0.00698 | 0.01107 | 0.01296 | Y |
| age_adjusted | place_only | month | trueskill | 0.01630 | 0.00703 | 0.01067 | 0.01192 | Y |

## 예측 확률 분포와 불확실성

확률이 극단으로 몰리면(판별력은 있는데 스케일이 깨진 상태) 여기서 먼저 드러납니다.
tau는 홀드아웃 이전 구간에서 log loss로 골랐습니다.

| config | policy | period | engine | tau | p 표준편차 | p<0.1 또는 >0.9 | 불확실성 p50 | 불확실성 p10 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| age_adjusted | aggressive | meet | trueskill | 0.5000 | 0.2335 | 8.5% | 2.097 | 1.855 |
| age_adjusted | conservative | meet | trueskill | 0.5000 | 0.2335 | 8.5% | 2.097 | 1.855 |
| age_adjusted | aggressive | month | trueskill | 1.0000 | 0.2366 | 8.9% | 3.155 | 2.712 |
| age_adjusted | conservative | month | trueskill | 1.0000 | 0.2366 | 8.9% | 3.155 | 2.712 |
| age_adjusted | aggressive | meet | glicko2 | 0.2000 | 0.2129 | 3.6% | 67.456 | 42.666 |
| age_adjusted | conservative | meet | glicko2 | 0.2000 | 0.2129 | 3.6% | 67.456 | 42.666 |
| age_adjusted | aggressive | month | glicko2 | 1.2000 | 0.2066 | 2.8% | 67.830 | 41.704 |
| age_adjusted | conservative | month | glicko2 | 1.2000 | 0.2066 | 2.8% | 67.830 | 41.704 |
| age_adjusted | place_only | meet | glicko2 | 0.2000 | 0.1498 | 0.4% | 140.873 | 64.240 |
| age_adjusted | place_only | meet | trueskill | 0.2500 | 0.1515 | 0.7% | 2.098 | 1.527 |
| age_adjusted | place_only | month | glicko2 | 0.2000 | 0.1463 | 0.3% | 141.094 | 63.277 |
| age_adjusted | place_only | month | trueskill | 0.2500 | 0.1488 | 0.6% | 2.097 | 1.524 |

## 캘리브레이션 플롯

- `age_adjusted/aggressive/meet/glicko2`: ![](backtest_calibration/aggressive-meet-glicko2.svg)
- `age_adjusted/aggressive/meet/trueskill`: ![](backtest_calibration/aggressive-meet-trueskill.svg)
- `age_adjusted/aggressive/month/glicko2`: ![](backtest_calibration/aggressive-month-glicko2.svg)
- `age_adjusted/aggressive/month/trueskill`: ![](backtest_calibration/aggressive-month-trueskill.svg)
- `age_adjusted/conservative/meet/glicko2`: ![](backtest_calibration/conservative-meet-glicko2.svg)
- `age_adjusted/conservative/meet/trueskill`: ![](backtest_calibration/conservative-meet-trueskill.svg)
- `age_adjusted/conservative/month/glicko2`: ![](backtest_calibration/conservative-month-glicko2.svg)
- `age_adjusted/conservative/month/trueskill`: ![](backtest_calibration/conservative-month-trueskill.svg)
- `age_adjusted/place_only/meet/glicko2`: ![](backtest_calibration/place_only-meet-glicko2.svg)
- `age_adjusted/place_only/meet/trueskill`: ![](backtest_calibration/place_only-meet-trueskill.svg)
- `age_adjusted/place_only/month/glicko2`: ![](backtest_calibration/place_only-month-glicko2.svg)
- `age_adjusted/place_only/month/trueskill`: ![](backtest_calibration/place_only-month-trueskill.svg)

## 세그먼트 분해 (best config)

### n_games

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| 21+ | 12,901 | 0.56167 | 0.7113 | 0.18996 |
| 6-20 | 3,860 | 0.46716 | 0.7811 | 0.15285 |
| 0-5 | 2,290 | 0.68026 | 0.5734 | 0.24409 |

### age

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| <=12 | 7,942 | 0.55963 | 0.7033 | 0.19091 |
| 16+ | 7,681 | 0.55955 | 0.7055 | 0.18992 |
| 13-15 | 3,428 | 0.54393 | 0.7290 | 0.18223 |

### sigma

sigma는 레이팅의 불확실성입니다. 값이 클수록 그 선수의 실력을 아직 덜 안다는 뜻이고, 쌍에서는 두 선수 중 큰 쪽을 씁니다. sigma-오차 역전의 원인 분석은 `docs/adr/0007-sigma-inversion.md`에 있습니다.

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| high(> 2.2) | 6,473 | 0.53846 | 0.7153 | 0.18237 |
| low(<= 2.0) | 6,292 | 0.59727 | 0.6834 | 0.20525 |
| mid(2.0~2.2) | 6,286 | 0.53510 | 0.7276 | 0.17940 |

### round

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| semifinal | 6,029 | 0.55743 | 0.7101 | 0.18900 |
| quarterfinal | 5,580 | 0.52988 | 0.7301 | 0.17825 |
| final | 3,526 | 0.61197 | 0.6724 | 0.21087 |
| heat | 2,997 | 0.51185 | 0.7404 | 0.17109 |
| final_b | 919 | 0.65054 | 0.6083 | 0.22764 |

### grade

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| (unknown-grade) | 12,127 | 0.55319 | 0.7147 | 0.18704 |
| 5,6 | 4,224 | 0.53993 | 0.7190 | 0.18257 |
| 3,4 | 2,465 | 0.59255 | 0.6738 | 0.20449 |
| 1,2 | 235 | 0.66935 | 0.5915 | 0.23895 |

### event

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| 여자초등5,6학년-1500m | 868 | 0.52020 | 0.7350 | 0.17487 |
| 남자초등5,6학년-1500m | 808 | 0.52770 | 0.7314 | 0.17729 |
| 남자중학부-1500m | 757 | 0.59533 | 0.6803 | 0.20347 |
| 여자초등5,6학년-500m | 644 | 0.52060 | 0.7283 | 0.17570 |
| 남자초등5,6학년-500m | 597 | 0.54720 | 0.7119 | 0.18495 |
| 남자부-1500m | 584 | 0.65626 | 0.6250 | 0.23139 |
| 여자중학부-1500m | 579 | 0.47631 | 0.7876 | 0.15588 |
| 남자고등부-1500m | 572 | 0.53214 | 0.7465 | 0.17717 |
| 여자초등5,6학년-1000m | 552 | 0.56575 | 0.6848 | 0.19381 |
| 남자부-1000m | 536 | 0.57288 | 0.6828 | 0.19605 |
| 여자고등부-1500m | 524 | 0.50286 | 0.7290 | 0.16902 |
| 남자초등5,6학년-1000m | 516 | 0.57619 | 0.7016 | 0.19605 |

### source_status

| bucket | n | log_loss | accuracy | brier |
| --- | ---: | ---: | ---: | ---: |
| FIN-FIN | 19,051 | 0.55677 | 0.7088 | 0.18894 |


## GO/STOP 판정

- best_config: `age_adjusted/aggressive/meet/trueskill`
- best_log_loss: **0.55677**
- B3_log_loss: **0.63306**
- improvement_vs_B3: **12.05%**
- holdout 비율: **19,051 / 172,028** (11.1%)
- verdict: **GO**

| 조건 | 관측값 | 통과 |
| --- | ---: | --- |
| 개선율 >= 5% | 12.05% | Y |
| ECE <= 0.03 | 0.01735 | Y |
| 70% 과신 없음 | N | Y |
