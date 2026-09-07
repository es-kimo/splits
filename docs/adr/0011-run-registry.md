# ADR 0011 — 실행 레지스트리와 콘텐츠 주소 지정 (R-09)

- 상태: Accepted
- 작성일: 2026-09-07
- 선행: `docs/adr/0010-replay-strategy.md`

## 문맥

레이팅 실행이 늘어나면 값의 출처를 구분하지 못한 채 서로 다른 입력, 엔진 설정,
보정기를 한 계산에 섞을 위험이 있습니다. 출력 파일 이름이나 생성 시각은 같은
실행을 식별하는 근거가 될 수 없습니다.

## 결정

1. 입력 스냅샷 ID는 레저 루트의 모든 일반 파일을 상대 경로 순으로 정렬해, 각
   파일의 SHA-256과 경로를 다시 해시해 계산합니다. mtime은 사용하지 않습니다.
2. `run_id`는 다음의 SHA-256 앞 16자리입니다.

   ```text
   algo_version || canonical_json(engine_params) ||
   canonical_json(calibrator_spec) || input_snapshot_id
   ```

   canonical JSON은 키를 정렬하고 유한 부동소수 값을 고정 표기로 직렬화합니다.
3. `algo_version`은 `rating/replay/version.py`에서 수동 관리합니다. 엔진, 리플레이,
   입력 식별, 보정 코드가 바뀌었는데 이 버전 파일이 바뀌지 않으면 CI가 실패합니다.
   관계없는 커밋 SHA는 기록용이며 `run_id`에는 포함하지 않습니다.
4. 레지스트리는 `out/rating_runs/registry.sqlite`에 `rating_run`과
   `rating_snapshot`을 보관합니다. 스냅샷의 `sigma`는 현재 선택 엔진에서 예측
   불확실성으로 사용되는 값입니다.
5. 실행 산출물은 오직 `out/rating_runs/runs/<run_id>/`에 작성합니다. 스냅샷,
   보정기, 매니페스트, 리포트가 모두 완성되고 DB 상태가 `complete`가 된 후에만
   `runs/current` 텍스트 포인터를 `os.replace`로 교체합니다.
6. 조회는 시작 시 `current`의 run ID를 한 번 고정하고, 완료 상태만 읽습니다.
   반환값에는 항상 `run_id`가 포함되며 서로 다른 ID의 값을 함께 사용하려 하면
   예외를 냅니다.
7. 실패한 실행은 `failed`로 기록하고 디버깅 산출물을 남기되 기본 목록, 조회,
   `current`에서는 제외합니다. 현재 용량과 실행 빈도 근거가 없으므로 자동 정리는
   하지 않고 모든 완료 실행을 보존합니다.

## 결과

- 같은 입력·설정·보정기는 동일한 ID를 갖고, 완성된 기존 실행을 재사용할 수 있습니다.
- 입력 내용, 엔진 파라미터, 보정기 계수 중 하나라도 달라지면 다른 ID가 됩니다.
- 부분 작성 또는 실패 산출물이 서빙/분석 경로에 노출되지 않습니다.

## 사용

```bash
python -m rating.replay.orchestrator --params configs/base.toml --register
python -m rating.replay.registry --list
```
