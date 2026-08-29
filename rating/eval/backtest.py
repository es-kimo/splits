from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Sequence

import polars as pl

from rating.engine.glicko2 import Glicko2Engine, Glicko2Params
from rating.engine.types import Predictor, RaceEntry, RaceResult, RatingLike, RatingPeriod
from rating.ledger.policies import POLICIES
from rating.ledger.schema import load_race_ledger, validate_ledger
from rating.ledger.season import parse_kst_date

from .baselines import (
    BaselinePredictor,
    ConstantBaseline,
    HeadToHeadBaseline,
    LastMeetPercentileBaseline,
    PairwiseExample,
    PreviousSeasonBestTimeBaseline,
    RaceObservation,
    RaceParticipant,
    build_pairwise_examples,
)
from .metrics import MetricSummary, compute_metrics, write_calibration_svg

EngineChoice = Literal["glicko2", "trueskill"]

_REQUIRED_LEDGER_COLUMNS = {
    "race_ordering_key",
    "race_id",
    "athlete_id",
    "rank",
    "status",
    "race_date",
    "season_year",
    "meet_id",
    "event",
    "round_class",
    "time_sec",
    "weight",
}


@dataclass(frozen=True)
class Metrics:
    sample_size: int
    accuracy: float
    log_loss: float
    brier: float
    coverage: float
    ece: float
    overconfidence_70: bool
    overconfidence_70_count: int
    overconfidence_70_win_rate: float
    overconfidence_70_ci_low: float
    overconfidence_70_ci_high: float
    predictions: pl.DataFrame


@dataclass(frozen=True)
class ConfigResult:
    policy: str
    rating_period: RatingPeriod
    engine: EngineChoice
    holdout_seasons: tuple[int, ...]
    metrics_by_predictor: dict[str, Metrics]
    common_subset_metrics: dict[str, Metrics]
    calibration_path: Path
    comparison_count: int


@dataclass
class ModelAdapter:
    name: str
    predictor: Predictor
    state: dict[str, RatingLike]
    initial_phi: float

    def predict(self, example: PairwiseExample) -> float:
        return float(self.predictor.predict_prob(example.winner_id, example.loser_id, example.race_date))

    def update(self, races: Sequence[RaceObservation]) -> None:
        race_results = [
            RaceResult(
                race_id=race.race_id,
                race_date=race.race_date,
                meet_id=race.meet_id,
                entries=tuple(
                    RaceEntry(
                        athlete_id=participant.athlete_id,
                        rank=participant.rank,
                        status=participant.status,
                        weight=participant.weight,
                    )
                    for participant in race.participants
                ),
            )
            for race in races
        ]
        self.state = self.predictor.update(self.state, race_results)

    def pair_uncertainty(self, example: PairwiseExample) -> tuple[float, int]:
        left = self.state.get(example.winner_id)
        right = self.state.get(example.loser_id)
        left_phi = float(getattr(left, "phi", self.initial_phi))
        right_phi = float(getattr(right, "phi", self.initial_phi))
        left_games = int(getattr(left, "n_games", 0))
        right_games = int(getattr(right, "n_games", 0))
        return max(left_phi, right_phi), min(left_games, right_games)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _ensure_eval_columns(frame: pl.DataFrame) -> pl.DataFrame:
    missing = sorted(_REQUIRED_LEDGER_COLUMNS.difference(frame.columns))
    if missing:
        raise ValueError(f"[error] race_ledger 필수 컬럼이 없습니다: {', '.join(missing)}")
    out = frame
    if "grade_text" not in out.columns:
        out = out.with_columns(pl.lit("").alias("grade_text"))
    if "gender" not in out.columns:
        out = out.with_columns(pl.lit("").alias("gender"))
    return out


def _parse_race_date(raw: Any) -> date:
    text = _norm(raw)
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    parsed = parse_kst_date(text)
    if parsed is None:
        raise ValueError(f"[error] race_date 파싱 실패: {raw}")
    return parsed


