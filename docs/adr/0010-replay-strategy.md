# ADR 0010 — 리플레이 전략과 시즌 체크포인트 (R-08)

- 상태: Accepted
- 작성시각: 2026-09-07
- 선행: `docs/adr/0003-ledger-ordering.md`, `docs/adr/0006-backtest-verdict-rerun.md`, `docs/adr/0009-age-model.md`
- 연계 이슈: R-09, R-11, R-12

## 문맥

레이팅 파라미터나 입력 레저가 달라지면 과거 경기부터 순차 재생해야 합니다. 다만 전체 리플레이가 충분히 빠르다면 복잡한 증분 인프라보다, 재현 가능한 시즌 경계 체크포인트가 더 안전합니다.

## 측정

2026-09-07에 전체 레저(18,847경기, 176개 기간)를 `trueskill/meet` 기본 설정으로 측정했습니다. 상세 프로파일은 `out/replay_bench.md`에 남깁니다.

| 항목 | 관측값 | 기준 | 판정 |
| --- | ---: | ---: | --- |
| 전체 리플레이(콜드) | 10.308초 | < 60초 | 충족 |
| 마지막 시즌 체크포인트 재개 | 2.665초 | < 5초 | 충족 |
| 최대 메모리 | 172.99 MiB | 관측 | 기록 |
| 시즌별 처리 시간 | 0.044~0.719초 | 시즌당 5초 초과 시 월 단위 검토 | 유지 |

프로파일에서 시간의 대부분은 TrueSkill의 다자간 순위 갱신에 사용됐고, 그 다음은 레저 검증입니다. 현 성능은 목표를 충족하므로 벡터화, numba, Rust 코어 최적화는 도입하지 않습니다. 목표를 다시 넘으면 race 단위 배치 또는 numba를 먼저 검토합니다.

## 결정

1. `rating.replay.orchestrator.replay()`가 입력 레저의 결정적 순서로 원시 상태를 재생합니다.
2. 시즌은 7월 시작~다음 해 6월 종료이며, 완결된 각 시즌의 마지막 처리일에 전체 선수 상태를 저장합니다.
3. 체크포인트 키는 `hash(algorithm_version, params_hash, input_hash, cutoff_date)`입니다. 알고리즘, 명시적 TrueSkill EP 반복 상한·수렴 허용오차를 포함한 파라미터, 입력 Parquet 스냅샷, 또는 기준일이 바뀌면 자동으로 다른 키가 됩니다.
4. 상태는 Parquet `float64`로 저장하고 `mu`, 불확실성, 엔진 sigma, `last_active`, `n_games`를 모두 보존합니다. 메타데이터와 상태 해시가 맞지 않으면 로드를 거부합니다.
5. 현 상태 크기는 작으므로 유효한 시즌 체크포인트를 모두 보관합니다. 경로는 `out/replay_checkpoints/`이며 Git에 포함하지 않습니다.
6. 체크포인트에는 원시 상태만 저장합니다. Platt 보정기는 실행 산출물로 별도 적합·저장하며, 체크포인트와 섞지 않습니다.

`trueskill` 라이브러리가 공개하는 EP 제어값인 `min_delta`를 `convergence_tolerance`으로, 라이브러리 기본값으로 고정돼 있던 최대 EP 순회를 `ep_max_iterations`로 명시 전달합니다. 선수는 `(rank, athlete_id)`로 정렬한 뒤 갱신하므로 입력 행 순서에 따라 결과가 달라지지 않습니다.

## 재현

```bash
# 현재 레저를 기준으로 콜드/재개 시간, 메모리, 프로파일을 측정합니다.
make rating-replay-bench

# 체크포인트를 저장하거나 호환되는 최근 체크포인트부터 재생합니다.
python -m rating.replay.orchestrator --ledger out/ledger
```
