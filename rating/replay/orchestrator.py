from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import pstats
import re
import time
import tomllib
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from rating.engine.glicko2 import Glicko2Engine, Glicko2Params, Rating
from rating.engine.runner import group_periods, ledger_digest, run_replay, to_race_results
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
from .registry import DEFAULT_REGISTRY_ROOT, RatingRegistry
from .snapshot import input_snapshot_id, run_id as content_run_id
from .version import ALGORITHM_VERSION

_DEFAULT_ALGORITHM_VERSION = ALGORITHM_VERSION


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
    run_id: str
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
    checkpoint_input_hash: str | None = None,
    included_race_ids: frozenset[str] | None = None,
) -> ReplayResult:
    started = time.perf_counter()
    race_ledger = load_race_ledger(ledger_path)
    validate_ledger(race_ledger)
    all_target_races = to_race_results(race_ledger)
    if not all_target_races:
        raise ValueError(f"[error] 평가 가능한 race가 없습니다: {ledger_path}")
    if until is not None:
        all_target_races = [race for race in all_target_races if race.race_date <= until]
    if not all_target_races:
        raise ValueError("[error] 요청한 종료일 이전에 평가 가능한 race가 없습니다.")
    target_date = max(race.race_date for race in all_target_races)
    input_hash = ledger_digest(ledger_path)
    snapshot_id = input_snapshot_id(ledger_path)
    resolved_params_hash = params_digest(params.fingerprint())
    resolved_checkpoint_input_hash = checkpoint_input_hash or input_hash
    engine_params = params.fingerprint()
    engine_params.pop("algorithm_version")
    resolved_run_id = content_run_id(
        algo_version=params.algorithm_version,
        engine_params=engine_params,
        calibrator_spec={"method": "unfitted"},
        input_id=snapshot_id,
    )
    checkpoint = from_checkpoint or find_nearest(
        target_date,
        params.algorithm_version,
        resolved_params_hash,
        resolved_checkpoint_input_hash,
        root=checkpoint_root,
    )
    state: dict[str, Rating] = {}
    if checkpoint is not None:
        _validate_checkpoint(
            checkpoint,
            target_date=target_date,
            params=params,
            params_hash=resolved_params_hash,
            input_hash=resolved_checkpoint_input_hash,
        )
        restored = load(checkpoint.cid, root=checkpoint_root, expected=checkpoint)
        if restored is None:
            raise CheckpointError(f"[error] 선택한 checkpoint 상태를 찾을 수 없습니다: {checkpoint.cid}")
        state = restored
        all_target_races = [race for race in all_target_races if race.race_date > checkpoint.cutoff_date]
    races = (
        [race for race in all_target_races if race.race_id in included_race_ids]
        if included_race_ids is not None
        else all_target_races
    )
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
        if included_race_ids is None and is_season_end and season_is_complete:
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
        run_id=resolved_run_id,
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
    parser.add_argument("--params", help="엔진 및 보정기 설정 TOML 파일")
    parser.add_argument("--until", help="재생 종료일 (YYYY-MM-DD)")
    parser.add_argument("--engine", choices=["glicko2", "trueskill"])
    parser.add_argument("--rating-period", choices=["meet", "month"])
    parser.add_argument("--tau", type=float)
    parser.add_argument("--convergence-tolerance", type=float)
    parser.add_argument("--ep-max-iterations", type=int)
    parser.add_argument("--bench", action="store_true", help="콜드 리플레이 성능을 측정합니다")
    parser.add_argument("--register", action="store_true", help="콘텐츠 주소 실행으로 등록하고 완료 후 공개합니다")
    parser.add_argument("--registry-root", default=str(DEFAULT_REGISTRY_ROOT), help="실행 레지스트리 루트")
    parser.add_argument("--out", default="out/replay_bench.md", help="--bench 측정 보고서 경로")
    return parser


