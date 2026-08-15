# data 디렉터리 커밋 정책

이 저장소는 통계 재집계를 가능하게 유지하면서 개인정보 커밋을 막기 위해 `data/` 커밋 범위를 제한합니다.

## 1) 커밋 허용 파일

- `data/README.md`
- `data/records_anon.csv`
- `data/stats_distribution.csv`
- `data/stats_participation.csv`
- `data/public_figures.csv` (의도된 실명 명단)
- `data/coverage.csv`
- `data/meet_index_inf201.csv`

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

## 4) 익명키 규칙

- 생성식: `sha256(idNo + SALT)[:12]`
- SALT 입력: 환경변수 `SPLITS_ANON_SALT`
- SALT는 저장소에 커밋하지 않고 로컬 환경에서만 관리합니다.
- SALT 유실 시 익명키 재현이 불가능하므로 별도 안전 백업이 필요합니다.

## 5) 생성 순서

```bash
export SPLITS_ANON_SALT='로컬에서만 보관하는_충분히긴_무작위문자열'
export SPLITS_MEET_INDEX_CSV='/Users/kihyun/orgs/personal/splits/data/meet_index_inf201.csv'
python3 analyze.py
python3 build_data.py
```

- `analyze.py`는 통계 CSV를 생성합니다.
- `build_data.py`는 사이트 JSON과 `records_anon.csv`를 생성하며, `SPLITS_MEET_INDEX_CSV`를 지정하면 `toCd`를 함께 채웁니다.

## 6) 커밋 전 검증

```bash
git config core.hooksPath .githooks
python3 scripts/check_data_commit_policy.py --mode tracked
```

- `pre-commit` 훅은 스테이징 파일(`--mode staged`)을 자동 검사합니다.
- CI는 추적 파일 전체(`--mode tracked`)를 검사합니다.
