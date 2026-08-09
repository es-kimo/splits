# splits
대한체육회 경기결과 데이터에서 쇼트트랙 선수 이력을 수집·정제해 공개하는 프로젝트입니다.
선수 식별(idNo) 확정, 대회 기록 수집, 분석 산출물 생성 과정을 단일 파이프라인으로 운영합니다.
현재 공인 선수 지정 명단 기준 선수별 성적/이력 페이지를 정적 사이트로 제공합니다. 선수 목록은 `athlete/`, 선수 개별 URL은 `athlete/{slug}/` 패턴으로 생성됩니다.

공개 대상 명단은 `data/public_figures.csv`를 수동으로 관리합니다.

- 컬럼: `idNo, 이름, 슬러그, 출생연도, 지정근거, 언론보도URL, 지정일자, 상태(active/removed)`
- 자동 지정 로직은 사용하지 않습니다.
- `상태=removed`는 삭제 요청 우선 처리 상태이며, 빌드 시 페이지/목록/사이트맵에서 제외됩니다.

배포 URL: https://es-kimo.github.io/splits/
실행 방법: `pip install -r requirements.txt && python scrape.py history && python analyze.py && python build_data.py && python build_site.py`
`python build_data.py` 실행 시 `site/data/*.json` 계약 파일을 생성하고, `python build_site.py`는 해당 JSON만 읽어 HTML을 생성합니다.
reference 안내: 세부 데이터 구조/분석 메모는 `/home/runner/work/splits/splits/reference/`를 참고하세요.

## 검색엔진 색인 파일
- `python build_site.py` 실행 시 루트에 `sitemap.xml`, `robots.txt`가 함께 생성됩니다.
- sitemap 포함 URL:
  - `https://es-kimo.github.io/splits/`
  - `https://es-kimo.github.io/splits/athlete/`
  - `https://es-kimo.github.io/splits/athlete/{slug}/`
  - `https://es-kimo.github.io/splits/privacy/`

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
