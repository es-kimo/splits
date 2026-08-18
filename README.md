# splits

대한체육회 경기결과 데이터를 수집·정제해 쇼트트랙 선수 이력을 공개하는 프로젝트입니다.  
핵심은 **명령어별 산출물(CSV/JSON)과 다음 단계 의존 관계**를 명확히 유지하는 것입니다.

- 배포 URL: https://splits.kr/
- 공개 대상 명단(수동 관리): `data/public_figures.csv`
- Python 파이프라인은 데이터 생성, Astro(`web/`)는 사이트 렌더링 담당

## 1) 위상정렬(선수 단계) 파이프라인

```mermaid
flowchart TD
  A[scrape.py resolve] --> B[data/resolved.csv]
  B --> C[scrape.py history]
  C --> D[data/records.csv + data/athlete_info.csv]
  D --> E[analyze.py]
  E --> F[data/placements.csv 등 분석 CSV]
  F --> G[build_data.py]
  G --> H[site/data/*.json]
  H --> I[build_site.py]
  I --> J[index.html, analysis/, athlete/, meet/, distribution/, privacy/, sitemap.xml, robots.txt]

  K[scrape.py enumerate] --> L[data/athlete_index.csv]
  M[collect_full_history.py collect/retry-failures/export] --> O[data/records_full.csv + data/athlete_info_full.csv]
  M --> P[data/raw/inf201|inf301_kind|detail_class_ajax|inf301|inf310|inf503]
  M --> Q[data/collect_progress.json + data/collect_failures.csv + data/detail_failures.csv + data/collect_request_failures.csv]
  L -. 소속 집계 보조 입력 .-> E
  E --> N[data/id_merges.csv]
  N -. 재실행 시 기존 병합표로 되먹임 .-> E
  O -. 익명 통계 입력 우선 .-> E
  O -. 대회 집계 1순위 .-> G
  D -. 대회 집계 2순위 폴백 .-> G
```

full 입력은 별도 종점이 아니라 `analyze.py`/`build_data.py`로 되돌아오는 되먹임 간선입니다.
`build_data.py`는 분석 CSV만으로는 동작하지 않고, `records_full`/`records` 중 한 쌍을 **반드시** 직접 읽습니다(둘 다 없으면 `FileNotFoundError`).

## 2) 빠른 실행(공개 사이트 빌드)

```bash
pip install -r requirements.txt
npm install --prefix web   # 최초 1회
python scrape.py resolve
python scrape.py history
python analyze.py
cat > .env.local <<'EOF'
SPLITS_ANON_SALT=<충분히 긴 랜덤 문자열>
SPLITS_MEET_INDEX_CSV=/Users/kihyun/orgs/personal/splits/data/meet_index_inf201.csv
EOF
python build_data.py
python build_site.py
```

## 3) 커맨드별 입력/산출물/의존성