def _load_engine_config(path: str | None) -> dict[str, object]:
    if path is None:
        return {}
    with Path(path).expanduser().open("rb") as handle:
        payload = tomllib.load(handle)
    engine = payload.get("engine")
    if not isinstance(engine, dict):
        raise ValueError("[error] params TOML에 [engine] 테이블이 필요합니다.")
    return dict(engine)


def main() -> None:
    args = build_parser().parse_args()
    config = _load_engine_config(args.params)
    engine_name = args.engine or str(config.get("name", "trueskill"))
    rating_period = args.rating_period or str(config.get("rating_period", "meet"))
    tau = float(args.tau if args.tau is not None else config.get("tau", 25.0 / 300.0))
    convergence_tolerance = float(
        args.convergence_tolerance if args.convergence_tolerance is not None else config.get("convergence_tolerance", 1e-4)
    )
    ep_max_iterations = int(
        args.ep_max_iterations if args.ep_max_iterations is not None else config.get("ep_max_iterations", 10)
    )
    if engine_name not in {"glicko2", "trueskill"}:
        raise ValueError(f"[error] 지원하지 않는 엔진입니다: {engine_name}")
    if rating_period not in {"meet", "month"}:
        raise ValueError(f"[error] 지원하지 않는 period입니다: {rating_period}")
    if args.register and args.bench:
        raise ValueError("[error] --register와 --bench는 함께 사용할 수 없습니다.")
    until = date.fromisoformat(args.until) if args.until else None
    params = ReplayParams(
        engine_name=engine_name,
        rating_period=rating_period,
        tau=tau,
        convergence_tolerance=convergence_tolerance,
        ep_max_iterations=ep_max_iterations,
    )
    ledger_path = Path(args.ledger).expanduser()
    checkpoint_root = Path(args.checkpoint_root).expanduser()
    if args.register:
        if engine_name == "trueskill":
            engine_params = {
                "engine": engine_name,
                "tau": tau,
                "initial_mu": float(config.get("initial_mu", 25.0)),
                "initial_sigma": float(config.get("initial_sigma", 25.0 / 3.0)),
                "beta": float(config.get("beta", 25.0 / 6.0)),
                "draw_probability": float(config.get("draw_probability", 0.0)),
                "rating_period": rating_period,
                "convergence_tolerance": convergence_tolerance,
                "ep_max_iterations": ep_max_iterations,
                "pairwise_size_weight": True,
            }
        else:
            engine_params = {
                "engine": engine_name,
                "tau": tau,
                "initial_mu": 1500.0,
                "initial_phi": 350.0,
                "initial_sigma": 0.06,
                "rating_period": rating_period,
                "pairwise_size_weight": True,
            }
        registry = RatingRegistry(Path(args.registry_root).expanduser())
        reusable = registry.find_reusable(
            algo_version=params.algorithm_version,
            engine_params=engine_params,
            input_snapshot_id=input_snapshot_id(ledger_path),
        )
        if reusable is not None:
            registry.publish(reusable.run_id)
            print(f"[ok] run_id={reusable.run_id}")
            print("[ok] reused=complete")
            return
        result = run_replay(
            ledger_path=ledger_path,
            output_path=Path(args.registry_root).expanduser() / "unused.parquet",
            report_path=Path(args.registry_root).expanduser() / "unused.md",
            engine_name=engine_name,
            rating_period=rating_period,
            tau=tau,
            algorithm_version=params.algorithm_version,
            registry_root=Path(args.registry_root).expanduser(),
            trueskill_initial_mu=float(config.get("initial_mu", 25.0)),
            trueskill_initial_sigma=float(config.get("initial_sigma", 25.0 / 3.0)),
            beta=float(config.get("beta", 25.0 / 6.0)),
            draw_probability=float(config.get("draw_probability", 0.0)),
            convergence_tolerance=convergence_tolerance,
            ep_max_iterations=ep_max_iterations,
        )
        print(f"[ok] run_id={result.run_id}")
        print(f"[ok] registry={Path(args.registry_root).expanduser()}")
        return
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
    print(f"[ok] run_id={result.run_id}")


if __name__ == "__main__":
    main()
