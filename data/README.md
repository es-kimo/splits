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
- `data/cohort.csv`
- `data/cohort_stage_summary.csv`
- `data/retention_overall.csv`
- `data/retention_band.csv`
- `data/improvement_rate.csv`
- `data/reverse_distribution.csv`
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

## 3-4) cohort.csv 규격

헤더(순서 고정):

`익명키, 성별, 출생연도, 첫대회연도, 첫시즌, 첫학년, 마지막시즌, 기록중단기준n, 좌측절단, 도달_중등, 도달_고등, 도달_대학, 관측충분_중등, 관측충분_고등, 관측충분_대학, 분석대상_중등, 분석대상_고등, 분석대상_대학`

- `좌측절단`: 첫 대회연도가 관측 시작연도(현재 데이터 기준 2007)인 선수 여부
- `도달_*`: 해당 단계(중등/고등/대학·일반) 이상 학년에 실제 도달했는지 여부
- `관측충분_*`: `진입학년 도달 필요 시즌 + 기록중단기준n` 조건을 충족해 미도달 판정이 가능한지 여부
- `분석대상_*`: `도달_* 또는 관측충분_*`을 만족하고 좌측절단이 아닌 선수

## 3-5) cohort_stage_summary.csv 규격

헤더(순서 고정):

`분석단계, 목표진입학년, 기록중단기준n, 관측판정식, 대상N, 남자N, 여자N, 이미도달N, 관측충분미도달N, 좌측절단제외N, 사용가능시즌범위, N100미만, 신뢰한계문구`

- 단계별 분석대상 수(`대상N`)와 성별 분포를 기록합니다.
- `N100미만=Y`인 경우 `신뢰한계문구`에 표본 부족 경고를 남깁니다.

## 3-6) retention_overall.csv 규격

헤더(순서 고정):

`지표유형, 기준, 분리기준, 분리값, 학년, 전환구간, 잔존인원, 잔존율(%), 신규진입인원, 다음학년진입인원, 학년이탈인원, 학년이탈률(%), 도달단계, 도달인원, 도달률(%), 대상인원, 병합의심률(%), 관측시즌범위, 신뢰한계문구`

- `지표유형`: `학년잔존` 또는 `단계도달`
- `기준`: `쇼트트랙 기준` 또는 `빙상 전체 기준`
- `분리기준`: `전체`, `성별`, `시작학년`, `시작시즌대`
- `학년잔존` 행은 학년별 `잔존/신규진입/이탈`을 포함하고, `전환구간`에 `6→7`, `9→10`, `12→13`을 표시합니다.
- `단계도달` 행은 `도달단계`(중등/고등/대학·일반)별 `도달인원`, `도달률(%)`, `대상인원`을 포함합니다.
- `병합의심률(%)`, `관측시즌범위`, `신뢰한계문구`로 병합 리스크·표본 N·관측기간 한계를 함께 기록합니다.

## 3-7) retention_band.csv 규격

헤더(순서 고정):

`기준유형, 성별, 구간수, 백분위구간, 구간정렬값, 병합규칙, 표본N, 중등대상N, 중등도달N, 중등도달률(%), 중등도달CI하한(%), 중등도달CI상한(%), 고등대상N, 고등도달N, 고등도달률(%), 고등도달CI하한(%), 고등도달CI상한(%), 대학일반대상N, 대학일반도달N, 대학일반도달률(%), 대학일반도달CI하한(%), 대학일반도달CI상한(%), 기록대비방향일치_중등, 기록대비방향일치_고등, 기록대비방향일치_대학일반, 신뢰한계문구`

- `기준유형`: `기록백분위` 또는 `순위백분위`
- 백분위 구간 기본값은 `상위 10%`, `10~30%`, `30~50%`, `50% 이하`입니다.
- 구간 표본이 부족하면 `병합규칙`에 따라 `10~30%`와 `30~50%`를 `10~50%`로 병합합니다.
- `기록대비방향일치_*`는 순위 기준 결과가 기록 기준과 같은 방향인지(`Y`/`N`)를 나타냅니다.

## 3-8) improvement_rate.csv 규격

헤더(순서 고정):

`지표유형, 성별, 거리, 학년, 백분위구간, 표본N, 향상폭_p25(초), 향상폭_p50(초), 향상폭_p75(초), 평균향상폭(초), 예측단계, 향상속도_AUC(%), 백분위_AUC(%), 예측력차이(AUC%p), 신뢰한계문구`

- `지표유형`
  - `기준선`: 학년×성별×거리별 향상 폭 분포
  - `구간비교`: 백분위 구간별 향상 폭 비교
  - `예측력비교`: 향상 속도 vs 백분위의 단계 도달 예측력 비교
- 향상 폭은 같은 거리에서 `이전 시즌 최고기록 - 다음 시즌 최고기록`(초)으로 계산합니다.
- `예측력차이(AUC%p)`는 `향상속도_AUC(%) - 백분위_AUC(%)`입니다.

## 3-9) reverse_distribution.csv 규격

헤더(순서 고정):

`대상그룹, 지표, 구간, 대상N, 해당N, 비율(%), 국가대표N, 7번방향일치, 신뢰한계문구`

- `대상그룹`: `대학·일반 진입`, `고등부 완주`, `국가대표`
- `지표`
  - `백분위 분포`: `상위권`, `중위권`, `하위권`, `초등 기록 없음`
  - `유형 분류`: `조기 두각형`, `후발 상승형`, `늦은 시작형`
- `국가대표N`: 해당 구간 안에 포함되는 국가대표 사례 수
- `7번방향일치`: 이슈 #7 방향성과의 정합성(`Y`/`N`/공백)
- `신뢰한계문구`: 표본 부족, 결측 해석 주의, 방향 불일치 등 해석 한계를 누적 기록

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
- `analyze.py`는 시즌 분석 산출물(`season_month_histogram.csv`, `participation.csv`, `season_activity_counts.csv`, `class_transition_summary.csv`, `gap_return_rates.csv`, `record_stop_rule.csv`, `cohort.csv`, `cohort_stage_summary.csv`, `retention_overall.csv`, `retention_band.csv`, `improvement_rate.csv`, `reverse_distribution.csv`, `analysis/retention_overall.svg`)을 함께 생성합니다.
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

익명 산출물(`records_anon.csv`, `stats_distribution.csv`, `reverse_distribution.csv`, `site/data/distribution.json`)만 읽으므로
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