| 커맨드                                             | 선행 입력(주요)                                                                                                                                                                | 생성/갱신 산출물                                                                                                                                                                                                                                                                                                                                    | 다음 단계에서 사용                                          |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `python scrape.py resolve`                         | `athletes.py` 내 대상 명단                                                                                                                                                     | `data/candidates.csv`, `data/resolved.csv`                                                                                                                                                                                                                                                                                                          | `scrape.py history`                                         |
| `python scrape.py history`                         | `data/resolved.csv`                                                                                                                                                            | `data/records.csv`, `data/athlete_info.csv`, `data/raw/history_*.html`                                                                                                                                                                                                                                                                              | `analyze.py`                                                |
| `python scrape.py enumerate`                       | INF703 검색 결과                                                                                                                                                               | `data/athlete_index.csv`, `data/no_id_rows.csv`, `data/raw/search_*.html`                                                                                                                                                                                                                                                                           | `collect_full_history.py`                                   |
| `python analyze.py`                                | `data/records.csv`, `data/athlete_info.csv` (필수) / `data/athlete_index.csv`(선택, `SPLITS_ATHLETE_INDEX_CSV`로 경로 지정 가능), `data/id_merges.csv`(선택, 기존 병합표 재사용), `data/records_full.csv` + `data/athlete_info_full.csv`(선택, 익명 통계에만 우선 사용)                                                             | `data/clean_records.csv`, `data/placements.csv`, `data/youth_summary.csv`, `data/outliers.csv`, `data/coverage.csv`, `data/age_matrix.csv`, `data/best_heat_times.csv`, `data/school_raw_list.txt`, `data/school_aliases.csv`, `data/school_ambiguous.csv`, `data/id_merge_candidates.csv`, `data/id_merges.csv`, `data/stats_distribution.csv`, `data/stats_participation.csv`, `data/season_month_histogram.csv`, `data/participation.csv`, `data/season_activity_counts.csv`, `data/class_transition_summary.csv`, `data/gap_return_rates.csv`, `data/record_stop_rule.csv`, `data/cohort.csv`, `data/cohort_stage_summary.csv` | `build_data.py`, `collect_full_history.py(간접: id_merges)` |
| `python scripts/audit_id_key_reliability.py`       | `data/records_full.csv` + `data/athlete_info_full.csv` 우선(없으면 `data/records.csv` + `data/athlete_info.csv`) / `SPLITS_ANON_SALT`(선택, 없으면 대체 salt로 동등성 검사)                                                                                                                                                    | `data/merge_audit_summary.md`(숫자/유형 요약), `data/merge_audit_sample_private.csv`, `data/merge_audit_signals_private.csv`                                                                                                                                                                                                                        | 이슈 #77 완료 기준(쪼개짐/합쳐짐 리스크, 매칭 가능성) 판정    |
| `python collect_full_history.py collect`           | 네트워크 원천(INF201→INF301(kind옵션)→detailClass AJAX→INF301→INF310), 기존 캐시/진행상태(`data/raw/**`, `data/collect_progress.json`)                                       | `data/raw/inf201/{page}.html`, `data/raw/inf301_kind/{classCd}_{toCd}.html`, `data/raw/detail_class_ajax/{classCd}_{toCd}_{kindCd}.json`, `data/raw/inf301/{classCd}_{toCd}_{kindCd}_{detailClassCd}.html`, `data/raw/inf310/{classCd}_{toCd}_{kindCd}_{detailClassCd}_{baseClassCd}_{rhCd}_{pcntGbn}.html`, `data/raw/inf503/{idNo}.html`, `data/collect_progress.json`, `data/collect_failures.csv`, `data/detail_failures.csv`, `data/collect_request_failures.csv`, `data/suspicious_ids.csv`, `data/records_full.csv`, `data/athlete_info_full.csv` | `analyze.py` 익명 통계 입력 우선, `build_data.py` 대회 집계 입력 우선 |
| `python collect_full_history.py retry-failures`    | `data/collect_failures.csv`(부분완료/실패 대회 목록)                                                                                                                            | 위 `collect`와 동일 파일 갱신                                                                                                                                                                                                                                                                                                                       | 동일                                                        |
| `python collect_full_history.py export`            | `data/raw/inf201|inf301_kind|detail_class_ajax|inf301|inf310|inf503` 캐시                                                                                                      | `data/records_full.csv`, `data/athlete_info_full.csv`, `data/suspicious_ids.csv`, `data/detail_failures.csv` 재생성                                                                                                                                                                                                                                | 동일                                                        |
| `python collect_full_history.py weekly-incremental` | `data/meet_index_inf201.csv`(신규 대회 판별 기준, 없으면 `records_anon.csv` 기반 시드 생성), INF201 1페이지 응답, 환경변수 `SPLITS_ANON_SALT`                                 | 신규 대회 캐시(`data/raw/**` 일부), `data/records_full.csv`, `data/athlete_info_full.csv`, `data/weekly_incremental_summary.json`, `data/records_anon.csv` append, `data/meet_index_inf201.csv` 갱신                                                                                                                                            | `analyze.py`(익명 통계 재집계), `build_site.py`            |
| `python collect_full_history.py compare-resolved`  | `data/resolved.csv`, `data/records.csv`, `data/athlete_info.csv`, `data/records_full.csv`, `data/athlete_info_full.csv`                                                        | CSV 생성 없음(회귀 비교 로그)                                                                                                                                                                                                                                                                                                                       | 품질 점검                                                   |
| `python collect_full_history.py cleanup-raw-cache` | `data/raw/**/*.html`                                                                                                                                                           | raw cache 삭제                                                                                                                                                                                                                                                                                                                                      | 저장 공간 정리                                              |
| `python build_data.py`                             | `data/placements.csv`, `data/youth_summary.csv`, `data/age_matrix.csv`, `data/athlete_info.csv`, `data/coverage.csv`, `data/public_figures.csv`, `data/stats_distribution.csv` + **대회 집계용 원천 1쌍 필수**: `records_full.csv`+`athlete_info_full.csv`(1순위) 또는 `records.csv`+`athlete_info.csv`(2순위), 환경변수 `SPLITS_ANON_SALT` (선택: `SPLITS_MEET_INDEX_CSV`) | `data/records_anon.csv`, `site/data/athletes.json`, `site/data/meets.json`, `site/data/distribution.json`, `site/data/meta.json`                                                                                                                                                                                                                     | `build_site.py`                                             |
| `python build_site.py`                             | `site/data/*.json`, `web/`                                                                                                                                                     | 루트 정적 결과물(`index.html`, `analysis/`, `athlete/`, `meet/`, `distribution/`, `privacy/`, `sitemap.xml`, `robots.txt`, `support.js`)                                                                                                                                                                                                             | 배포                                                        |
| `python event_participants.py collect ...`         | 특정 대회 classCd/toCd 또는 event-index                                                                                                                                        | `data/event_{classCd}_{toCd}_participants.csv`, `data/event_{classCd}_{toCd}_participant_occurrences.csv`(종별/종별구분/pcntGbn 포함), `data/event_{classCd}_{toCd}_detail_metrics.csv`                                                                                                                                                         | 대회 단위 점검/분석 보조                                    |
| `python event_participants.py validate-route ...`  | `data/athlete_index.csv`(필수), `data/public_figures.csv`(공인선수 대조), `records_full.csv` 또는 `records.csv`(권장: `--compare-data-dir /Users/kihyun/orgs/personal/splits/data`) | `data/route_validation/<run_id>/A_detail_comparison.csv`, `B_set_comparison.csv`, `C_diff_classification.csv`, `D_public_figures_check.csv`, `summary.json`(INF310 구분행/참가자 미추출 원인 분리 지표 포함), `event_*/` 하위 상세 CSV, `reference/data/issue-47-route-validation.md`                                                    | 이슈 #47 통일 가능 여부 판정                                 |

