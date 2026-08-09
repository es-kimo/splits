# splits
대한체육회 경기결과 데이터에서 쇼트트랙 선수 이력을 수집·정제해 공개하는 프로젝트입니다.
선수 식별(idNo) 확정, 대회 기록 수집, 분석 산출물 생성 과정을 단일 파이프라인으로 운영합니다.
현재 14명 기준 선수별 성적/이력 페이지를 정적 사이트로 제공합니다. 선수 목록은 `athlete/`, 선수 개별 URL은 `athlete/{idNo}/` 패턴으로 생성됩니다.

배포 URL: https://es-kimo.github.io/splits/
실행 방법: `pip install -r requirements.txt && python scrape.py history && python analyze.py && python build_site.py`
reference 안내: 세부 데이터 구조/분석 메모는 `/home/runner/work/splits/splits/reference/`를 참고하세요.

## 검색엔진 색인 파일
- `python build_site.py` 실행 시 루트에 `sitemap.xml`, `robots.txt`가 함께 생성됩니다.
- sitemap 포함 URL:
  - `https://es-kimo.github.io/splits/`
  - `https://es-kimo.github.io/splits/athlete/`
  - `https://es-kimo.github.io/splits/athlete/{idNo}/`
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
