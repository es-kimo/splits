# data 디렉터리 커밋 정책

이 저장소는 통계 재집계를 가능하게 유지하면서 개인정보 커밋을 막기 위해 `data/` 커밋 범위를 제한합니다.

## 1) 커밋 허용 파일

- `data/README.md`
- `data/records_anon.csv`
- `data/stats_distribution.csv`
- `data/stats_participation.csv`
- `data/season_month_histogram.csv`
- `data/participation.csv`
- `data/season_activity_counts.csv`
- `data/class_transition_summary.csv`
- `data/gap_return_rates.csv`
- `data/record_stop_rule.csv`
- `data/public_figures.csv` (의도된 실명 명단)
- `data/coverage.csv`
- `data/meet_index_inf201.csv`
- `data/class_level_map.csv`
- `data/class_level_year_category_counts.csv`
- `data/class_level_ab_agreement_summary.csv`
- `data/class_level_ab_mismatch_types.csv`
- `data/class_level_year_readiness.csv`

## 2) 커밋 금지 파일

- `data/raw/**`
- `data/records.csv`
- `data/records_full.csv`
- `data/athlete_info.csv`
- `data/athlete_info_full.csv`
- `data/athlete_index.csv`
- `data/id_merge_candidates.csv`
- `data/id_merges.csv`
- `.env` 및 `.env.*`

## 3) records_anon.csv 규격

헤더(순서 고정):

`toCd, classCd, 대회명, 대회연도, 일자, 종별, 학령구간, 거리, SF여부, 라운드, 라운드종류, 순위, 기록_초, 사유, 성별, 출생연도, 학년, 익명키`

금지 컬럼:

`이름, idNo, 소속, 시도, BIB, 레인`

`toCd`는 `meet_index_inf201.csv`가 있으면 자동 매핑하고, 파일이 없거나 매칭이 애매하면 공백으로 둡니다.
주간 자동 갱신은 이 파일을 기준으로 신규 대회를 식별합니다.

`classCd`는 종목 구분값(`1`=스피드, `2`=쇼트트랙, `3`=피겨)이며 행 단위 규칙으로 산출합니다.

1. `라운드종류`가 `기타`이고 `라운드`가 `N조` 형태이면 스피드(`1`)
2. 대회명에 `스피드`가 있고 `쇼트트랙`이 없으면 스피드(`1`)
3. 그 외에는 쇼트트랙(`2`)

수집 원천(INF201)이 쇼트트랙 기준으로만 조회되어 응답의 `classCd`에는 종목 판별력이 없기 때문에 위 규칙을 사용합니다.
스피드 행도 삭제하지 않고 그대로 보존하며, 통계 집계 단계에서만 `classCd=2`를 사용합니다.
이미 커밋된 파일에 이 컬럼을 채울 때는 익명키를 유지하기 위해 `python3 scripts/backfill_records_anon_class_cd.py`를 사용합니다(재실행 가능).

## 3-1) participation.csv 규격

헤더(순서 고정):

`익명키, 시즌, 출생연도, 성별, 학년, 단계, 종별_단계, 대회수, 경기수, classCd목록, 오픈참가`

- `익명키`는 12자리 hex 형식이어야 합니다.
- `오픈참가`는 `Y`/`N` 값만 허용합니다.
- `classCd목록`은 시즌 내 참가한 종목 코드를 `|`로 연결합니다(예: `1|2`).

## 3-2) gap_return_rates.csv 규격

헤더(순서 고정):

`구간, 공백시즌수, 사례수, 복귀사례, 복귀율(%), 관측부족제외수`

- `구간`: `전체`, `6→7`, `9→10`, `12→13`
- `공백시즌수`: `1`, `2`, `3`, `4+` (각 `n시즌 이상` 구간)
- `사례수`: 관측기간이 충분해 해당 구간 평가가 가능한 사례 수
- `복귀사례`: 사례수 중 이후 시즌에 다시 활동이 확인된 사례 수
- `관측부족제외수`: 분모 산정에서 제외된 사례 수

복귀 판단은 `classCd목록` 기준으로 종목 전환(스피드 포함) 이후 활동도 `복귀`로 처리합니다.  
즉, 스피드 전환 선수는 `기록 중단`으로 계산하지 않습니다.

## 3-3) record_stop_rule.csv 규격

헤더(순서 고정):

`기준식, 복귀율기준(%), 분모기준, 확정n, 근거구간, 근거사례수, 근거복귀사례, 근거복귀율(%), 근거문장`

- 기본 기준: `복귀율 <= 20%` 및 `분모 >= 100`
- `확정n`: 위 기준을 동시에 만족하는 최소 `n` (없으면 `보류`)
- `근거문장`: 기준 확정/보류 사유를 사람이 읽을 수 있는 문장으로 기록

## 4) 익명키 규칙

