# 익명 데이터 커밋 정책

본 문서는 저장소에 커밋 가능한 데이터 범위와 익명화 기준을 정의합니다.

## 1. 목적

- 통계 재집계를 재현 가능하게 유지합니다.
- 개인 식별 정보의 저장소 유입을 차단합니다.

## 2. 커밋 허용 범위

- `data/records_anon.csv`
- `data/stats_distribution.csv`
- `data/stats_participation.csv`
- `data/season_month_histogram.csv`
- `data/participation.csv`
- `data/season_activity_counts.csv`
- `data/class_transition_summary.csv`
- `data/gap_return_rates.csv`
- `data/record_stop_rule.csv`
- `data/cohort.csv`
- `data/cohort_stage_summary.csv`
- `data/retention_overall.csv`
- `data/retention_band.csv`
- `data/improvement_rate.csv`
- `data/public_figures.csv`
- `data/coverage.csv`
- `data/meet_index_inf201.csv`
- `data/class_level_map.csv`
- `data/class_level_year_category_counts.csv`
- `data/class_level_ab_agreement_summary.csv`
- `data/class_level_ab_mismatch_types.csv`
- `data/class_level_year_readiness.csv`
- `site/**`

## 3. 커밋 금지 범위

- `data/raw/**`
- `data/records.csv`, `data/records_full.csv`
- `data/athlete_info.csv`, `data/athlete_info_full.csv`
- `data/athlete_index.csv`
- `data/id_merge_candidates.csv`, `data/id_merges.csv`
- `.env`, `.env.*`

## 4. 익명화 규칙

- 익명키 생성식: `sha256(idNo + SALT)[:12]`
- SALT는 환경변수 `SPLITS_ANON_SALT`로 주입합니다.
- SALT는 저장소/워크플로 로그에 남기지 않습니다.
- SALT는 운영자가 별도 백업 매체로 보관합니다.

## 5. records_anon 스키마

헤더:

`toCd, classCd, 대회명, 대회연도, 일자, 종별, 학령구간, 거리, SF여부, 라운드, 라운드종류, 순위, 기록_초, 사유, 성별, 출생연도, 학년, 익명키`

금지 컬럼:

`이름, idNo, 소속, 시도, BIB, 레인`

`toCd`는 별도 대회 인덱스(`meet_index_inf201.csv`)가 있을 때만 채웁니다. 인덱스가 없거나 매칭이 불명확한 경우에는 공백을 허용합니다.

## 5-1. participation 스키마

헤더:

`익명키, 시즌, 출생연도, 성별, 학년, 단계, 종별_단계, 대회수, 경기수, classCd목록, 오픈참가`

규칙:

- `익명키`: 12자리 hex
- `오픈참가`: `Y` 또는 `N`

## 5-2. cohort 스키마

헤더:

`익명키, 성별, 출생연도, 첫대회연도, 첫시즌, 첫학년, 마지막시즌, 기록중단기준n, 좌측절단, 도달_중등, 도달_고등, 도달_대학, 관측충분_중등, 관측충분_고등, 관측충분_대학, 분석대상_중등, 분석대상_고등, 분석대상_대학`

규칙:

- `익명키`: 12자리 hex
- `좌측절단` 및 `*_중등/*_고등/*_대학` 플래그 컬럼: `Y` 또는 `N`

## 6. 강제 장치

- 로컬 `pre-commit` 훅: 스테이징 파일 정책 검증
- GitHub Actions: 추적 파일 전체 정책 검증
- 검증 스크립트: `scripts/check_data_commit_policy.py`