## 4) 전체 선수 기록 수집(비공개 원천 데이터) 운영

기본 공유 경로를 재사용할 때는 `--data-dir`로 외부 데이터 디렉터리를 지정합니다.

```bash
python collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data collect
python collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data retry-failures
python collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data weekly-incremental --fail-on-unknown-failures
python collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data compare-resolved
python collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data cleanup-raw-cache
```

- `collect`: 미수집 대상 이어받기 수집 + full CSV 생성
- `retry-failures`: 부분완료/실패 대회 캐시 무효화 후 재요청 + full CSV 재생성
- `weekly-incremental`: INF201 1페이지 기준 신규 대회만 수집 + records_anon 증분 append
- `export`: 네트워크 요청 없이 캐시만으로 full CSV 재생성
- `compare-resolved`: 기존 resolved 기준 old/new 회귀 비교
- `cleanup-raw-cache`: 집계 후 raw HTML 캐시만 삭제
- `--data-dir` 미지정 시 `./data`(또는 `SPLITS_DATA_DIR`) 사용
- 네트워크 요청 간격은 기본 1초(`--request-gap`), 캐시 히트 시 sleep 생략
- `collect`는 classCd=2(쇼트트랙) 대회를 `INF201` 응답 기준으로 전수 시도하고, 대회 경로에서 발견된 전체 선수 id를 `INF503`로 보완 조회해 `채점종합`·출생년도·목록 외 대회 이력을 보강합니다.
- 분기 전수 재수집 런북은 `reference/data/quarterly-full-recollection-runbook.md`를 따릅니다.
- GitHub Actions 주간 자동화는 `.github/workflows/data-weekly-refresh.yml`(UTC 월 19시 = KST 화 04시)에서 관리합니다.

## 5) 파일 의미(핵심)