def _to_races(frame: pl.DataFrame) -> list[RaceObservation]:
    normalized = _ensure_eval_columns(frame)
    rows = normalized.sort(["race_ordering_key", "rank", "athlete_id"], nulls_last=True).to_dicts()
    races: list[RaceObservation] = []
    cursor = 0
    while cursor < len(rows):
        race_key = _norm(rows[cursor].get("race_ordering_key"))
        chunk: list[dict[str, Any]] = []
        while cursor < len(rows) and _norm(rows[cursor].get("race_ordering_key")) == race_key:
            chunk.append(rows[cursor])
            cursor += 1
        if len(chunk) < 2:
            continue
        first = chunk[0]
        race_id = _norm(first.get("race_id"))
        if not race_id:
            continue
        race_date = _parse_race_date(first.get("race_date"))
        meet_id = _norm(first.get("meet_id")) or "-"
        season_year = _to_int(first.get("season_year"))
        participants: list[RaceParticipant] = []
        for row in chunk:
            athlete_id = _norm(row.get("athlete_id"))
            if not athlete_id:
                continue
            participants.append(
                RaceParticipant(
                    athlete_id=athlete_id,
                    rank=_to_int(row.get("rank")),
                    status=_norm(row.get("status")),
                    time_sec=_to_float(row.get("time_sec")),
                    weight=float(_to_float(row.get("weight")) or 1.0),
                )
            )
        if len(participants) < 2:
            continue
        races.append(
            RaceObservation(
                race_id=race_id,
                race_date=race_date,
                meet_id=meet_id,
                season_year=season_year,
                event=_norm(first.get("event")) or "(unknown-event)",
                round_class=_norm(first.get("round_class")) or "other",
                grade_text=_norm(first.get("grade_text")) or "(unknown-grade)",
                gender=_norm(first.get("gender")) or "(unknown-gender)",
                participants=tuple(participants),
            )
        )
    return races


def _period_key(race: RaceObservation, rating_period: RatingPeriod) -> str:
    if rating_period == "month":
        return f"{race.race_date.year:04d}-{race.race_date.month:02d}"
    return f"{race.race_date.isoformat()}|{race.meet_id}"


def _group_periods(races: Sequence[RaceObservation], rating_period: RatingPeriod) -> list[list[RaceObservation]]:
    grouped: dict[str, list[RaceObservation]] = {}
    for race in races:
        key = _period_key(race, rating_period)
        grouped.setdefault(key, []).append(race)
    return list(grouped.values())


def _select_holdout_seasons(races: Sequence[RaceObservation], holdout_seasons: int) -> tuple[int, ...]:
    seasons = sorted({race.season_year for race in races if race.season_year > 0})
    if len(seasons) < holdout_seasons:
        raise ValueError(f"[error] 홀드아웃 시즌 수가 부족합니다: available={len(seasons)}, requested={holdout_seasons}")
    return tuple(seasons[-holdout_seasons:])


def _to_metrics(summary: MetricSummary, predictions: pl.DataFrame) -> Metrics:
    return Metrics(
        sample_size=summary.sample_size,
        accuracy=summary.accuracy,
        log_loss=summary.log_loss,
        brier=summary.brier,
        coverage=summary.coverage,
        ece=summary.calibration.ece,
        overconfidence_70=summary.calibration.overconfidence_70,
        overconfidence_70_count=summary.calibration.overconfidence_70_count,
        overconfidence_70_win_rate=summary.calibration.overconfidence_70_win_rate,
        overconfidence_70_ci_low=summary.calibration.overconfidence_70_ci_low,
        overconfidence_70_ci_high=summary.calibration.overconfidence_70_ci_high,
        predictions=predictions,
    )