- 생성식: `sha256(idNo + SALT)[:12]`
- SALT 입력: 환경변수 `SPLITS_ANON_SALT`
- SALT는 저장소에 커밋하지 않고 로컬 환경에서만 관리합니다.
- SALT 유실 시 익명키 재현이 불가능하므로 별도 안전 백업이 필요합니다.

## 5) 생성 순서

```bash
cat > .env.local <<'EOF'
SPLITS_ANON_SALT=<충분히 긴 랜덤 문자열>
SPLITS_MEET_INDEX_CSV=/Users/kihyun/orgs/personal/splits/data/meet_index_inf201.csv
EOF
python3 analyze.py
python3 build_data.py
```

- `analyze.py`는 통계 CSV를 생성합니다.
- `analyze.py`는 익명 통계 CSV와 단계 판정 진단 CSV를 생성합니다.
- `analyze.py`는 시즌 분석 산출물(`season_month_histogram.csv`, `participation.csv`, `season_activity_counts.csv`, `class_transition_summary.csv`, `gap_return_rates.csv`, `record_stop_rule.csv`)을 함께 생성합니다.
- `build_data.py`는 사이트 JSON과 `records_anon.csv`를 생성하며, `SPLITS_MEET_INDEX_CSV`를 지정하면 `toCd`를 함께 채웁니다.
- `build_data.py`와 `collect_full_history.py`는 `.env.local`/`.env`를 자동 로드합니다(이미 설정된 셸 환경변수가 우선).

## 6) 커밋 전 검증

```bash
git config core.hooksPath .githooks
python3 scripts/check_data_commit_policy.py --mode tracked
```

- `pre-commit` 훅은 스테이징 파일(`--mode staged`)을 자동 검사합니다.
- CI는 추적 파일 전체(`--mode tracked`)를 검사합니다.

## 7) 데이터 품질 점검

```bash
python3 scripts/audit_data_quality.py
```

익명 산출물(`records_anon.csv`, `stats_distribution.csv`, `site/data/distribution.json`)만 읽으므로
원천 데이터나 SALT 없이 실행할 수 있습니다. 점검 항목은 다음과 같습니다.

| 구분 | 확인 내용 |
| --- | --- |
| 스키마·개인정보 | 금지 컬럼 부재, 익명키 형식, `classCd` 도메인, 키 유일성 |
| k-익명성 | 공개 셀의 최소 인원수, 비공개 셀의 마스킹 누락 |
| 분위수 | 기록·순위 분위수 단조성, 순위 하한 |
| 물리적 타당성 | 이상치 하한 적용 여부, 세계기록 대비 검사, 상식적 상한 |
| 거리 정합성 | 같은 조건에서 짧은 거리가 더 빠른지, 평균 속도 범위 |
| 도메인 신호 | 성별 기록 차이와 성장 곡선이 알려진 사실을 재현하는지 |
| 표본 안정성 | 인접 출생연도 간 중앙값 급변, 공개 셀 표본 크기 |
| 산출물 정합성 | CSV와 사이트 JSON의 행·키·값 일치 |
| 커버리지 | 항목별 결측률, 공개 가능 조합 비율, 폴백 응답률 |

`--strict`를 붙이면 경고도 실패로 처리합니다.

## 9) 단계 판정 진단 산출물 (이슈 #78)

`analyze.py`는 아래 진단 파일을 함께 생성합니다.

- `data/class_level_map.csv`: `종별` 원문 전수 목록과 정규화 단계(A)
- `data/class_level_year_category_counts.csv`: 연도 × 종별 행 수
- `data/class_level_ab_agreement_summary.csv`: 종별 기반(A) vs 출생연도 계산(B) 요약
- `data/class_level_ab_mismatch_types.csv`: A/B 불일치 유형별 건수
- `data/class_level_year_readiness.csv`: 연도별 단계 분석 사용 가능 여부

단계 계산(B) 기본식:

`학년 = 시즌시작연도 - 출생연도 - 6` (시즌 시작월 7월 기준)

- B를 기본 판정으로 사용하고, 출생연도 결측 시에만 A(종별 기반)로 폴백합니다.
- `학년 <= 0`은 미취학/입력오류 구간으로 단계 분석에서 제외합니다.

## 8) 선수 식별키 신뢰도 점검 (이슈 #77)

```bash
python3 scripts/audit_id_key_reliability.py
# 또는 공유 원천 경로 명시
python3 scripts/audit_id_key_reliability.py --data-dir /Users/kihyun/orgs/personal/splits/data
```

- 입력 우선순위: `records_full.csv + athlete_info_full.csv` → 없으면 `records.csv + athlete_info.csv`
- 요약 산출물: `data/merge_audit_summary.md` (숫자/유형 통계만 기록)
- 로컬 전용 private 산출물: `data/merge_audit_sample_private.csv`, `data/merge_audit_signals_private.csv`
- private 산출물은 원천 식별자를 포함할 수 있으므로 Git 커밋 금지입니다.