| 파일                                                   | 의미                                                           |
| ------------------------------------------------------ | -------------------------------------------------------------- |
| `data/public_figures.csv`                              | 공개 대상 선수 목록(수동 관리, `상태=removed`는 빌드에서 제외) |
| `data/records_anon.csv`                               | 커밋 가능한 익명 원천 레코드(`sha256(idNo + SALT)[:12]`)     |
| `data/athlete_index.csv`                               | 전체 선수 수집용 id 인덱스                                     |
| `data/resolved.csv`                                    | 기준 선수 id 확정 결과                                         |
| `data/records.csv` / `data/athlete_info.csv`           | 기본 분석 입력(공개 사이트 핵심 입력)                          |
| `data/records_full.csv` / `data/athlete_info_full.csv` | 전체 수집 확장 입력(익명 통계 + 대회 집계 강화용, `source=event|inf503` 포함) |
| `data/collect_failures.csv`                             | 대회 상태 요약 중 부분완료/실패 목록(재시도 입력)              |
| `data/detail_failures.csv`                              | 세부종목 단위 실패 로그(`classCd,toCd,kindCd,detailClassCd`)   |
| `data/collect_request_failures.csv`                     | 요청 단위 실패 로그(HTTP/네트워크 진단)                        |
| `data/meet_index_inf201.csv`                            | 주간 증분 신규 대회 판별용 INF201 인덱스                       |
| `data/suspicious_ids.csv`                               | 규격 외 idNo(자리수/형식 이상) 감지 로그                        |
| `data/id_merges.csv`                                   | 동일 선수 id 병합 확정표(부idNo→주idNo)                        |
| `data/placements.csv`                                  | 선수·대회·거리 단위 대표 성적(라운드 해석 적용 결과)           |
| `data/stats_distribution.csv`                          | 익명 분포 통계(`출생연도×성별×거리`, k-익명성 기준 적용)       |
| `data/stats_participation.csv`                         | 익명 참가 통계                                                 |
| `data/season_month_histogram.csv`                      | 월별 대회 수 히스토그램(시즌 경계 근거)                        |
| `data/participation.csv`                               | 선수×시즌 참가 이력(익명키 기준)                              |
| `data/season_activity_counts.csv`                      | 시즌별 활동 선수 수                                             |
| `data/class_transition_summary.csv`                    | 시즌별 종목 전환 유형 요약(기록 중단 분리 포함)                |
| `data/gap_return_rates.csv`                            | 공백 시즌 길이별 복귀율(전체/학년 전환 구간)                   |
| `data/record_stop_rule.csv`                            | `n시즌 연속 미출전 = 기록 중단` 기준 확정 결과와 근거 문장      |
| `data/cohort.csv`                                      | 선수별 분석 대상 플래그(좌측절단/중등·고등·대학 분석 대상)      |
| `data/cohort_stage_summary.csv`                        | 단계별 대상 선수 수(N), 성별 분포, 표본 신뢰 한계 요약          |
| `site/data/*.json`                                     | Astro 빌드 계약 데이터                                         |
| `index.html`, `athlete/`, `meet/` 등                   | 최종 배포 정적 산출물                                          |

## 6) 운영 원칙