def evaluate(predictor: Predictor, holdout: pl.DataFrame, *, rating_period: RatingPeriod = "meet") -> Metrics:
    races = _to_races(holdout)
    periods = _group_periods(races, rating_period)
    state: dict[str, RatingLike] = {}
    rows: list[dict[str, Any]] = []
    comparison_id = 0
    for period_races in periods:
        examples = build_pairwise_examples(period_races, start_id=comparison_id)
        for example in examples:
            rows.append(
                {
                    "comparison_id": int(example.comparison_id),
                    "race_id": example.race_id,
                    "probability": float(predictor.predict_prob(example.winner_id, example.loser_id, example.race_date)),
                    "actual": 1,
                    "covered": True,
                }
            )
        if examples:
            comparison_id = int(examples[-1].comparison_id) + 1
        race_results = [
            RaceResult(
                race_id=race.race_id,
                race_date=race.race_date,
                meet_id=race.meet_id,
                entries=tuple(
                    RaceEntry(
                        athlete_id=participant.athlete_id,
                        rank=participant.rank,
                        status=participant.status,
                        weight=participant.weight,
                    )
                    for participant in race.participants
                ),
            )
            for race in period_races
        ]
        state = predictor.update(state, race_results)
    predictions = pl.DataFrame(rows) if rows else pl.DataFrame(schema={"comparison_id": pl.Int64, "race_id": pl.Utf8, "probability": pl.Float64, "actual": pl.Int64, "covered": pl.Boolean})
    summary = compute_metrics(
        actuals=predictions["actual"].to_list() if predictions.height > 0 else [],
        probabilities=predictions["probability"].to_list() if predictions.height > 0 else [],
        covered=predictions["covered"].to_list() if predictions.height > 0 else [],
    )
    return _to_metrics(summary, predictions)


def _build_model(engine: EngineChoice, rating_period: RatingPeriod) -> ModelAdapter:
    if engine == "glicko2":
        predictor: Predictor = Glicko2Engine(params=Glicko2Params(rating_period=rating_period))
        return ModelAdapter(name="glicko2", predictor=predictor, state={}, initial_phi=350.0)
    from rating.engine.trueskill_wrapper import TrueSkillEngine

    predictor = TrueSkillEngine()
    return ModelAdapter(name="trueskill", predictor=predictor, state={}, initial_phi=25.0 / 3.0)


def _config_key(policy: str, rating_period: RatingPeriod, engine: EngineChoice) -> str:
    return f"{policy}|{rating_period}|{engine}"


