from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from rating.calibration import Calibrator, fit as fit_calibrator
from rating.eval.backtest import (
    EVALUATION_POLICY,
    EngineChoice,
    ModelAdapter,
    RatingPeriod,
    ScheduleStep,
    _build_model,
    _build_schedule,
    _discover_policy_ledgers,
    _fit_engine_tau,
    _select_holdout_seasons,
    _to_races,
)
from rating.eval.baselines import RaceObservation, build_pairwise_examples
from rating.eval.metrics import compute_metrics
from rating.ledger.schema import load_race_ledger, validate_ledger


@dataclass(frozen=True)
class HoldoutEvaluation:
    log_loss: float
    ece: float
    sample_size: int
    frame: pl.DataFrame


def _load_schedule(
    *,
    ledger_root: Path,
    policy: str,
    rating_period: RatingPeriod,
    holdout_season_count: int,
    engine: EngineChoice,
) -> tuple[list[ScheduleStep], set[int], int, float, list[RaceObservation]]:
    discovered = _discover_policy_ledgers(ledger_root)
    if not discovered:
        raise FileNotFoundError(f"[error] race_ledger를 찾을 수 없습니다: {ledger_root}")
    if policy not in discovered:
        raise FileNotFoundError(f"[error] 정책 레저를 찾을 수 없습니다: {policy}")
    eval_ledger = discovered.get(EVALUATION_POLICY)
    if eval_ledger is None:
        if len(discovered) != 1:
            raise FileNotFoundError(f"[error] 고정 평가셋 정책 '{EVALUATION_POLICY}'의 레저가 없습니다.")
        eval_ledger = next(iter(discovered.values()))

    train_frame = load_race_ledger(discovered[policy])
    validate_ledger(train_frame)
    eval_frame = load_race_ledger(eval_ledger)
    validate_ledger(eval_frame)
    train_races = _to_races(train_frame)
    eval_races = _to_races(eval_frame)
    holdout_seasons = _select_holdout_seasons(eval_races, holdout_season_count)
    holdout_set = set(holdout_seasons)
    previous_season = min(holdout_seasons) - 1
    steps = _build_schedule(train_races, eval_races, rating_period)
    tau, _scores = _fit_engine_tau(engine, rating_period, steps, holdout_set, previous_season)
    return steps, holdout_set, previous_season, tau, train_races


def _fit_on_season(model: ModelAdapter, steps: list[ScheduleStep], holdout_set: set[int], fit_season: int) -> Calibrator:
    probabilities: list[float] = []
    labels: list[int] = []
    for step in steps:
        if any(race.season_year in holdout_set for race in step.train_races):
            continue
        for meet_races in step.eval_meets:
            if any(race.season_year in holdout_set for race in meet_races):
                continue
            if not any(race.season_year == fit_season for race in meet_races):
                continue
            for example in build_pairwise_examples(meet_races):
                probabilities.append(model.predict_raw(example))
                labels.append(example.label)
        model.update(step.train_races)
    if not probabilities:
        raise ValueError(f"[error] 보정기 적합 시즌({fit_season})에 비교가 없습니다.")
    return fit_calibrator(probabilities, labels, fold_id=f"season={fit_season}")


def _evaluate_holdout(model: ModelAdapter, steps: list[ScheduleStep], holdout_set: set[int], calibrator: Calibrator) -> HoldoutEvaluation:
    rows: list[dict[str, Any]] = []
    for step in steps:
        for meet_races in step.eval_meets:
            in_holdout = any(race.season_year in holdout_set for race in meet_races)
            if not in_holdout:
                continue
            for example in build_pairwise_examples(meet_races):
                raw = model.predict_raw(example)
                diagnostics = model.pair_diagnostics(example)
                rows.append(
                    {
                        "actual": int(example.label),
                        "raw_probability": float(raw),
                        "probability": float(calibrator.apply(raw)),
                        "pair_sigma_max": float(diagnostics["pair_sigma_max"]),
                        "pair_n_games": int(diagnostics["pair_n_games_min"]),
                    }
                )
        model.update(step.train_races)
    frame = pl.DataFrame(rows)
    summary = compute_metrics(
        actuals=frame["actual"].to_list() if frame.height > 0 else [],
        probabilities=frame["probability"].to_list() if frame.height > 0 else [],
    )
    return HoldoutEvaluation(
        log_loss=summary.log_loss,
        ece=summary.calibration.ece,
        sample_size=summary.sample_size,
        frame=frame,
    )


