.PHONY: help setup dev build build-quick update-weekly collect-full collect-retry export-full rating rating-calibration rating-eval rating-sigma-diagnosis audit test clean

SHELL := /bin/bash
VENV ?= .venv
PYTHON := $(shell if [ -f $(VENV)/bin/python ]; then echo $(VENV)/bin/python; else echo python3; fi)
PYTEST := $(shell if [ -f $(VENV)/bin/pytest ]; then echo $(VENV)/bin/pytest; else echo pytest; fi)

# 기본 색상 정의
BLUE := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RESET := \033[0m

help: ## 📖 사용 가능한 전체 명령어 목록 출력
	@echo -e "$(BLUE)======================================================================$(RESET)"
	@echo -e "$(GREEN)  splits 프로젝트 파이프라인 단축 명령어 (Makefile)$(RESET)"
	@echo -e "$(BLUE)======================================================================$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo -e "$(BLUE)======================================================================$(RESET)"

setup: ## 🛠️ 파이썬 패키지 및 Astro 웹 의존성 설치
	@echo -e "$(YELLOW)[1/2] Python 의존성 설치 중...$(RESET)"
	pip install -r requirements.txt
	@echo -e "$(YELLOW)[2/2] Astro 웹 프론트엔드 의존성 설치 중...$(RESET)"
	npm install --prefix web

dev: ## 🌐 Astro 로컬 개발 서버 실행 (웹 UI 실시간 확인)
	@echo -e "$(GREEN)로컬 개발 서버를 시작합니다 (http://localhost:4321)...$(RESET)"
	npm run dev --prefix web

build: ## 🚀 [기본 빌드] 통계 분석 -> site JSON 생성 -> 정적 사이트 빌드
	@echo -e "$(YELLOW)[1/3] analyze.py: 통계 및 코호트 분석 실행...$(RESET)"
	$(PYTHON) analyze.py
	@echo -e "$(YELLOW)[2/3] build_data.py: site/data/*.json 생성...$(RESET)"
	$(PYTHON) build_data.py
	@echo -e "$(YELLOW)[3/3] build_site.py: Astro 정적 사이트 빌드...$(RESET)"
	$(PYTHON) build_site.py
	@echo -e "$(GREEN)✅ 빌드 완료! (결과물이 루트 디렉토리에 동기화되었습니다)$(RESET)"

build-quick: ## ⚡ [공인선수 빠른 빌드] scrape resolve/history -> analyze -> build
	@echo -e "$(YELLOW)[1/5] scrape.py resolve: 공인 선수 ID 확정...$(RESET)"
	$(PYTHON) scrape.py resolve
	@echo -e "$(YELLOW)[2/5] scrape.py history: 경기 이력 수집...$(RESET)"
	$(PYTHON) scrape.py history
	@echo -e "$(YELLOW)[3/5] analyze.py: 통계 분석...$(RESET)"
	$(PYTHON) analyze.py
	@echo -e "$(YELLOW)[4/5] build_data.py: JSON 변환...$(RESET)"
	$(PYTHON) build_data.py
	@echo -e "$(YELLOW)[5/5] build_site.py: 정적 사이트 빌드...$(RESET)"
	$(PYTHON) build_site.py
	@echo -e "$(GREEN)✅ 공인선수 빠른 빌드 완료!$(RESET)"

update-weekly: ## 🔄 [주간 증분] 신규 대회 수집 -> records_anon 갱신 -> 통계 -> 사이트 빌드
	@echo -e "$(YELLOW)[1/4] collect_full_history.py weekly-incremental: 신규 대회 수집...$(RESET)"
	$(PYTHON) collect_full_history.py weekly-incremental --fail-on-unknown-failures
	@echo -e "$(YELLOW)[2/4] analyze.py: 통계 재집계...$(RESET)"
	$(PYTHON) analyze.py
	@echo -e "$(YELLOW)[3/4] build_data.py: 계약 데이터 갱신...$(RESET)"
	$(PYTHON) build_data.py
	@echo -e "$(YELLOW)[4/4] build_site.py: 정적 사이트 배포 빌드...$(RESET)"
	$(PYTHON) build_site.py
	@echo -e "$(GREEN)✅ 주간 업데이트 완료!$(RESET)"

collect-full: ## 🌐 [분기 전수 수집] 전체 대회 및 선수 전수 크롤링 실행
	@echo -e "$(YELLOW)전체 기록 수집을 시작합니다...$(RESET)"
	$(PYTHON) collect_full_history.py collect

collect-retry: ## 🔁 [수집 실패 복구] 실패/부분완료 대회 재시도 및 export
	@echo -e "$(YELLOW)[1/2] 실패 대회 재수집...$(RESET)"
	$(PYTHON) collect_full_history.py retry-failures
	@echo -e "$(YELLOW)[2/2] full CSV 재생성...$(RESET)"
	$(PYTHON) collect_full_history.py export

rating: ## 🏆 [레이팅 계산] 경기 레저 Parquet 생성 -> TrueSkill 레이팅 계산
	@echo -e "$(YELLOW)[1/2] rating.ledger.build: Parquet 레저 구축...$(RESET)"
	$(PYTHON) -m rating.ledger.build --results $(shell if [ -f data/records_full.csv ]; then echo data/records_full.csv; else echo data/records_anon.csv; fi) --out out/ledger
	@echo -e "$(YELLOW)[2/2] rating.engine.runner: TrueSkill 레이팅 산출...$(RESET)"
	$(PYTHON) -m rating.engine.runner --ledger out/ledger --out out/ratings_baseline.parquet --report out/baseline_report.md --engine trueskill --rating-period meet
	@echo -e "$(GREEN)✅ 레이팅 산출 완료! (out/ratings_baseline.parquet)$(RESET)"

rating-age: ## 📈 [연령 모델] records_anon 기반 레저/메타 구축 -> 연령 정규화 리포트 생성
	@echo -e "$(YELLOW)[1/3] rating.ledger.build: 연령 메타 포함 레저 구축...$(RESET)"
	$(PYTHON) -m rating.ledger.build --results data/records_anon.csv --policy conservative --out out/ledger
	@echo -e "$(YELLOW)[2/3] rating.engine.runner: TrueSkill 스냅샷 생성...$(RESET)"
	$(PYTHON) -m rating.engine.runner --ledger out/ledger --out out/ratings_baseline.parquet --report out/baseline_report.md --engine trueskill --rating-period meet
	@echo -e "$(YELLOW)[3/3] rating.engine.age: 연령 베이스라인/정규화 산출...$(RESET)"
	$(PYTHON) -m rating.engine.age --ratings out/ratings_baseline.parquet --ledger out/ledger --out out/age_curves.md --adjusted-out out/ratings_age_adjusted.parquet
	@echo -e "$(GREEN)✅ 연령 산출 완료! (out/age_curves.md, out/ratings_age_adjusted.parquet)$(RESET)"

rating-eval: rating ## 📊 [레이팅 백테스트] 정책별 비교 및 예측력 백테스트 리포트 생성
	@echo -e "$(YELLOW)rating.eval.backtest: 백테스트 평가 실행...$(RESET)"
	$(PYTHON) -m rating.eval.backtest --ledger out/ledger --holdout-seasons 2 --all-configs --out out/backtest_report.md
	@echo -e "$(GREEN)✅ 백테스트 완료! (out/backtest_report.md)$(RESET)"

rating-calibration: rating ## 🧭 [보정 프로토콜] 적합 폴드·재적합 주기·세그먼트 분리 판정 리포트 생성
	@echo -e "$(YELLOW)rating.calibration.protocol: 보정 프로토콜 평가 실행...$(RESET)"
	$(PYTHON) -m rating.calibration.protocol --ledger out/ledger --policy conservative --rating-period meet --engine trueskill --out out/calibration_report.md
	@echo -e "$(GREEN)✅ 보정 프로토콜 완료! (out/calibration_report.md)$(RESET)"

rating-sigma-diagnosis: ## 🔬 [sigma 진단] 실력 차이를 통제해 sigma-오차 역전이 교락인지 버그인지 판정
	@echo -e "$(YELLOW)rating.eval.sigma_diagnosis: |mu 차이| 통제 후 sigma-오차 관계 측정...$(RESET)"
	$(PYTHON) -m rating.eval.sigma_diagnosis --ledger out/ledger --out out/sigma_diagnosis_report.md
	@echo -e "$(GREEN)✅ 진단 완료! (out/sigma_diagnosis_report.md, out/sigma_diagnosis/n_games_vs_sigma.svg)$(RESET)"

audit: ## 🔍 [품질 감사] 커밋 정책 준수 검사 & ID 병합 신뢰도 감사
	@echo -e "$(YELLOW)[1/2] 커밋 정책 감사 (개인정보 누출 방지)...$(RESET)"
	$(PYTHON) scripts/check_data_commit_policy.py
	@echo -e "$(YELLOW)[2/2] ID 키 신뢰도 및 병합 감사...$(RESET)"
	$(PYTHON) scripts/audit_id_key_reliability.py
	@echo -e "$(GREEN)✅ 품질 감사 완료!$(RESET)"

test: ## 🧪 [단위 테스트] pytest 전체 실행
	$(PYTEST) -v

clean: ## 🧹 빌드 산출물 및 임시 파일 정리
	@echo -e "$(YELLOW)웹 빌드 결과물 및 캐시 삭제 중...$(RESET)"
	rm -rf web/dist _astro
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo -e "$(GREEN)✅ 정리 완료!$(RESET)"