def _evaluate_config(
    *,
    policy: str,
    ledger_path: Path,
    engine: EngineChoice,
    rating_period: RatingPeriod,
    holdout_season_count: int,
    head2head_prob: float,
    calibration_dir: Path,
) -> ConfigResult:
    frame = load_race_ledger(ledger_path)
    validate_ledger(frame)
    races = _to_races(frame)
    if not races:
        raise ValueError(f"[error] 평가 가능한 race가 없습니다: {ledger_path}")
    holdout_seasons = _select_holdout_seasons(races, holdout_season_count)
    holdout_set = set(holdout_seasons)
    previous_season = min(holdout_seasons) - 1
    periods = _group_periods(races, rating_period)

    model = _build_model(engine, rating_period)
    baselines: list[BaselinePredictor] = [
        ConstantBaseline(),
        HeadToHeadBaseline(fixed_probability=head2head_prob),
        PreviousSeasonBestTimeBaseline(season_year=previous_season, races=races),
        LastMeetPercentileBaseline(),
    ]

    rows: list[dict[str, Any]] = []
    comparison_id = 0
    for period_races in periods:
        in_holdout = any(race.season_year in holdout_set for race in period_races)
        examples = build_pairwise_examples(period_races, start_id=comparison_id)
        if in_holdout:
            for example in examples:
                phi, n_games = model.pair_uncertainty(example)
                model_prob = model.predict(example)
                rows.append(
                    {
                        "config": _config_key(policy, rating_period, engine),
                        "predictor": model.name,
                        "comparison_id": example.comparison_id,
                        "race_id": example.race_id,
                        "actual": 1,
                        "probability": float(model_prob),
                        "covered": True,
                        "round_class": example.round_class,
                        "grade_text": example.grade_text,
                        "event": example.event,
                        "source_status": example.source_status,
                        "pair_phi": float(phi),
                        "pair_n_games": int(n_games),
                    }
                )
                for baseline in baselines:
                    baseline_pred = baseline.predict(example)
                    rows.append(
                        {
                            "config": _config_key(policy, rating_period, engine),
                            "predictor": baseline.name,
                            "comparison_id": example.comparison_id,
                            "race_id": example.race_id,
                            "actual": 1,
                            "probability": float(baseline_pred.probability),
                            "covered": bool(baseline_pred.covered),
                            "round_class": example.round_class,
                            "grade_text": example.grade_text,
                            "event": example.event,
                            "source_status": example.source_status,
                            "pair_phi": None,
                            "pair_n_games": None,
                        }
                    )
        if examples:
            comparison_id = int(examples[-1].comparison_id) + 1
        model.update(period_races)
        for baseline in baselines:
            baseline.update(period_races)

    predictions = pl.DataFrame(rows)
    metrics_by_predictor: dict[str, Metrics] = {}
    for predictor in sorted(predictions["predictor"].unique().to_list()):
        frame_pred = predictions.filter(pl.col("predictor") == predictor).sort("comparison_id")
        summary = compute_metrics(
            actuals=frame_pred["actual"].to_list(),
            probabilities=frame_pred["probability"].to_list(),
            covered=frame_pred["covered"].to_list(),
        )
        metrics_by_predictor[predictor] = _to_metrics(summary, frame_pred)

    covered_b1 = set(
        predictions.filter((pl.col("predictor") == "B1") & (pl.col("covered") == True)).select("comparison_id").to_series().to_list()
    )
    covered_b2 = set(
        predictions.filter((pl.col("predictor") == "B2") & (pl.col("covered") == True)).select("comparison_id").to_series().to_list()
    )
    common_ids = covered_b1.intersection(covered_b2)
    common_subset_metrics: dict[str, Metrics] = {}
    for predictor in sorted(predictions["predictor"].unique().to_list()):
        subset = predictions.filter((pl.col("predictor") == predictor) & (pl.col("comparison_id").is_in(common_ids))).sort("comparison_id")
        summary = compute_metrics(
            actuals=subset["actual"].to_list(),
            probabilities=subset["probability"].to_list(),
            covered=subset["covered"].to_list(),
        )
        common_subset_metrics[predictor] = _to_metrics(summary, subset)

    model_metrics = metrics_by_predictor[model.name]
    model_summary = model_metrics_to_summary(model_metrics)
    calibration_path = calibration_dir / f"{policy}-{rating_period}-{engine}.svg"
    write_calibration_svg(
        calibration_path,
        model_summary.calibration,
        title=f"{policy}/{rating_period}/{engine} calibration",
    )
    return ConfigResult(
        policy=policy,
        rating_period=rating_period,
        engine=engine,
        holdout_seasons=holdout_seasons,
        metrics_by_predictor=metrics_by_predictor,
        common_subset_metrics=common_subset_metrics,
        calibration_path=calibration_path,
        comparison_count=len(common_ids),
    )


def model_metrics_to_summary(metrics: Metrics) -> MetricSummary:
    # Recompute from stored predictions to keep report generation deterministic.
    return compute_metrics(
        actuals=metrics.predictions["actual"].to_list(),
        probabilities=metrics.predictions["probability"].to_list(),
        covered=metrics.predictions["covered"].to_list(),
    )


def _segment_band_n_games(value: Any) -> str:
    games = _to_int(value)
    if games <= 5:
        return "0-5"
    if games <= 20:
        return "6-20"
    return "21+"


def _segment_band_phi(value: Any, q1: float, q2: float) -> str:
    phi = float(value or 0.0)
    if phi <= q1:
        return f"low(<= {q1:.1f})"
    if phi <= q2:
        return f"mid({q1:.1f}~{q2:.1f})"
    return f"high(> {q2:.1f})"


