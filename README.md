# splits
대한체육회 경기결과 데이터에서 쇼트트랙 선수 이력을 수집·정제해 공개하는 프로젝트입니다.
선수 식별(idNo) 확정, 대회 기록 수집, 분석 산출물 생성 과정을 단일 파이프라인으로 운영합니다.
Python 파이프라인은 데이터 생성에 집중하고, 사이트 렌더링은 Astro(`web/`)가 담당합니다. 공개 사이트 URL 패턴은 `athlete/`, `athlete/{slug}/`, `meet/`, `meet/{slug}/`, `distribution/`, `privacy/`입니다.

공개 대상 명단은 `data/public_figures.csv`를 수동으로 관리합니다.

- 컬럼: `idNo, 이름, 슬러그, 출생연도, 지정근거, 언론보도URL, 지정일자, 상태(active/removed)`
- 자동 지정 로직은 사용하지 않습니다.
- `상태=removed`는 삭제 요청 우선 처리 상태이며, 빌드 시 페이지/목록/사이트맵에서 제외됩니다.

배포 URL: https://es-kimo.github.io/splits/
실행 방법: `pip install -r requirements.txt && python scrape.py history && python analyze.py && python build_data.py && python build_site.py`
`python build_data.py` 실행 시 `site/data/*.json` 계약 파일을 생성하고, `python build_site.py`는 Astro 빌드를 실행해 루트 정적 파일을 동기화합니다.
Astro 의존성은 최초 1회 `cd web && npm install`로 설치합니다.
reference 안내: 세부 데이터 구조/분석 메모는 `/home/runner/work/splits/splits/reference/`를 참고하세요.

`python analyze.py`는 기존 산출물과 함께 익명 통계 CSV를 생성합니다.
- `data/stats_distribution.csv`: 출생연도·성별·학령구간·거리 기준 분포(`기록_p10/p25/p50/p75/p90`, `순위_p25/p50/p75`)
- `data/stats_participation.csv`: 출생연도·성별 기준 참여 통계(`최초출전나이_p25/p50/p75`, `초등부출전수_p50`)
- 익명 통계 입력은 `data/records_full.csv`, `data/athlete_info_full.csv`가 있으면 이를 우선 사용하고, 없으면 `data/records.csv`, `data/athlete_info.csv`를 사용합니다.
- k-익명성 기준 `k=10` 미만 구간은 행을 유지하되 `인원수`와 지표를 모두 `데이터 부족`으로 표기합니다.
- 산출물에는 개인 식별 컬럼(`idNo`, `이름`, `소속`, `시도`)이 포함되지 않도록 자동 검증합니다.

## 전체 선수 기록 수집(비공개 원천 데이터)

- 선수 인덱스(`data/athlete_index.csv`)와 id 병합표(`data/id_merges.csv`) 기준으로 INF503 기록을 수집합니다.
- 수집 캐시: `data/raw/history/{idNo}.html`
- 진행 상태: `data/collect_progress.json`
- 실패 목록: `data/collect_failures.csv`
- 중간 산출물: `data/records_full.csv`, `data/athlete_info_full.csv`

```bash
python collect_full_history.py collect
python collect_full_history.py retry-failures
python collect_full_history.py compare-resolved
python collect_full_history.py cleanup-raw-cache
```

```bash
# worktree에서 개인 데이터 저장소를 직접 참조
python collect_full_history.py --data-dir /Users/kihyun/orgs/personal/splits/data collect
```

- `collect`: 미수집 대상만 이어받아 수집하고 full CSV를 생성합니다.
- `collect --refresh`: 전체 재수집합니다.
- `retry-failures`: 실패 목록만 재시도한 뒤 full CSV를 다시 생성합니다.
- `compare-resolved`: 기존 14명(`data/resolved.csv`)의 기존 산출물과 full 산출물을 회귀 비교합니다.
- `cleanup-raw-cache`: 집계 완료 후 `data/raw/history/*.html` 캐시만 삭제합니다.
- `--data-dir`: 입출력 데이터 기준 디렉터리를 바꿉니다. 미지정 시 `./data`, 또는 환경변수 `SPLITS_DATA_DIR`를 사용합니다.

## 검색엔진 색인 파일
- `python build_site.py` 실행 시 Astro 출력물과 함께 루트에 `sitemap.xml`, `robots.txt`가 생성됩니다.
- sitemap 포함 URL:
  - `https://es-kimo.github.io/splits/`
  - `https://es-kimo.github.io/splits/athlete/`
  - `https://es-kimo.github.io/splits/distribution/`
  - `https://es-kimo.github.io/splits/meet/`
  - `https://es-kimo.github.io/splits/meet/{slug}/`
  - `https://es-kimo.github.io/splits/athlete/{slug}/`
  - `https://es-kimo.github.io/splits/privacy/`
- `athlete/{slug}/`는 `data/public_figures.csv`에서 `상태=active`인 명단만 포함합니다.

## 검색엔진 등록 절차
1. Google Search Console
   - 속성: `https://es-kimo.github.io/splits/`
   - 사이트맵 제출: `https://es-kimo.github.io/splits/sitemap.xml`
2. 네이버 서치어드바이저
   - 사이트 등록: `https://es-kimo.github.io/splits/`
   - 사이트맵 제출: `https://es-kimo.github.io/splits/sitemap.xml`
3. 완료 체크
   - 두 콘솔에서 사이트맵 제출 상태가 성공인지 확인
   - 주요 URL에 대해 색인 요청(또는 수집 요청) 실행
