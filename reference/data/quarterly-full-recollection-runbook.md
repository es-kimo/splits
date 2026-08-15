# 분기 전수 재수집 운영 런북

주간 자동 갱신은 신규 대회 증분만 처리합니다. 원천 시스템의 과거 데이터 보정/지연 반영을 흡수하기 위해 분기 1회 전수 재수집을 수행합니다.

## 1) 실행 원칙

- 권장 실행 위치: 로컬(공유 데이터 디렉터리)
- 권장 시기: 1·4·7·10월 첫 주
- 요청 간격: 1초 이상 유지, 병렬 요청 금지
- 개인 데이터(`records_full.csv`, `athlete_info_full.csv`, `raw/**`)는 커밋 금지

## 2) 권장 실행 절차

```bash
python3 collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data --request-gap 1.0 --fail-on-unknown-failures collect
python3 collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data --request-gap 1.0 --fail-on-unknown-failures retry-failures
python3 collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data --request-gap 1.0 --fail-on-unknown-failures export
python3 analyze.py
python3 build_data.py
python3 build_site.py
```

## 3) 실패 유형 처리 기준

- known warning(워크플로 실패로 승격하지 않음)
  - `inf301_result_call_parse` (원천 미노출, INF503 보완 경로 존재)
  - `inf310_zero_participant` (계주 구간 빈 참가자 행)
- unknown failure
  - 위 known warning 외 실패 단계는 전부 unknown으로 간주하고 즉시 조사/재실행

## 4) 커밋 전 확인

```bash
python3 scripts/check_data_commit_policy.py --mode tracked
```

- 허용 파일만 변경되었는지 확인합니다.
- `data/meet_index_inf201.csv` 갱신 포함 여부를 확인합니다.