- `data/` 커밋 허용 파일은 `records_anon.csv`, `stats_distribution.csv`, `stats_participation.csv`, `season_month_histogram.csv`, `participation.csv`, `season_activity_counts.csv`, `class_transition_summary.csv`, `gap_return_rates.csv`, `record_stop_rule.csv`, `cohort.csv`, `cohort_stage_summary.csv`, `public_figures.csv`, `coverage.csv`, `meet_index_inf201.csv`(및 `data/README.md`)로 제한합니다.
- 개인식별/원천 데이터(`records`, `records_full`, `athlete_info`, `athlete_info_full`, `athlete_index`, `id_merge_candidates`, `id_merges`, `raw/**`)는 Git에 커밋하지 않습니다.
- SALT는 환경변수 `SPLITS_ANON_SALT`로만 주입하며 `.env*` 파일은 커밋하지 않습니다. `build_data.py`와 `collect_full_history.py`는 실행 시 `.env.local`/`.env`를 자동 로드합니다(이미 쉘에 설정된 값이 우선).
- `python analyze.py`는 익명 통계 생성 시 `records_full/athlete_info_full`이 있으면 우선 사용하고, 없으면 `records/athlete_info`를 사용합니다. 선수 단계 산출물(`placements.csv` 등)은 항상 `records/athlete_info` 기준입니다.
- `python analyze.py`는 `records.csv`/`athlete_info.csv`가 없고 `records_anon.csv`만 있는 경우에도 `coverage.csv`, `stats_distribution.csv`, `stats_participation.csv`, `season_month_histogram.csv`, `participation.csv`, `season_activity_counts.csv`, `class_transition_summary.csv`, `gap_return_rates.csv`, `record_stop_rule.csv`, `cohort.csv`, `cohort_stage_summary.csv`를 재생성할 수 있습니다.
- `python build_data.py`도 대회 집계에서 같은 우선순위(`records_full` → `records`)로 원천을 직접 읽습니다. 이 경로는 CSV를 거치지 않고 `analyze.py` 함수를 그대로 호출하므로 `Int64` 결측(`pd.NA`)이 살아 있습니다 — 값 변환 헬퍼는 `as_text()`를 거쳐 NA를 흡수해야 합니다.
- `records_anon.csv`의 `toCd`는 `SPLITS_MEET_INDEX_CSV`(또는 `data/meet_index_inf201.csv`, `/Users/kihyun/orgs/personal/splits/data/meet_index_inf201.csv`)가 있으면 자동 매핑하며, 매칭이 불명확하면 공백으로 둡니다.
- `records_anon.csv`의 `classCd`는 종목 구분값(`1`=스피드, `2`=쇼트트랙, `3`=피겨)이며, 라운드 형태(`N조`)와 대회명 규칙으로 행 단위 판별합니다. 통계 집계는 `classCd=2`만 사용하고 나머지 행도 삭제하지 않습니다.
- 익명키 생성식은 `sha256(idNo + SALT)[:12]`이고 `소속`은 입력에 포함하지 않습니다(`build_data.anon_key_spec()` 기준).
- 이미 커밋된 `records_anon.csv`에 컬럼을 추가·개명할 때는 익명키 재생성을 피하기 위해 `python scripts/backfill_records_anon_class_cd.py`를 사용합니다.
- `stats_distribution.csv`는 `출생연도×성별×거리` 단위이며 실제 데이터가 있는 조합만 생성합니다. 기록 통계(쇼트트랙 예선)와 순위 통계(쇼트트랙 학령 결승·채점종합)는 대상이 달라 인원수와 k-익명성 판정을 각각 분리합니다.
- `gap_return_rates.csv`는 `participation.csv` 시즌열에서 공백 에피소드를 만들고, 공백 `n`시즌 이상 구간의 복귀율을 계산합니다. 복귀 판단은 종목 전환(스피드 포함) 이후 활동도 `복귀`로 처리해 `기록 중단`으로 과대계산하지 않습니다.
- `record_stop_rule.csv`는 기준(`복귀율 <= 20%`, `분모 >= 100`)을 동시에 만족하는 최소 `n`을 `n시즌 연속 미출전 = 기록 중단` 기준으로 확정하고 근거 문장을 남깁니다.
- `cohort.csv`는 첫시즌/첫학년/좌측절단을 바탕으로 단계별(중등·고등·대학) 분석대상 플래그를 고정합니다. 관측 충분성은 `진입학년 도달 필요 시즌 + 기록중단 기준 n시즌`을 함께 반영합니다.
- k-익명성 기준(`k=10`) 미만 구간은 행을 유지하되 해당 쪽 `인원수`/지표를 `데이터 부족`으로 표기합니다.
- 산출물 생성 후에는 `python scripts/audit_data_quality.py`로 스키마·k-익명성·분위수 단조성·물리적 타당성·도메인 신호·커버리지를 점검합니다. 원천 데이터나 SALT 없이 실행됩니다.
- 식별키 신뢰도 감사 산출물(`merge_audit_sample_private.csv`, `merge_audit_signals_private.csv`)은 원천 식별자를 포함할 수 있으므로 로컬 전용으로만 사용하고 Git에 커밋하지 않습니다.
