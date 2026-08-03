# splits
대한체육회 경기결과 데이터에서 쇼트트랙 선수 이력을 수집·정제해 공개하는 프로젝트입니다.
선수 식별(idNo) 확정, 대회 기록 수집, 분석 산출물 생성 과정을 단일 파이프라인으로 운영합니다.
현재 14명 기준 선수별 성적/이력 페이지를 정적 사이트로 제공합니다. 선수 개별 URL은 `athlete/{idNo}/` 패턴으로 생성됩니다.

배포 URL: https://es-kimo.github.io/splits/
실행 방법: `pip install -r requirements.txt && python scrape.py history && python analyze.py && python build_site.py`
reference 안내: 세부 데이터 구조/분석 메모는 `/home/runner/work/splits/splits/reference/`를 참고하세요.
