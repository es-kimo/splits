from __future__ import annotations

import argparse
import math
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
    fit_logistic_scale,
)
from .invariants import LN2, assert_harness_invariants
from .metrics import (
    BootstrapInterval,
    CalibrationNull,
    MetricSummary,
    PlattScaler,
    bootstrap_log_loss_ci,
    calibration_null,
    clamp_probability,
    compute_metrics,
    fit_platt_scaler,
    write_calibration_svg,
)

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
    baseline_scales: "BaselineScales"
    holdout_comparison_count: int
    total_comparison_count: int
    engine_tau: float
    engine_tau_scores: dict[float, float]
    scaler: PlattScaler
    raw_metrics: Metrics
    calibration_null: CalibrationNull
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
        """P(left > right) — 방향은 example이 결과와 무관하게 고정합니다."""
        return float(self.predictor.predict_prob(example.left_id, example.right_id, example.race_date))

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
                    "probability": float(predictor.predict_prob(example.left_id, example.right_id, example.race_date)),
                    "actual": example.label,
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


# tau는 비활동/시간 경과에 따라 불확실성을 얼마나 되돌릴지 정하는 파라미터입니다.
# 너무 작으면 sigma/phi가 무너져 확률이 극단으로 몰립니다. 두 엔진의 기본값이
# 서로 다른 스케일이라, 각자 자기 격자에서 학습 구간 log loss로 고릅니다.
TAU_GRID: dict[str, tuple[float, ...]] = {
    "glicko2": (0.2, 0.35, 0.5, 0.8, 1.2),
    "trueskill": (25.0 / 300.0, 0.25, 0.5, 1.0, 2.0),
}


def _build_model(engine: EngineChoice, rating_period: RatingPeriod, tau: float | None = None) -> ModelAdapter:
    if engine == "glicko2":
        params = Glicko2Params(rating_period=rating_period) if tau is None else Glicko2Params(rating_period=rating_period, tau=tau)
        return ModelAdapter(name="glicko2", predictor=Glicko2Engine(params=params), state={}, initial_phi=350.0)
    from rating.engine.trueskill_wrapper import TrueSkillEngine, TrueSkillParams

    predictor: Predictor = TrueSkillEngine() if tau is None else TrueSkillEngine(params=TrueSkillParams(tau=tau))
    return ModelAdapter(name="trueskill", predictor=predictor, state={}, initial_phi=25.0 / 3.0)


def _fit_engine_tau(
    engine: EngineChoice,
    rating_period: RatingPeriod,
    steps: Sequence[ScheduleStep],
    holdout_set: set[int],
    previous_season: int,
) -> tuple[float, dict[float, float]]:
    """마지막 학습 시즌을 검증 구간으로 써서 tau를 고릅니다.

    두 엔진을 각자의 최선 설정으로 붙이기 위한 단계입니다. 한쪽만 기본값으로
    두고 비교하면 "어느 알고리즘이 나은가"라는 질문에 답할 수 없습니다.
    홀드아웃은 여기서 전혀 쓰지 않습니다.
    """
    scores: dict[float, float] = {}
    for tau in TAU_GRID[engine]:
        model = _build_model(engine, rating_period, tau=tau)
        loss_sum = 0.0
        count = 0
        for step in steps:
            if any(race.season_year in holdout_set for race in step.train_races):
                continue
            for meet_races in step.eval_meets:
                if any(race.season_year in holdout_set for race in meet_races):
                    continue
                if not any(race.season_year == previous_season for race in meet_races):
                    continue
                for example in build_pairwise_examples(meet_races):
                    probability = clamp_probability(model.predict(example))
                    loss_sum -= math.log(probability) if example.label == 1 else math.log(1.0 - probability)
                    count += 1
            model.update(step.train_races)
        scores[tau] = (loss_sum / count) if count else float("inf")

    best_tau = min(scores, key=lambda key: scores[key])
    return best_tau, scores


