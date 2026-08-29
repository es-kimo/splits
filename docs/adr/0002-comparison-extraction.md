# ADR 0002 — 라운드·실격 정책 기반 비교 추출 (R-02)

- 상태: Accepted
- 작성시각: 2026-08-29T12:35:00
- 입력: `records_full.csv` (공유 데이터 경로 기준 실행)

## 문맥

- R-01은 연결성 판정까지 완료했지만, R-05 백테스트가 비교할 수 있는 정책별 pairwise 추출 엔진은 아직 없었습니다.
- 쇼트트랙은 실격(PEN)·비완주(DNF/DNS)가 잦아 단일 고정 규칙으로 손실이 커질 수 있으므로, 정책 후보를 런타임 프리셋으로 분리해 실험 가능하게 만들어야 했습니다.
- `records_anon.csv`는 `사유`가 공백이어서 status 정책 검증이 불가능하므로, R-02 기본 입력을 `records_full.csv`로 확정했습니다.

## 결정

1. `rating/ledger/extract.py`에 `extract_comparisons(results: pl.DataFrame, policy: ExtractionPolicy)`를 구현합니다.
2. `rating/ledger/policies.py`에 `CONSERVATIVE`, `AGGRESSIVE`, `PLACE_ONLY` 프리셋을 둡니다.
3. 절대 규칙은 고정합니다.
   - 같은 `race_id` 내부에서만 비교 생성
   - 동점 `place` 비교 미생성
   - 릴레이/계주 제외
   - 채점종합 제외
4. 입력 단계 기본 필터를 고정합니다.
   - 시즌 컷오프: **2013+**
   - 동호인부: **항상 제외**
   - 스피드스케이팅 오염: 행 단위 규칙으로 제외
5. status 정규화는 `FIN/PEN/DNF/DNS/ADV`만 허용하고, **미분류 코드는 즉시 예외** 처리합니다.
   - `ADV`는 `DNF`에 합치지 않고 독립 처리합니다.

## 프리셋 정의

| preset | PEN | DNF | ADV | include_rounds |
| --- | --- | --- | --- | --- |
| conservative | exclude | exclude | exclude | heat, quarterfinal, semifinal, final, final_b |
| aggressive | last_place | loss_to_finishers | keep | heat, quarterfinal, semifinal, final, final_b, other |
| place_only | last_place | exclude | keep | final, final_b |

## status 감사 관측 (구조 필터 후)

- 전체 행수: **93,952**
- 원천 status 코드 수: **60**
- 정규화 집계: `FIN 87,945`, `PEN 3,372`, `DNF 2,265`, `DNS 370`, `ADV 0`
- 상세 표는 `out/status_audit.md`에 기록했습니다.

## 정책별 비교 수

| preset | 비교 행수 | race 수 | 주요 source_status |
| --- | ---: | ---: | --- |
| conservative | 1,051,387 | 5,268 | FIN-FIN |
| aggressive | 1,224,015 | 5,269 | FIN-FIN, FIN-PEN, FIN-DNF, PEN-PEN |
| place_only | 420,617 | 708 | FIN-FIN, FIN-PEN, PEN-PEN |

## 결과

- R-05는 세 프리셋을 동일 입력에서 직접 비교할 수 있게 되었고, 실격/비완주 처리의 정보 손실-노이즈 트레이드오프를 백테스트로 선택할 수 있습니다.
