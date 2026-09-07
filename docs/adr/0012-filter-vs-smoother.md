# ADR 0012 — 필터와 회고 스무딩 레이팅 분리 (R-10)

- 상태: Accepted
- 작성일: 2026-09-07
- 선행: `docs/adr/0011-run-registry.md`

## 문맥

레이팅에는 서로 다른 두 질문이 있습니다.

1. 특정 시점까지 알 수 있었던 선수의 실력은 예측과 백테스트에 쓰는 필터
   추정치입니다.
2. 현재의 전체 기록을 기준으로 과거 시점의 실력을 되돌아보는 값은 궤적 분석에
   쓰는 회고 스무딩 추정치입니다.

두 번째 값에는 미래 경기 정보가 들어 있으므로 첫 번째 용도로 사용하면 조용한
데이터 누수가 됩니다.

## 결정

1. 실행 레지스트리는 기존 `rating_snapshot`에 필터 상태를, 별도
   `rating_smoothed_snapshot`에 회고 상태를 같은 `run_id`로 저장합니다. 두
   테이블은 실행 완료 전에는 공개되지 않습니다.
2. `rating_as_of()`는 요청 기준일 이하의 가장 최근 필터 스냅샷만 색인 조회해
   `FilteredRating`을 반환합니다. 조회 중 리플레이하지 않습니다.
3. `rating_retrospective()`는 별도 스무딩 테이블만 조회해 `SmoothedRating`을
   반환합니다.
4. 스무딩은 레저의 날짜 축을 첫·마지막 경기일을 기준으로 반사한 뒤, 최신
   경기부터 같은 TrueSkill 갱신을 재생해 만듭니다. 순위와 승패는 바꾸지
   않습니다. 반사된 날짜가 증가하므로 비활동 기간의 `tau`도 원래 방향과 같은
   방식으로 적용됩니다.
5. 같은 선수·기간의 순방향과 역방향 상태는 가우시안 정밀도 가중으로 결합합니다.

   ```text
   mu_s = (mu_f / sigma_f^2 + mu_b / sigma_b^2)
          / (1 / sigma_f^2 + 1 / sigma_b^2)
   sigma_s = sqrt(1 / (1 / sigma_f^2 + 1 / sigma_b^2))
   ```

6. 백테스트 진단 경계는 `FilteredRating`만 받습니다. `SmoothedRating`은
   별도 명목 타입이므로 mypy가 전달을 거부합니다.
7. 스무딩은 `mu`, `sigma` 레이팅 층에서만 동작합니다. 확률 보정기는 별도
   산출물이며, 필터용 보정기를 스무딩 레이팅 확률에 재사용하지 않습니다.

## 결과

- 예측/백테스트와 회고 궤적 분석이 서로 다른 타입과 조회 경로를 사용합니다.
- 기간별 인덱스 조회는 리플레이 비용 없이 완료된 상태만 읽습니다.
- 국가대표 비교 보고서는 필터와 스무딩 차이가 큰 사례와 불확실성 변화를
  기록하지만, 스무딩 값을 실시간 예측이나 사용자용 확률로 노출하지 않습니다.

## 사용

```bash
python -m rating.replay.orchestrator --params configs/base.toml --register
python -m rating.query.temporal --compare-filter-smoother --athletes national_team --out out/smoothing_report.md
```