def _config_key(policy: str, rating_period: RatingPeriod, engine: EngineChoice) -> str:
    return f"{policy}|{rating_period}|{engine}"


EVALUATION_POLICY = "conservative"


@dataclass(frozen=True)
class ScheduleStep:
    """한 rating period 안에서 일어나는 일.

    모델은 period 경계에서 한 번 갱신되지만, 베이스라인은 대회(meet) 단위로
    전진합니다. 베이스라인은 "학부모가 이미 아는 정보"를 나타내므로 모델의
    rating period 선택에 따라 정보량이 달라지면 안 됩니다.
    """

    period_key: str
    eval_meets: tuple[tuple[RaceObservation, ...], ...]
    train_races: tuple[RaceObservation, ...]


def _build_schedule(
    train_races: Sequence[RaceObservation],
    eval_races: Sequence[RaceObservation],
    rating_period: RatingPeriod,
) -> list[ScheduleStep]:
    train_by_period: dict[str, list[RaceObservation]] = {}
    for race in train_races:
        train_by_period.setdefault(_period_key(race, rating_period), []).append(race)

    eval_by_period: dict[str, dict[tuple[date, str], list[RaceObservation]]] = {}
    for race in eval_races:
        period = eval_by_period.setdefault(_period_key(race, rating_period), {})
        period.setdefault((race.race_date, race.meet_id), []).append(race)

    steps: list[ScheduleStep] = []
    for key in sorted(set(train_by_period) | set(eval_by_period)):
        meets = eval_by_period.get(key, {})
        steps.append(
            ScheduleStep(
                period_key=key,
                eval_meets=tuple(tuple(meets[meet_key]) for meet_key in sorted(meets)),
                train_races=tuple(train_by_period.get(key, ())),
            )
        )
    return steps


def _make_baselines(
    *, head2head_prob: float, previous_season: int, eval_races: Sequence[RaceObservation], scales: "BaselineScales"
) -> list[BaselinePredictor]:
    return [
        ConstantBaseline(),
        HeadToHeadBaseline(fixed_probability=head2head_prob),
        PreviousSeasonBestTimeBaseline(season_year=previous_season, races=eval_races, scale=scales.b2),
        LastMeetPercentileBaseline(scale=scales.b3),
    ]


@dataclass(frozen=True)
class BaselineScales:
    b2: float
    b3: float
    b2_sample: int
    b3_sample: int


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    observed: str


@dataclass(frozen=True)
class Verdict:
    label: str
    gates: tuple[Gate, ...]

    @property
    def blocking(self) -> tuple[str, ...]:
        return tuple(f"{gate.name} (관측 {gate.observed})" for gate in self.gates if not gate.passed)

    @property
    def adr_status(self) -> str:
        return "Accepted" if self.label == "GO" else "Proposed"


def decide(model: Metrics, improvement: float) -> Verdict:
    """판정 규칙의 유일한 구현. 리포트와 ADR이 같은 결론을 쓰게 합니다."""
    gates = (
        Gate("개선율 >= 5%", improvement >= 0.05, f"{improvement:.2%}"),
        Gate("ECE <= 0.03", model.ece <= 0.03, f"{model.ece:.5f}"),
        Gate("70% 과신 없음", not model.overconfidence_70, "Y" if model.overconfidence_70 else "N"),
    )
    if all(gate.passed for gate in gates):
        label = "GO"
    elif improvement >= 0.01:
        label = "조건부"
    else:
        label = "STOP"
    return Verdict(label=label, gates=gates)