def _segment_table(base: HoldoutEvaluation) -> tuple[list[dict[str, Any]], str]:
    if base.frame.height == 0:
        return [], "N"
    sigmas = sorted(base.frame["pair_sigma_max"].to_list())
    q1 = sigmas[len(sigmas) // 3]
    q2 = sigmas[(len(sigmas) * 2) // 3]

    def sigma_bucket(value: float) -> str:
        if value <= q1:
            return f"low(<= {q1:.3f})"
        if value <= q2:
            return f"mid({q1:.3f}~{q2:.3f})"
        return f"high(> {q2:.3f})"

    rows: list[dict[str, Any]] = []
    split_signal = False
    sigma_labeled = base.frame.with_columns(
        pl.col("pair_sigma_max").map_elements(sigma_bucket, return_dtype=pl.Utf8).alias("bucket")
    )
    for bucket in sigma_labeled["bucket"].unique().to_list():
        sub = sigma_labeled.filter(pl.col("bucket") == bucket)
        labels = sub["actual"].to_list()
        raw_probs = sub["raw_probability"].to_list()
        calibrated = sub["probability"].to_list()
        global_log_loss = compute_metrics(labels, calibrated).log_loss
        global_ece = compute_metrics(labels, calibrated).calibration.ece
        leak_calibrator = fit_calibrator(raw_probs, labels, fold_id=f"holdout-segment:{bucket}")
        leak_probs = [leak_calibrator.apply(value) for value in raw_probs]
        leak_log_loss = compute_metrics(labels, leak_probs).log_loss
        upper_bound_gain = global_log_loss - leak_log_loss
        if len(labels) >= 200 and upper_bound_gain > 0.01:
            split_signal = True
        rows.append(
            {
                "segment": f"sigma/{bucket}",
                "n": len(labels),
                "log_loss(global)": global_log_loss,
                "ece(global)": global_ece,
                "leaky_upper_gain": upper_bound_gain,
            }
        )

    games_labeled = base.frame.with_columns(
        pl.when(pl.col("pair_n_games") <= 5)
        .then(pl.lit("0-5"))
        .when(pl.col("pair_n_games") <= 20)
        .then(pl.lit("6-20"))
        .otherwise(pl.lit("21+"))
        .alias("bucket")
    )
    for bucket in games_labeled["bucket"].unique().to_list():
        sub = games_labeled.filter(pl.col("bucket") == bucket)
        labels = sub["actual"].to_list()
        calibrated = sub["probability"].to_list()
        rows.append(
            {
                "segment": f"n_games/{bucket}",
                "n": len(labels),
                "log_loss(global)": compute_metrics(labels, calibrated).log_loss,
                "ece(global)": compute_metrics(labels, calibrated).calibration.ece,
                "leaky_upper_gain": 0.0,
            }
        )
    rows.sort(key=lambda item: item["segment"])
    return rows, ("Y" if split_signal else "N")


def _render_report(
    *,
    policy: str,
    rating_period: RatingPeriod,
    engine: EngineChoice,
    holdout_set: set[int],
    calibration_season_a: int,
    calibration_season_b: int,
    arm_a: HoldoutEvaluation,
    arm_b: HoldoutEvaluation,
    arm_c_log_loss: float,
    seasonal_rows: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    should_split: str,
) -> str:
    delta = arm_b.log_loss - arm_a.log_loss
    keep_current = delta <= 0.005
    slope_values = [float(row["slope"]) for row in seasonal_rows]
    intercept_values = [float(row["intercept"]) for row in seasonal_rows]
    slope_span = (max(slope_values) - min(slope_values)) if slope_values else 0.0
    intercept_span = (max(intercept_values) - min(intercept_values)) if intercept_values else 0.0
    refit_policy = "실행마다 재적합" if (slope_span > 0.08 or intercept_span > 0.02) else "시즌 경계에서 재적합"

    lines = [
        "# Calibration Protocol Report (R-17)",
        "",
        f"- 작성시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 대상 설정: **{policy}/{rating_period}/{engine}**",
        f"- 홀드아웃 시즌: {', '.join(str(value) for value in sorted(holdout_set))}",
        "",
        "## 1) 적합 폴드 위치",
        "",
        "| arm | 설명 | holdout log loss | holdout ECE |",
        "| --- | --- | ---: | ---: |",
        f"| A (현행) | 직전 학습 시즌 적합 (`season={calibration_season_a}`) | {arm_a.log_loss:.5f} | {arm_a.ece:.5f} |",
        f"| B (전용 폴드) | 한 시즌 앞당긴 전용 적합 (`season={calibration_season_b}`) | {arm_b.log_loss:.5f} | {arm_b.ece:.5f} |",
        f"| C (누수 참조) | 홀드아웃에서 직접 적합 (판정 제외) | {arm_c_log_loss:.5f} | - |",
        "",
        f"- 판정 규칙: |Δ holdout log loss| <= 0.005면 현행 유지",
        f"- 관측값: Δ(B-A) = {delta:+.5f}",
        f"- 결론: **{'현행 유지' if keep_current else '전용 폴드 분리'}**",
        "",
        "## 2) 재적합 주기",
        "",
        "| fit_season | sample | slope | intercept | holdout log loss |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in seasonal_rows:
        lines.append(
            f"| {row['season']} | {row['sample']:,} | {row['slope']:.5f} | {row['intercept']:+.5f} | {row['holdout_log_loss']:.5f} |"
        )
    lines.extend(
        [
            "",
            f"- slope span: {slope_span:.5f}",
            f"- intercept span: {intercept_span:.5f}",
            f"- 결론: **{refit_policy}**",
            "",
            "## 3) 세그먼트 분리 보정",
            "",
            "| segment | n | global log loss | global ECE | segment 분리 이득 상한(누수 참조) |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in segment_rows:
        lines.append(
            f"| {row['segment']} | {row['n']:,} | {row['log_loss(global)']:.5f} | {row['ece(global)']:.5f} | {row['leaky_upper_gain']:.5f} |"
        )
    lines.extend(
        [
            "",
            "- 분리 판정 기준: 표본 n>=200 구간에서 상한 이득이 0.01을 넘는 구간이 있으면 분리 검토",
            f"- 결론: **{'분리 검토 필요' if should_split == 'Y' else '전역 보정 유지'}**",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-17 보정기 적합 프로토콜 리포트를 생성합니다.")
    parser.add_argument("--ledger", default="out/ledger", help="레이스 레저 루트 디렉터리")
    parser.add_argument("--policy", default="conservative", help="학습 정책")
    parser.add_argument("--rating-period", default="meet", choices=["meet", "month"], help="평가 period")
    parser.add_argument("--engine", default="trueskill", choices=["glicko2", "trueskill"], help="엔진")
    parser.add_argument("--holdout-seasons", type=int, default=2, help="홀드아웃 시즌 수")
    parser.add_argument("--out", default="out/calibration_report.md", help="리포트 출력 경로")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    steps, holdout_set, previous_season, tau, train_races = _load_schedule(
        ledger_root=Path(args.ledger).expanduser(),
        policy=args.policy,
        rating_period=args.rating_period,
        holdout_season_count=int(args.holdout_seasons),
        engine=args.engine,
    )

    arm_a_scaler = _fit_on_season(_build_model(args.engine, args.rating_period, tau=tau), steps, holdout_set, previous_season)
    arm_a = _evaluate_holdout(_build_model(args.engine, args.rating_period, tau=tau), steps, holdout_set, arm_a_scaler)

    non_holdout = sorted({race.season_year for race in train_races if race.season_year > 0 and race.season_year not in holdout_set})
    dedicated_season = previous_season
    older = [value for value in non_holdout if value < previous_season]
    if older:
        dedicated_season = older[-1]
    arm_b_scaler = _fit_on_season(_build_model(args.engine, args.rating_period, tau=tau), steps, holdout_set, dedicated_season)
    arm_b = _evaluate_holdout(_build_model(args.engine, args.rating_period, tau=tau), steps, holdout_set, arm_b_scaler)

    leak_scaler = fit_calibrator(
        arm_a.frame["raw_probability"].to_list(),
        arm_a.frame["actual"].to_list(),
        fold_id="holdout(leak-reference)",
    )
    arm_c_probs = [leak_scaler.apply(value) for value in arm_a.frame["raw_probability"].to_list()]
    arm_c_log_loss = compute_metrics(arm_a.frame["actual"].to_list(), arm_c_probs).log_loss

    seasonal_rows: list[dict[str, Any]] = []
    seasonal_candidates = non_holdout[-4:] if len(non_holdout) > 4 else non_holdout
    for season in seasonal_candidates:
        scaler = _fit_on_season(_build_model(args.engine, args.rating_period, tau=tau), steps, holdout_set, season)
        holdout = _evaluate_holdout(_build_model(args.engine, args.rating_period, tau=tau), steps, holdout_set, scaler)
        seasonal_rows.append(
            {
                "season": season,
                "sample": scaler.sample_size,
                "slope": scaler.slope,
                "intercept": scaler.intercept,
                "holdout_log_loss": holdout.log_loss,
            }
        )
    seasonal_rows.sort(key=lambda item: int(item["season"]))

    segment_rows, should_split = _segment_table(arm_a)

    report = _render_report(
        policy=args.policy,
        rating_period=args.rating_period,
        engine=args.engine,
        holdout_set=holdout_set,
        calibration_season_a=previous_season,
        calibration_season_b=dedicated_season,
        arm_a=arm_a,
        arm_b=arm_b,
        arm_c_log_loss=arm_c_log_loss,
        seasonal_rows=seasonal_rows,
        segment_rows=segment_rows,
        should_split=should_split,
    )
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"[ok] out={out_path}")


if __name__ == "__main__":
    main()