def _segment_rows(frame: pl.DataFrame, column: str, max_rows: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counts = frame.group_by(column).len().sort("len", descending=True)
    for bucket in counts.select(column).to_series().to_list()[:max_rows]:
        sub = frame.filter(pl.col(column) == bucket)
        summary = compute_metrics(
            actuals=sub["actual"].to_list(),
            probabilities=sub["probability"].to_list(),
            covered=sub["covered"].to_list(),
        )
        rows.append(
            {
                "bucket": _norm(bucket) or "(blank)",
                "n": summary.sample_size,
                "log_loss": summary.log_loss,
                "accuracy": summary.accuracy,
                "brier": summary.brier,
            }
        )
    return rows


def _render_segment_section(best_result: ConfigResult) -> str:
    model_name = best_result.engine
    model_rows = best_result.metrics_by_predictor[model_name].predictions
    phi_values = [float(value) for value in model_rows["pair_phi"].to_list() if value is not None]
    q1 = sorted(phi_values)[int((len(phi_values) - 1) * 0.33)] if phi_values else 0.0
    q2 = sorted(phi_values)[int((len(phi_values) - 1) * 0.66)] if phi_values else 0.0

    segmented = model_rows.with_columns(
        [
            pl.col("pair_n_games").map_elements(_segment_band_n_games, return_dtype=pl.Utf8).alias("n_games_band"),
            pl.col("pair_phi").map_elements(lambda value: _segment_band_phi(value, q1, q2), return_dtype=pl.Utf8).alias("phi_band"),
        ]
    )

    axes = [
        ("n_games", "n_games_band"),
        ("phi", "phi_band"),
        ("round", "round_class"),
        ("grade", "grade_text"),
        ("event", "event"),
        ("source_status", "source_status"),
    ]
    lines = ["## 세그먼트 분해 (best config)", ""]
    for axis_name, column in axes:
        lines.extend([f"### {axis_name}", "", "| bucket | n | log_loss | accuracy | brier |", "| --- | ---: | ---: | ---: | ---: |"])
        for row in _segment_rows(segmented, column):
            lines.append(
                f"| {row['bucket']} | {row['n']:,} | {row['log_loss']:.5f} | {row['accuracy']:.4f} | {row['brier']:.5f} |"
            )
        lines.append("")
    return "\n".join(lines)


def _render_report(results: Sequence[ConfigResult], report_path: Path) -> str:
    if not results:
        raise ValueError("[error] 백테스트 결과가 없습니다.")
    holdout_seasons = sorted(set(season for result in results for season in result.holdout_seasons))

    model_rows = []
    for result in results:
        model = result.metrics_by_predictor[result.engine]
        b3 = result.metrics_by_predictor["B3"]
        improvement = 0.0
        if b3.log_loss > 0:
            improvement = (b3.log_loss - model.log_loss) / b3.log_loss
        model_rows.append(
            {
                "result": result,
                "model": model,
                "b3": b3,
                "improvement": improvement,
            }
        )
    model_rows.sort(key=lambda item: item["model"].log_loss)
    best = model_rows[0]

    if best["improvement"] >= 0.05 and best["model"].ece <= 0.03 and not best["model"].overconfidence_70:
        verdict = "GO"
    elif best["improvement"] >= 0.01:
        verdict = "조건부"
    else:
        verdict = "STOP"

    lines = [
        "# R-05 Backtest Report",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- holdout_seasons: {', '.join(str(season) for season in holdout_seasons)}",
        f"- configs: {len(results)}",
        "",
        "## 모델 설정 요약",
        "",
        "| policy | period | engine | n | log_loss | accuracy | brier | ece | B3 대비 개선율 | 70% 과신 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in model_rows:
        result: ConfigResult = row["result"]
        model: Metrics = row["model"]
        lines.append(
            f"| {result.policy} | {result.rating_period} | {result.engine} | {model.sample_size:,} | {model.log_loss:.5f} | {model.accuracy:.4f} | {model.brier:.5f} | {model.ece:.5f} | {row['improvement'] * 100:.2f}% | {'Y' if model.overconfidence_70 else 'N'} |"
        )

    lines.extend(
        [
            "",
            "## 12설정 × 4베이스라인 로그손실",
            "",
            "| policy | period | engine | B0 | B1 | B2 | B3 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in results:
        lines.append(
            f"| {result.policy} | {result.rating_period} | {result.engine} | {result.metrics_by_predictor['B0'].log_loss:.5f} | {result.metrics_by_predictor['B1'].log_loss:.5f} | {result.metrics_by_predictor['B2'].log_loss:.5f} | {result.metrics_by_predictor['B3'].log_loss:.5f} |"
        )

    lines.extend(
        [
            "",
            "## 공통 부분집합 비교 (B1/B2 both-covered)",
            "",
            "| policy | period | engine | subset_n | model | B0 | B1 | B2 | B3 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in results:
        common = result.common_subset_metrics
        lines.append(
            f"| {result.policy} | {result.rating_period} | {result.engine} | {result.comparison_count:,} | {common[result.engine].log_loss:.5f} | {common['B0'].log_loss:.5f} | {common['B1'].log_loss:.5f} | {common['B2'].log_loss:.5f} | {common['B3'].log_loss:.5f} |"
        )

    lines.extend(["", "## 캘리브레이션 플롯", ""])
    report_dir = report_path.parent
    for result in results:
        rel = result.calibration_path.relative_to(report_dir) if result.calibration_path.is_relative_to(report_dir) else result.calibration_path
        lines.append(f"- `{result.policy}/{result.rating_period}/{result.engine}`: ![]({rel.as_posix()})")

    lines.extend(["", _render_segment_section(best["result"]), "", "## GO/STOP 판정", ""])
    lines.append(f"- best_config: `{best['result'].policy}/{best['result'].rating_period}/{best['result'].engine}`")
    lines.append(f"- best_log_loss: **{best['model'].log_loss:.5f}**")
    lines.append(f"- B3_log_loss: **{best['b3'].log_loss:.5f}**")
    lines.append(f"- improvement_vs_B3: **{best['improvement'] * 100:.2f}%**")
    lines.append(f"- verdict: **{verdict}**")
    return "\n".join(lines) + "\n"


def _write_adr(results: Sequence[ConfigResult], path: Path) -> None:
    model_rows = []
    for result in results:
        model = result.metrics_by_predictor[result.engine]
        b3 = result.metrics_by_predictor["B3"]
        improvement = (b3.log_loss - model.log_loss) / b3.log_loss if b3.log_loss > 0 else 0.0
        model_rows.append((result, model, b3, improvement))
    model_rows.sort(key=lambda row: row[1].log_loss)
    best_result, best_model, best_b3, best_improvement = model_rows[0]

    if best_improvement >= 0.05 and best_model.ece <= 0.03 and not best_model.overconfidence_70:
        verdict = "GO"
    elif best_improvement >= 0.01:
        verdict = "조건부"
    else:
        verdict = "STOP"

    lines = [
        "# ADR 0005 — 백테스트 판정 (R-05)",
        "",
        "- 상태: Accepted",
        f"- 작성시각: {datetime.now().isoformat(timespec='seconds')}",
        "- 선행: `docs/adr/0004-glicko2-baseline.md`",
        "",
        "## 문맥",
        "",
        "- R-05 요구에 따라 정책 3종 × rating period 2종 × 엔진 2종(총 12설정)을 동일 하네스에서 비교했습니다.",
        "- 홀드아웃은 마지막 2시즌이며, 예측 시점 이전 정보만 사용하도록 period 단위 선예측 후갱신 순서를 강제했습니다.",
        "",
        "## 최적 설정 관측값",
        "",
        f"- best_config: **{best_result.policy}/{best_result.rating_period}/{best_result.engine}**",
        f"- model log loss: **{best_model.log_loss:.5f}**",
        f"- B3 log loss: **{best_b3.log_loss:.5f}**",
        f"- improvement vs B3: **{best_improvement * 100:.2f}%**",
        f"- ECE: **{best_model.ece:.5f}**",
        f"- overconfidence@70: **{'Y' if best_model.overconfidence_70 else 'N'}** (n={best_model.overconfidence_70_count:,})",
        "",
        "## 판정 규칙 적용",
        "",
        "| 조건 | 판정 |",
        "| --- | --- |",
        "| log loss 개선율 >= 5% AND calibration 양호 | GO |",
        "| 1% <= 개선율 < 5% | 조건부 |",
        "| 개선율 < 1% 또는 B3와 동등/열위 | STOP |",
        "",
        f"최종 판정: **{verdict}**",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _discover_policy_ledgers(root: Path) -> dict[str, Path]:
    direct = root / "race_ledger"
    if direct.exists():
        return {"conservative": direct}
    mapped: dict[str, Path] = {}
    for policy in sorted(POLICIES.keys()):
        candidate = root / policy / "race_ledger"
        if candidate.exists():
            mapped[policy] = candidate
    return mapped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-05 백테스트 하네스를 실행합니다.")
    parser.add_argument("--ledger", default="out/ledger", help="레이스 레저 루트 디렉터리")
    parser.add_argument("--holdout-seasons", type=int, default=2, help="홀드아웃 시즌 수")
    parser.add_argument("--all-configs", action="store_true", help="정책×period×엔진 전체 설정 실행")
    parser.add_argument("--policy", default="conservative", choices=sorted(POLICIES.keys()), help="단일 실행 정책")
    parser.add_argument("--rating-period", default="meet", choices=["meet", "month"], help="단일 실행 rating period")
    parser.add_argument("--engine", default="both", choices=["glicko2", "trueskill", "both"], help="단일 실행 엔진")
    parser.add_argument("--head2head-prob", type=float, default=0.65, help="B1 고정 확률")
    parser.add_argument("--out", default="out/backtest_report.md", help="리포트 출력 경로")
    parser.add_argument("--calibration-dir", default="out/backtest_calibration", help="캘리브레이션 SVG 디렉터리")
    parser.add_argument("--adr-out", default="docs/adr/0005-backtest-verdict.md", help="ADR 출력 경로")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    ledger_root = Path(args.ledger).expanduser()
    discovered = _discover_policy_ledgers(ledger_root)
    if not discovered:
        raise FileNotFoundError(f"[error] race_ledger를 찾을 수 없습니다: {ledger_root}")

    if args.all_configs:
        missing = sorted(set(POLICIES.keys()).difference(discovered.keys()))
        if missing:
            joined = ", ".join(missing)
            raise FileNotFoundError(f"[error] --all-configs 실행에는 정책별 레저가 필요합니다. 누락: {joined}")
        policies = sorted(POLICIES.keys())
        periods: list[RatingPeriod] = ["meet", "month"]
        engines: list[EngineChoice] = ["glicko2", "trueskill"]
    else:
        policies = [args.policy]
        periods = [args.rating_period]
        engines = ["glicko2", "trueskill"] if args.engine == "both" else [args.engine]
        if args.policy not in discovered and "conservative" in discovered and len(discovered) == 1:
            discovered[args.policy] = discovered["conservative"]
        if args.policy not in discovered:
            raise FileNotFoundError(f"[error] 정책 레저를 찾을 수 없습니다: {args.policy}")

    calibration_dir = Path(args.calibration_dir).expanduser()
    out_path = Path(args.out).expanduser()
    adr_path = Path(args.adr_out).expanduser()

    results: list[ConfigResult] = []
    for policy in policies:
        ledger_path = discovered[policy]
        for period in periods:
            for engine in engines:
                result = _evaluate_config(
                    policy=policy,
                    ledger_path=ledger_path,
                    engine=engine,
                    rating_period=period,
                    holdout_season_count=int(args.holdout_seasons),
                    head2head_prob=float(args.head2head_prob),
                    calibration_dir=calibration_dir,
                )
                results.append(result)

    report_text = _render_report(results, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_text, encoding="utf-8")
    _write_adr(results, adr_path)

    print(f"[ok] configs={len(results)}")
    print(f"[ok] out={out_path}")
    print(f"[ok] calibration_dir={calibration_dir}")
    print(f"[ok] adr={adr_path}")


if __name__ == "__main__":
    main()