def _best_row(results: Sequence[ConfigResult]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for result in results:
        model = result.metrics_by_predictor[result.engine]
        b3 = result.metrics_by_predictor["B3"]
        improvement = (b3.log_loss - model.log_loss) / b3.log_loss if b3.log_loss > 0 else 0.0
        rows.append({"result": result, "model": model, "b3": b3, "improvement": improvement})
    rows.sort(key=lambda item: item["model"].log_loss)
    return rows[0]


def _fit_baseline_scales(
    steps: Sequence[ScheduleStep],
    eval_races: Sequence[RaceObservation],
    holdout_set: set[int],
    previous_season: int,
    *,
    head2head_prob: float,
) -> BaselineScales:
    """B2/B3의 로지스틱 스케일을 홀드아웃 **이전** 구간에서만 적합합니다.

    베이스라인은 넘어야 하는 기준이므로 최대한 유리하게 세워야 합니다. 스케일을
    상수로 박아두면 확률이 포화해 동전 던지기보다 나쁜 기준선이 되고, 그러면
    개선율이라는 숫자 자체가 의미를 잃습니다.
    """
    del head2head_prob
    # B2는 고정된 한 시즌의 최고기록을 참조하므로, 적합용 인스턴스는 참조 시즌을
    # 한 시즌 앞으로 당겨 적합 구간이 참조 시즌보다 뒤에 오도록 만듭니다.
    b2_fit = PreviousSeasonBestTimeBaseline(season_year=previous_season - 1, races=eval_races)
    b3_fit = LastMeetPercentileBaseline()

    b2_deltas: list[float] = []
    b2_labels: list[int] = []
    b3_deltas: list[float] = []
    b3_labels: list[int] = []

    for step in steps:
        for meet_races in step.eval_meets:
            if any(race.season_year in holdout_set for race in meet_races):
                continue
            in_b2_window = any(race.season_year == previous_season for race in meet_races)
            for example in build_pairwise_examples(meet_races):
                if in_b2_window:
                    gap = b2_fit.delta(example)
                    if gap is not None:
                        b2_deltas.append(example.orient_delta(gap))
                        b2_labels.append(example.label)
                gap = b3_fit.delta(example)
                if gap is not None:
                    b3_deltas.append(example.orient_delta(gap))
                    b3_labels.append(example.label)
            b3_fit.update(meet_races)

    b2_scale = (
        fit_logistic_scale(b2_deltas, b2_labels)
        if b2_deltas
        else float(PreviousSeasonBestTimeBaseline.default_scale)
    )
    b3_scale = fit_logistic_scale(b3_deltas, b3_labels) if b3_deltas else float(LastMeetPercentileBaseline.default_scale)
    return BaselineScales(b2=b2_scale, b3=b3_scale, b2_sample=len(b2_labels), b3_sample=len(b3_labels))


def _fit_calibrator(
    model: ModelAdapter,
    steps: Sequence[ScheduleStep],
    holdout_set: set[int],
    previous_season: int,
) -> PlattScaler:
    """마지막 학습 시즌에서 사후 보정기를 적합합니다.

    모델을 처음부터 다시 재생하며 보정 시즌의 (예측, 실제)를 모읍니다. 예측은
    항상 갱신보다 먼저 일어나므로 보정 구간에도 누수가 없고, 홀드아웃은 전혀
    건드리지 않습니다. 반환된 보정기는 두 엔진에 동일하게 적용됩니다.
    """
    probabilities: list[float] = []
    labels: list[int] = []
    for step in steps:
        if any(race.season_year in holdout_set for race in step.train_races):
            continue
        for meet_races in step.eval_meets:
            if any(race.season_year in holdout_set for race in meet_races):
                continue
            if any(race.season_year == previous_season for race in meet_races):
                for example in build_pairwise_examples(meet_races):
                    probabilities.append(model.predict(example))
                    labels.append(example.label)
        model.update(step.train_races)
    return fit_platt_scaler(probabilities, labels)


def _evaluate_config(
    *,
    policy: str,
    ledger_path: Path,
    eval_ledger_path: Path,
    engine: EngineChoice,
    rating_period: RatingPeriod,
    holdout_season_count: int,
    head2head_prob: float,
    calibration_dir: Path,
) -> ConfigResult:
    """정책은 학습 데이터 구성에만 적용하고, 평가셋은 전 설정에서 고정합니다.

    정책을 평가셋에도 적용하면 설정마다 다른 시험지를 푸는 셈이 됩니다.
    aggressive는 DNF가 섞인 더 어려운 문제를, place_only는 결승만 남긴 다른
    문제를 풀게 되어 로그 손실을 나란히 놓고 비교할 수 없습니다.
    """
    eval_frame = load_race_ledger(eval_ledger_path)
    validate_ledger(eval_frame)
    eval_races = _to_races(eval_frame)
    if not eval_races:
        raise ValueError(f"[error] 평가 가능한 race가 없습니다: {eval_ledger_path}")

    if ledger_path == eval_ledger_path:
        train_races = eval_races
    else:
        train_frame = load_race_ledger(ledger_path)
        validate_ledger(train_frame)
        train_races = _to_races(train_frame)
        if not train_races:
            raise ValueError(f"[error] 학습 가능한 race가 없습니다: {ledger_path}")

    # 홀드아웃 시즌은 평가셋 기준으로 정해 전 설정이 같은 구간을 씁니다.
    holdout_seasons = _select_holdout_seasons(eval_races, holdout_season_count)
    holdout_set = set(holdout_seasons)
    previous_season = min(holdout_seasons) - 1
    steps = _build_schedule(train_races, eval_races, rating_period)

    scales = _fit_baseline_scales(
        steps, eval_races, holdout_set, previous_season, head2head_prob=head2head_prob
    )
    tau, tau_scores = _fit_engine_tau(engine, rating_period, steps, holdout_set, previous_season)

    # 보정기는 홀드아웃 이전 구간에서 적합하고, 두 엔진에 동일하게 적용합니다.
    scaler = _fit_calibrator(_build_model(engine, rating_period, tau=tau), steps, holdout_set, previous_season)

    model = _build_model(engine, rating_period, tau=tau)
    baselines = _make_baselines(
        head2head_prob=head2head_prob,
        previous_season=previous_season,
        eval_races=eval_races,
        scales=scales,
    )

    rows: list[dict[str, Any]] = []
    comparison_id = 0
    holdout_comparisons = 0
    total_comparisons = 0
    config = _config_key(policy, rating_period, engine)

    for step in steps:
        for meet_races in step.eval_meets:
            examples = build_pairwise_examples(meet_races, start_id=comparison_id)
            total_comparisons += len(examples)
            in_holdout = any(race.season_year in holdout_set for race in meet_races)
            if in_holdout:
                holdout_comparisons += len(examples)
                for example in examples:
                    phi, n_games = model.pair_uncertainty(example)
                    raw_probability = float(model.predict(example))
                    rows.append(
                        {
                            "config": config,
                            "predictor": model.name,
                            "comparison_id": example.comparison_id,
                            "race_id": example.race_id,
                            "actual": example.label,
                            "probability": scaler.apply(raw_probability),
                            "raw_probability": raw_probability,
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
                        prediction = baseline.predict(example)
                        rows.append(
                            {
                                "config": config,
                                "predictor": baseline.name,
                                "comparison_id": example.comparison_id,
                                "race_id": example.race_id,
                                "actual": example.label,
                                # 베이스라인은 P(winner > loser)를 내므로 예제 방향으로 되돌립니다.
                                "probability": example.orient(prediction.probability),
                                "raw_probability": example.orient(prediction.probability),
                                "covered": bool(prediction.covered),
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
            # 베이스라인은 대회 단위로 전진합니다(모델의 rating period와 무관).
            for baseline in baselines:
                baseline.update(meet_races)
        model.update(step.train_races)

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
    raw_summary = compute_metrics(
        actuals=model_metrics.predictions["actual"].to_list(),
        probabilities=model_metrics.predictions["raw_probability"].to_list(),
        covered=model_metrics.predictions["covered"].to_list(),
    )
    raw_metrics = _to_metrics(raw_summary, model_metrics.predictions)
    null = calibration_null(model_metrics.predictions["probability"].to_list())
    calibration_path = calibration_dir / f"{policy}-{rating_period}-{engine}.svg"
    write_calibration_svg(
        calibration_path,
        model_metrics_to_summary(model_metrics).calibration,
        title=f"{policy}/{rating_period}/{engine} calibration",
    )
    result = ConfigResult(
        policy=policy,
        rating_period=rating_period,
        engine=engine,
        holdout_seasons=holdout_seasons,
        baseline_scales=scales,
        holdout_comparison_count=holdout_comparisons,
        total_comparison_count=total_comparisons,
        engine_tau=tau,
        engine_tau_scores=tau_scores,
        scaler=scaler,
        raw_metrics=raw_metrics,
        calibration_null=null,
        metrics_by_predictor=metrics_by_predictor,
        common_subset_metrics=common_subset_metrics,
        calibration_path=calibration_path,
        comparison_count=len(common_ids),
    )
    assert_harness_invariants(result)
    return result


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


_CI_CACHE: dict[int, BootstrapInterval] = {}


def _log_loss_ci(result: ConfigResult, *, resamples: int = 1000) -> BootstrapInterval:
    cached = _CI_CACHE.get(id(result))
    if cached is not None:
        return cached
    predictions = result.metrics_by_predictor[result.engine].predictions
    interval = bootstrap_log_loss_ci(
        predictions["actual"].to_list(),
        predictions["probability"].to_list(),
        predictions["race_id"].to_list(),
        resamples=resamples,
    )
    _CI_CACHE[id(result)] = interval
    return interval


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
    verdict = decide(best["model"], best["improvement"])

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
            "## 로그손실 95% 신뢰구간 (레이스 단위 블록 부트스트랩)",
            "",
            "같은 레이스의 비교들은 독립이 아니므로 레이스를 통째로 리샘플링합니다.",
            "구간이 겹치면 두 설정의 차이를 노이즈와 구분할 수 없습니다.",
            "",
            "| policy | period | engine | log_loss | CI 하한 | CI 상한 | 최적 설정과 겹침 |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    best_ci = _log_loss_ci(best["result"])
    for row in model_rows:
        result = row["result"]
        interval = _log_loss_ci(result)
        is_best = result is best["result"]
        overlap = "(최적)" if is_best else ("Y" if interval.overlaps(best_ci) else "N")
        lines.append(
            f"| {result.policy} | {result.rating_period} | {result.engine} | {interval.point:.5f} | "
            f"{interval.low:.5f} | {interval.high:.5f} | {overlap} |"
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
            "베이스라인 로지스틱 스케일은 홀드아웃 이전 구간에서 log loss 최소화로 적합했습니다.",
            "",
            "| policy | period | B2 scale | B2 적합표본 | B3 scale | B3 적합표본 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in results:
        if result.engine != "glicko2":
            continue
        scales = result.baseline_scales
        lines.append(
            f"| {result.policy} | {result.rating_period} | {scales.b2:.5f} | {scales.b2_sample:,} | {scales.b3:.5f} | {scales.b3_sample:,} |"
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

    lines.extend(
        [
            "",
            "## 사후 보정 (Platt scaling)",
            "",
            "캘리브레이션은 사후 보정으로 고칠 수 있지만 판별력은 어떤 후처리로도 못 늘립니다.",
            "보정 전 비교는 고칠 수 있는 약점과 못 고치는 약점을 같은 무게로 재게 되므로,",
            "두 엔진에 동일한 보정을 적용한 뒤 비교합니다. 보정기는 홀드아웃 직전 시즌에서 적합했습니다.",
            "단조 변환이라 정확도는 보정 전후가 같습니다.",
            "",
            "| policy | period | engine | slope | intercept | log_loss 보정전 | 보정후 | ECE 보정전 | 보정후 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in model_rows:
        result = row["result"]
        raw = result.raw_metrics
        model = row["model"]
        lines.append(
            f"| {result.policy} | {result.rating_period} | {result.engine} | {result.scaler.slope:.4f} | "
            f"{result.scaler.intercept:+.4f} | {raw.log_loss:.5f} | {model.log_loss:.5f} | "
            f"{raw.ece:.5f} | {model.ece:.5f} |"
        )

    lines.extend(
        [
            "",
            "## ECE 유한표본 귀무분포",
            "",
            "ECE는 유한표본에서 위로 편향됩니다. 완전히 캘리브레이션된 예측기도 0이 나오지 않으므로,",
            "관측 ECE가 노이즈 바닥 위인지 확인해야 게이트를 해석할 수 있습니다.",
            "예측 확률은 그대로 두고 라벨만 그 확률에서 뽑아 귀무분포를 만들었습니다.",
            "",
            "| policy | period | engine | 관측 ECE | 귀무 p50 | 귀무 p95 | 귀무 p99 | 노이즈 초과 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in model_rows:
        result = row["result"]
        null = result.calibration_null
        observed = row["model"].ece
        lines.append(
            f"| {result.policy} | {result.rating_period} | {result.engine} | {observed:.5f} | "
            f"{null.p50:.5f} | {null.p95:.5f} | {null.p99:.5f} | {'Y' if observed > null.p95 else 'N'} |"
        )

    lines.extend(
        [
            "",
            "## 예측 확률 분포와 불확실성",
            "",
            "확률이 극단으로 몰리면(판별력은 있는데 스케일이 깨진 상태) 여기서 먼저 드러납니다.",
            "tau는 홀드아웃 이전 구간에서 log loss로 골랐습니다.",
            "",
            "| policy | period | engine | tau | p 표준편차 | p<0.1 또는 >0.9 | 불확실성 p50 | 불확실성 p10 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in model_rows:
        result = row["result"]
        predictions = row["model"].predictions
        probabilities = predictions["probability"].to_list()
        extreme = sum(1 for p in probabilities if p < 0.1 or p > 0.9) / max(len(probabilities), 1)
        phis = sorted(value for value in predictions["pair_phi"].to_list() if value is not None)
        p50 = phis[len(phis) // 2] if phis else 0.0
        p10 = phis[int(len(phis) * 0.10)] if phis else 0.0
        spread = float(pl.Series(probabilities).std() or 0.0)
        lines.append(
            f"| {result.policy} | {result.rating_period} | {result.engine} | {result.engine_tau:.4f} | "
            f"{spread:.4f} | {extreme:.1%} | {p50:.3f} | {p10:.3f} |"
        )

    lines.extend(["", "## 캘리브레이션 플롯", ""])
    report_dir = report_path.parent
    for result in results:
        rel = result.calibration_path.relative_to(report_dir) if result.calibration_path.is_relative_to(report_dir) else result.calibration_path
        lines.append(f"- `{result.policy}/{result.rating_period}/{result.engine}`: ![]({rel.as_posix()})")

    lines.extend(["", _render_segment_section(best["result"]), "", "## GO/STOP 판정", ""])
    best_result: ConfigResult = best["result"]
    lines.append(f"- best_config: `{best_result.policy}/{best_result.rating_period}/{best_result.engine}`")
    lines.append(f"- best_log_loss: **{best['model'].log_loss:.5f}**")
    lines.append(f"- B3_log_loss: **{best['b3'].log_loss:.5f}**")
    lines.append(f"- improvement_vs_B3: **{best['improvement'] * 100:.2f}%**")
    lines.append(
        f"- holdout 비율: **{best_result.holdout_comparison_count:,} / {best_result.total_comparison_count:,}** "
        f"({best_result.holdout_comparison_count / max(best_result.total_comparison_count, 1):.1%})"
    )
    lines.append(f"- verdict: **{verdict.label}**")
    lines.extend(["", "| 조건 | 관측값 | 통과 |", "| --- | ---: | --- |"])
    for gate in verdict.gates:
        lines.append(f"| {gate.name} | {gate.observed} | {'Y' if gate.passed else 'N'} |")
    if verdict.blocking:
        lines.extend(["", f"GO를 막은 조건: {', '.join(verdict.blocking)}"])
    return "\n".join(lines) + "\n"


def _write_adr(results: Sequence[ConfigResult], path: Path) -> None:
    best = _best_row(results)
    best_result: ConfigResult = best["result"]
    best_model: Metrics = best["model"]
    best_b3: Metrics = best["b3"]
    best_improvement: float = best["improvement"]
    verdict = decide(best_model, best_improvement)
    metrics = best_result.metrics_by_predictor
    holdout_ratio = best_result.holdout_comparison_count / max(best_result.total_comparison_count, 1)

    lines = [
        "# ADR 0006 — 백테스트 판정 재실행 (R-05)",
        "",
        # GO가 아닌 판정을 Accepted로 적으면, 무엇이 막혔는지가 기록에서 사라집니다.
        f"- 상태: {verdict.adr_status}",
        f"- 작성시각: {datetime.now().isoformat(timespec='seconds')}",
        "- 선행: `docs/adr/0005-backtest-verdict.md` (Superseded)",
        "",
        "## 문맥",
        "",
        "- R-05 요구에 따라 정책 3종 × rating period 2종 × 엔진 2종(총 12설정)을 동일 하네스에서 비교했습니다.",
        "- 홀드아웃은 마지막 2시즌이며, 예측 시점 이전 정보만 사용하도록 period 단위 선예측 후갱신 순서를 강제했습니다.",
        "- 비교 방향은 결과와 무관한 해시로 고정하고, 베이스라인 로지스틱 스케일은 홀드아웃 이전 구간에서 적합했습니다.",
        f"- 정책은 학습 데이터 구성에만 적용하고, 평가셋은 `{EVALUATION_POLICY}` 홀드아웃으로 전 설정 고정했습니다.",
        "- 두 엔진에 동일한 사후 보정(Platt)을 적용한 뒤 비교했습니다. 캘리브레이션은 고칠 수 있고 판별력은 못 고치기 때문입니다.",
        "",
        "## 최적 설정 관측값",
        "",
        f"- best_config: **{best_result.policy}/{best_result.rating_period}/{best_result.engine}**",
        f"- model log loss: **{best_model.log_loss:.5f}** (accuracy {best_model.accuracy:.4f}, brier {best_model.brier:.5f})",
        f"- improvement vs B3: **{best_improvement * 100:.2f}%**",
        f"- ECE: **{best_model.ece:.5f}**",
        f"- overconfidence@70: **{'Y' if best_model.overconfidence_70 else 'N'}** (n={best_model.overconfidence_70_count:,})",
        "",
        "### 베이스라인 원값",
        "",
        "베이스라인이 동전 던지기보다 나쁘면 그건 발견이 아니라 구현 결함입니다. 원값을 남깁니다.",
        "",
        "| 베이스라인 | log loss | 동전(ln2=0.69315) 대비 |",
        "| --- | ---: | --- |",
    ]
    for name in ("B0", "B1", "B2", "B3"):
        if name not in metrics:
            continue
        loss = metrics[name].log_loss
        # B0은 정의상 동전이므로 부동소수 반올림으로 열위 표시가 나오면 안 됩니다.
        if abs(loss - LN2) <= 1e-6:
            verdict_text = "동일"
        elif loss > LN2:
            verdict_text = "열위"
        else:
            verdict_text = "우위"
        lines.append(f"| {name} | {loss:.5f} | {verdict_text} |")

    lines.extend(
        [
            "",
            "### 홀드아웃 규모",
            "",
            f"- 홀드아웃 비교: **{best_result.holdout_comparison_count:,}** / 전체 **{best_result.total_comparison_count:,}** ({holdout_ratio:.1%})",
            f"- 홀드아웃 시즌: {', '.join(str(season) for season in best_result.holdout_seasons)}",
            f"- 적합된 베이스라인 스케일: B2={best_result.baseline_scales.b2:.5f}, B3={best_result.baseline_scales.b3:.5f}",
            "",
            "## 판정 규칙 적용",
            "",
            "| 조건 | 관측값 | 통과 |",
            "| --- | ---: | --- |",
        ]
    )
    for gate in verdict.gates:
        lines.append(f"| {gate.name} | {gate.observed} | {'Y' if gate.passed else 'N'} |")

    lines.extend(
        [
            "",
            "| 판정 | 규칙 |",
            "| --- | --- |",
            "| GO | 개선율 >= 5% AND ECE <= 0.03 AND 70% 과신 없음 |",
            "| 조건부 | 1% <= 개선율 < 5%, 또는 개선율은 충분하나 캘리브레이션 게이트 미통과 |",
            "| STOP | 개선율 < 1% 또는 B3와 동등/열위 |",
            "",
            f"최종 판정: **{verdict.label}**",
        ]
    )
    if verdict.blocking:
        lines.extend(["", f"GO를 막은 조건: **{', '.join(verdict.blocking)}**"])

    lines.extend(["", "## 알려진 한계", ""])
    best_ci = _log_loss_ci(best_result)
    overlapping = [
        f"`{other.policy}/{other.rating_period}/{other.engine}`"
        for other in results
        if other is not best_result and _log_loss_ci(other).overlaps(best_ci)
    ]
    if overlapping:
        lines.append(
            f"- 최적 설정의 CI가 다음과 겹칩니다: {', '.join(overlapping)}. "
            "이들 사이의 순위는 이 홀드아웃으로 확정되지 않습니다."
        )
    else:
        lines.append("- 최적 설정의 CI는 다른 모든 설정과 분리됩니다.")

    predictions = best_model.predictions
    newcomers = predictions.filter(pl.col("pair_n_games") <= 5)
    if newcomers.height > 0:
        newcomer_summary = compute_metrics(
            actuals=newcomers["actual"].to_list(),
            probabilities=newcomers["probability"].to_list(),
        )
        lines.append(
            f"- 신인 구간(n_games <= 5, n={newcomer_summary.sample_size:,}): "
            f"log loss {newcomer_summary.log_loss:.5f}, 정확도 {newcomer_summary.accuracy:.4f}. "
            "이력이 없는 선수에게 모집단 평균 사전분포를 주기 때문이며, R-06 연령 모델이 다뤄야 할 지점입니다."
        )

    tau_values = sorted(best_result.engine_tau_scores.items(), key=lambda item: item[1])
    if len(tau_values) >= 2:
        spread = tau_values[-1][1] - tau_values[0][1]
        lines.append(
            f"- tau 격자 전체의 검증 log loss 폭은 {spread:.5f}입니다. "
            "폭이 좁으면 tau가 사실상 식별되지 않으므로, 선택값을 과신하면 안 됩니다."
        )

    lines.append(
        "- ECE 게이트는 고정 임계값(0.03)이라 표본 크기에 따라 엄격도가 달라집니다. "
        "리포트의 귀무분포 표와 함께 읽어야 합니다."
    )
    lines.append("")
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
    parser.add_argument("--adr-out", default="docs/adr/0006-backtest-verdict-rerun.md", help="ADR 출력 경로")
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

    # 평가셋은 전 설정에서 고정합니다. 정책은 학습 데이터 구성에만 적용됩니다.
    eval_ledger_path = discovered.get(EVALUATION_POLICY)
    if eval_ledger_path is None:
        if len(discovered) != 1:
            raise FileNotFoundError(
                f"[error] 고정 평가셋 정책 '{EVALUATION_POLICY}'의 레저를 찾을 수 없습니다: {ledger_root}"
            )
        eval_ledger_path = next(iter(discovered.values()))

    results: list[ConfigResult] = []
    for policy in policies:
        ledger_path = discovered[policy]
        for period in periods:
            for engine in engines:
                result = _evaluate_config(
                    policy=policy,
                    ledger_path=ledger_path,
                    eval_ledger_path=eval_ledger_path,
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
