from __future__ import annotations

import math
from datetime import date
from typing import Callable, Sequence

import polars as pl

from rating.engine.types import Predictor, RaceResult, RatingLike, RatingPeriod

_SMOOTHED_SCHEMA = {
    "athlete_id": pl.Utf8,
    "valid_date": pl.Date,
    "mu": pl.Float64,
    "sigma": pl.Float64,
    "n_games": pl.Int64,
}


def build_smoothed_snapshots(
    races: Sequence[RaceResult],
    filtered_snapshots: pl.DataFrame,
    *,
    rating_period: RatingPeriod,
    predictor_factory: Callable[[], Predictor],
) -> pl.DataFrame:
    """Combine forward states with a reverse replay on a reflected date axis."""

    if not races:
        return pl.DataFrame(schema=_SMOOTHED_SCHEMA)
    reverse_snapshots = _reverse_snapshots(
        races,
        rating_period=rating_period,
        predictor_factory=predictor_factory,
    )
    _validate_snapshots(filtered_snapshots, "필터")
    _validate_snapshots(reverse_snapshots, "역방향")
    forward = filtered_snapshots.select(
        [
            "athlete_id",
            "valid_date",
            pl.col("mu").alias("forward_mu"),
            pl.col("phi").alias("forward_sigma"),
            pl.col("n_games").alias("forward_n_games"),
        ]
    )
    reverse = reverse_snapshots.rename(
        {
            "mu": "reverse_mu",
            "sigma": "reverse_sigma",
            "n_games": "reverse_n_games",
        }
    )
    joined = forward.join(reverse, on=["athlete_id", "valid_date"], how="inner")
    if joined.height != forward.height:
        raise ValueError("[error] 필터와 역방향 스냅샷의 선수·기준일 조합이 일치하지 않습니다.")

    rows: list[dict[str, object]] = []
    for row in joined.to_dicts():
        forward_sigma = float(row["forward_sigma"])
        reverse_sigma = float(row["reverse_sigma"])
        _validate_sigma(forward_sigma, "필터")
        _validate_sigma(reverse_sigma, "역방향")
        forward_precision = 1.0 / (forward_sigma * forward_sigma)
        reverse_precision = 1.0 / (reverse_sigma * reverse_sigma)
        precision = forward_precision + reverse_precision
        rows.append(
            {
                "athlete_id": str(row["athlete_id"]),
                "valid_date": row["valid_date"],
                "mu": (
                    (float(row["forward_mu"]) * forward_precision)
                    + (float(row["reverse_mu"]) * reverse_precision)
                )
                / precision,
                "sigma": math.sqrt(1.0 / precision),
                "n_games": int(row["forward_n_games"]),
            }
        )
    return pl.DataFrame(rows, schema=_SMOOTHED_SCHEMA).sort(["valid_date", "athlete_id"])


def _reverse_snapshots(
    races: Sequence[RaceResult],
    *,
    rating_period: RatingPeriod,
    predictor_factory: Callable[[], Predictor],
) -> pl.DataFrame:
    first_date = min(race.race_date for race in races)
    last_date = max(race.race_date for race in races)
    state: dict[str, RatingLike] = {}
    predictor = predictor_factory()
    rows: list[dict[str, object]] = []
    periods = _group_periods(races, rating_period)

    for valid_date, period_races in reversed(periods):
        reversed_races = tuple(
            _with_reflected_date(race, first_date, last_date) for race in reversed(period_races)
        )
        state = predictor.update(state, reversed_races)
        active_ids = {entry.athlete_id for race in period_races for entry in race.entries}
        for athlete_id in sorted(active_ids):
            rating = state.get(athlete_id)
            if rating is None:
                continue
            rows.append(
                {
                    "athlete_id": athlete_id,
                    "valid_date": valid_date,
                    "mu": float(rating.mu),
                    "sigma": float(rating.phi),
                    "n_games": int(rating.n_games),
                }
            )
    return pl.DataFrame(rows, schema=_SMOOTHED_SCHEMA).sort(["valid_date", "athlete_id"])


def _with_reflected_date(race: RaceResult, first_date: date, last_date: date) -> RaceResult:
    reflected_ordinal = first_date.toordinal() + last_date.toordinal() - race.race_date.toordinal()
    return RaceResult(
        race_id=race.race_id,
        race_date=date.fromordinal(reflected_ordinal),
        meet_id=race.meet_id,
        entries=race.entries,
    )


def _group_periods(
    races: Sequence[RaceResult],
    rating_period: RatingPeriod,
) -> list[tuple[date, list[RaceResult]]]:
    grouped: dict[str, list[RaceResult]] = {}
    valid_dates: dict[str, date] = {}
    for race in races:
        key = (
            f"{race.race_date.year:04d}-{race.race_date.month:02d}"
            if rating_period == "month"
            else f"{race.race_date.isoformat()}|{race.meet_id}"
        )
        grouped.setdefault(key, []).append(race)
        valid_dates[key] = max(valid_dates.get(key, race.race_date), race.race_date)
    return [(valid_dates[key], grouped[key]) for key in grouped]


def _validate_snapshots(snapshots: pl.DataFrame, label: str) -> None:
    required = {"athlete_id", "valid_date", "mu", "n_games"}
    required.add("phi" if label == "필터" else "sigma")
    missing = sorted(required.difference(snapshots.columns))
    if missing:
        raise ValueError(f"[error] {label} 스냅샷 컬럼이 없습니다: {', '.join(missing)}")


def _validate_sigma(value: float, label: str) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"[error] {label} 스냅샷 sigma는 양의 유한값이어야 합니다.")
