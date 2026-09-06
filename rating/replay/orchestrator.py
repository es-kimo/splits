from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import pstats
import re
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from rating.engine.glicko2 import Glicko2Engine, Glicko2Params, Rating
from rating.engine.runner import group_periods, ledger_digest, to_race_results
from rating.engine.trueskill_wrapper import TrueSkillEngine, TrueSkillParams
from rating.engine.types import EngineName, Predictor, RatingPeriod
from rating.ledger.schema import load_race_ledger, validate_ledger
from rating.ledger.season import infer_season_year

from .checkpoint import (
    DEFAULT_CHECKPOINT_ROOT,
    Checkpoint,
    CheckpointError,
    checkpoint_id,
    find_nearest,
    load,
    params_digest,
    save,
)

_DEFAULT_ALGORITHM_VERSION = "rating.replay.v1"


@dataclass(frozen=True)
class ReplayParams:
    engine_name: EngineName = "trueskill"
    rating_period: RatingPeriod = "meet"
    algorithm_version: str = _DEFAULT_ALGORITHM_VERSION
    tau: float = 25.0 / 300.0
    initial_mu: float = 25.0
    initial_sigma: float = 25.0 / 3.0
    glicko_initial_mu: float = 1500.0
    glicko_initial_phi: float = 350.0
    glicko_initial_sigma: float = 0.06
    beta: float = 25.0 / 6.0
    draw_probability: float = 0.0
    convergence_tolerance: float = 1e-4
    ep_max_iterations: int = 10
    max_iterations: int = 100
    epsilon: float = 1e-6
    pairwise_size_weight: bool = True

    def fingerprint(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReplayResult:
    final_state: dict[str, Rating]
    input_hash: str
    params_hash: str
    resumed_from: Checkpoint | None
    saved_checkpoints: tuple[Checkpoint, ...]
    race_count: int
    period_count: int
    elapsed_seconds: float
    season_elapsed_seconds: dict[int, float]

    def state_digest(self) -> str:
        lines = [
            "|".join(
                (
                    athlete_id,
                    float(rating.mu).hex(),
                    float(rating.phi).hex(),
                    float(rating.sigma).hex(),
                    rating.last_active.isoformat() if rating.last_active else "",
                    str(int(rating.n_games)),
                )
            )
            for athlete_id, rating in sorted(self.final_state.items())
        ]
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReplayBenchmark:
    replay: ReplayResult
    checkpoint_resume_seconds: float | None
    peak_memory_bytes: int
    profile_summary: str


def _build_predictor(params: ReplayParams) -> Predictor:
    if params.engine_name == "glicko2":
        return Glicko2Engine(
            params=Glicko2Params(
                tau=float(params.tau),
                initial_mu=float(params.glicko_initial_mu),
                initial_phi=float(params.glicko_initial_phi),
                initial_sigma=float(params.glicko_initial_sigma),
                rating_period=params.rating_period,
            ),
            epsilon=float(params.epsilon),
            max_iterations=int(params.max_iterations),
            pairwise_size_weight=bool(params.pairwise_size_weight),
        )
    if params.engine_name == "trueskill":
        return TrueSkillEngine(
            params=TrueSkillParams(
                initial_mu=float(params.initial_mu),
                initial_sigma=float(params.initial_sigma),
                beta=float(params.beta),
                tau=float(params.tau),
                draw_probability=float(params.draw_probability),
                rating_period=params.rating_period,
                convergence_tolerance=float(params.convergence_tolerance),
                ep_max_iterations=int(params.ep_max_iterations),
            )
        )
    raise ValueError(f"[error] 지원하지 않는 엔진입니다: {params.engine_name}")


def _checkpoint_for(
    *,
    root: Path,
    algorithm_version: str,
    params_hash: str,
    input_hash: str,
    cutoff_date: date,
) -> Checkpoint:
    cid = checkpoint_id(algorithm_version, params_hash, input_hash, cutoff_date)
    state_path = root / f"{cid}.parquet"
    metadata_path = root / f"{cid}.json"
    return Checkpoint(
        cid=cid,
        cutoff_date=cutoff_date,
        algorithm_version=algorithm_version,
        params_hash=params_hash,
        input_hash=input_hash,
        state_path=state_path,
        metadata_path=metadata_path,
    )


def _validate_checkpoint(
    checkpoint: Checkpoint,
    *,
    target_date: date,
    params: ReplayParams,
    params_hash: str,
    input_hash: str,
) -> None:
    if checkpoint.cutoff_date > target_date:
        raise CheckpointError("[error] checkpoint cutoff이 요청한 재생 종료일보다 뒤에 있습니다.")
    expected_cid = checkpoint_id(params.algorithm_version, params_hash, input_hash, checkpoint.cutoff_date)
    if checkpoint.cid != expected_cid:
        raise CheckpointError("[error] checkpoint이 현재 알고리즘, 파라미터 또는 입력과 호환되지 않습니다.")


def replay(
    ledger_path: Path,
    params: ReplayParams,
    from_checkpoint: Checkpoint | None = None,
    until: date | None = None,
    *,
    checkpoint_root: Path = DEFAULT_CHECKPOINT_ROOT,
) -> ReplayResult:
    started = time.perf_counter()
    race_ledger = load_race_ledger(ledger_path)
    validate_ledger(race_ledger)
    races = to_race_results(race_ledger)
    if not races:
        raise ValueError(f"[error] 평가 가능한 race가 없습니다: {ledger_path}")
    if until is not None:
        races = [race for race in races if race.race_date <= until]
    if not races:
        raise ValueError("[error] 요청한 종료일 이전에 평가 가능한 race가 없습니다.")
    target_date = max(race.race_date for race in races)
    input_hash = ledger_digest(ledger_path)
    resolved_params_hash = params_digest(params.fingerprint())
    checkpoint = from_checkpoint or find_nearest(
        target_date,
        params.algorithm_version,
        resolved_params_hash,
        input_hash,
        root=checkpoint_root,
    )
    state: dict[str, Rating] = {}
    if checkpoint is not None:
        _validate_checkpoint(
            checkpoint,
            target_date=target_date,
            params=params,
            params_hash=resolved_params_hash,
            input_hash=input_hash,
        )
        restored = load(checkpoint.cid, root=checkpoint_root, expected=checkpoint)
        if restored is None:
            raise CheckpointError(f"[error] 선택한 checkpoint 상태를 찾을 수 없습니다: {checkpoint.cid}")
        state = restored
        races = [race for race in races if race.race_date > checkpoint.cutoff_date]
    periods = group_periods(races, params.rating_period)
    predictor = _build_predictor(params)
    season_elapsed_seconds: dict[int, float] = {}
    saved_checkpoints: list[Checkpoint] = []
    all_races = to_race_results(race_ledger)
    final_date_by_season: dict[int, date] = {}
    for race in all_races:
        season = infer_season_year(race.race_date)
        if season is None:
            raise ValueError(f"[error] 시즌을 계산할 수 없습니다: {race.race_date}")
        previous = final_date_by_season.get(season)
        if previous is None or race.race_date > previous:
            final_date_by_season[season] = race.race_date

    for index, (period_date, period_races) in enumerate(periods):
        period_started = time.perf_counter()
        state = {
            athlete_id: Rating(
                mu=float(rating.mu),
                phi=float(rating.phi),
                sigma=float(rating.sigma),
                last_active=rating.last_active,
                n_games=int(rating.n_games),
            )
            for athlete_id, rating in predictor.update(state, period_races).items()
        }
        season = infer_season_year(period_date)
        if season is None:
            raise ValueError(f"[error] 시즌을 계산할 수 없습니다: {period_date}")
        season_elapsed_seconds[season] = season_elapsed_seconds.get(season, 0.0) + (time.perf_counter() - period_started)
        next_season = (
            infer_season_year(periods[index + 1][0])
            if index + 1 < len(periods)
            else None
        )
        is_season_end = next_season != season
        season_is_complete = final_date_by_season[season] == period_date
        if is_season_end and season_is_complete:
            candidate = _checkpoint_for(
                root=checkpoint_root,
                algorithm_version=params.algorithm_version,
                params_hash=resolved_params_hash,
                input_hash=input_hash,
                cutoff_date=period_date,
            )
            save(
                state,
                candidate.cid,
                root=checkpoint_root,
                algorithm_version=candidate.algorithm_version,
                params_hash=candidate.params_hash,
                input_hash=candidate.input_hash,
                cutoff_date=candidate.cutoff_date,
            )
            saved_checkpoints.append(candidate)

    return ReplayResult(
        final_state=state,
        input_hash=input_hash,
        params_hash=resolved_params_hash,
        resumed_from=checkpoint,
        saved_checkpoints=tuple(saved_checkpoints),
        race_count=len(races),
        period_count=len(periods),
        elapsed_seconds=time.perf_counter() - started,
        season_elapsed_seconds=season_elapsed_seconds,
    )


def benchmark(
    ledger_path: Path,
    params: ReplayParams,
    *,
    report_path: Path,
) -> ReplayBenchmark:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="splits-replay-bench-") as temporary_root:
        temporary_path = Path(temporary_root)
        cold_root = temporary_path / "cold"
        memory_root = temporary_path / "memory"
        profile_root = temporary_path / "profile"
        replay_result = replay(ledger_path, params, checkpoint_root=cold_root)
        target_season = infer_season_year(max(race.race_date for race in to_race_results(load_race_ledger(ledger_path))))
        if target_season is None:
            raise ValueError("[error] 마지막 시즌을 계산할 수 없습니다.")
        previous_season_checkpoints = [
            checkpoint
            for checkpoint in replay_result.saved_checkpoints
            if infer_season_year(checkpoint.cutoff_date) is not None
            and infer_season_year(checkpoint.cutoff_date) < target_season
        ]
        checkpoint_resume_seconds = None
        if previous_season_checkpoints:
            resume_result = replay(
                ledger_path,
                params,
                from_checkpoint=max(previous_season_checkpoints, key=lambda item: item.cutoff_date),
                checkpoint_root=cold_root,
            )
            checkpoint_resume_seconds = resume_result.elapsed_seconds
        tracemalloc.start()
        replay(ledger_path, params, checkpoint_root=memory_root)
        _, peak_memory_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        profile = cProfile.Profile()
        profile.enable()
        replay(ledger_path, params, checkpoint_root=profile_root)
        profile.disable()
    output = io.StringIO()
    pstats.Stats(profile, stream=output).sort_stats("cumulative").print_stats(15)
    profile_summary = output.getvalue().strip().replace(f"{Path.cwd().resolve().as_posix()}/", "")
    profile_summary = re.sub(r"\.venv/lib/[^/]+/site-packages/", "<site-packages>/", profile_summary)
    result = ReplayBenchmark(
        replay=replay_result,
        checkpoint_resume_seconds=checkpoint_resume_seconds,
        peak_memory_bytes=peak_memory_bytes,
        profile_summary=profile_summary,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Replay benchmark",
        "",
        f"- 전체 리플레이(콜드): **{result.replay.elapsed_seconds:.3f}초** (목표: < 60초, {'충족' if result.replay.elapsed_seconds < 60.0 else '미달'})",
        (
            f"- 마지막 시즌 체크포인트 재개: **{result.checkpoint_resume_seconds:.3f}초** "
            f"(목표: < 5초, {'충족' if result.checkpoint_resume_seconds < 5.0 else '미달'})"
            if result.checkpoint_resume_seconds is not None
            else "- 마지막 시즌 체크포인트 재개: 이전 시즌 체크포인트가 없어 측정하지 못했습니다."
        ),
        f"- 최대 메모리: **{result.peak_memory_bytes / (1024 * 1024):.2f} MiB**",
        f"- 처리 경기: **{result.replay.race_count:,}개**, 기간: **{result.replay.period_count:,}개**",
        "",
        "## 시즌별 처리 시간",
        "",
        "| 시즌 | 처리 시간 |",
        "| ---: | ---: |",
    ]
    lines.extend(f"| {season} | {elapsed:.3f}초 |" for season, elapsed in sorted(result.replay.season_elapsed_seconds.items()))
    lines.extend(["", "## 프로파일 상위 항목", "", "```text", result.profile_summary, "```", ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="결정적 레이팅 리플레이와 시즌 체크포인트 실행기")
    parser.add_argument("--ledger", default="out/ledger", help="race_ledger를 포함한 입력 경로")
    parser.add_argument("--checkpoint-root", default=str(DEFAULT_CHECKPOINT_ROOT), help="체크포인트 저장 경로")
    parser.add_argument("--until", help="재생 종료일 (YYYY-MM-DD)")
    parser.add_argument("--engine", choices=["glicko2", "trueskill"], default="trueskill")
    parser.add_argument("--rating-period", choices=["meet", "month"], default="meet")
    parser.add_argument("--tau", type=float, default=25.0 / 300.0)
    parser.add_argument("--convergence-tolerance", type=float, default=1e-4)
    parser.add_argument("--ep-max-iterations", type=int, default=10)
    parser.add_argument("--bench", action="store_true", help="콜드 리플레이 성능을 측정합니다")
    parser.add_argument("--out", default="out/replay_bench.md", help="--bench 측정 보고서 경로")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    until = date.fromisoformat(args.until) if args.until else None
    params = ReplayParams(
        engine_name=args.engine,
        rating_period=args.rating_period,
        tau=float(args.tau),
        convergence_tolerance=float(args.convergence_tolerance),
        ep_max_iterations=int(args.ep_max_iterations),
    )
    ledger_path = Path(args.ledger).expanduser()
    checkpoint_root = Path(args.checkpoint_root).expanduser()
    if args.bench:
        result = benchmark(
            ledger_path,
            params,
            report_path=Path(args.out).expanduser(),
        )
        print(f"[ok] benchmark={args.out}")
        print(f"[ok] elapsed_seconds={result.replay.elapsed_seconds:.3f}")
        return
    result = replay(ledger_path, params, until=until, checkpoint_root=checkpoint_root)
    print(f"[ok] races={result.race_count:,}")
    print(f"[ok] periods={result.period_count:,}")
    print(f"[ok] resumed_from={result.resumed_from.cid if result.resumed_from else '-'}")
    print(f"[ok] state_digest={result.state_digest()}")


if __name__ == "__main__":
    main()
