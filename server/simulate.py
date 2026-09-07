from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class AthleteRef:
    opaque_id: str


@dataclass(frozen=True)
class ExplicitRating:
    athlete_id: str
    mu: float
    sigma: float


@dataclass(frozen=True)
class HeatSpec:
    athletes: Sequence[AthleteRef | ExplicitRating]
    advance_count: int
    penalty_rate: float | None
    seed: int


@dataclass(frozen=True)
class SimBudget:
    min_iterations: int = 2_000
    max_iterations: int = 50_000
    target_ci_width: float = 0.02
    max_seconds: float = 1.0


@dataclass(frozen=True)
class AdvanceEstimate:
    athlete_id: str
    advance_prob: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class HeatResult:
    probabilities: tuple[AdvanceEstimate, ...]
    iterations: int
    converged: bool


def simulate_heat(spec: HeatSpec, budget: SimBudget, *, beta: float) -> HeatResult:
    """Estimate advancement by independently sampling performance and penalties."""

    ratings = _normalized_ratings(spec)
    _validate_budget(budget)
    _validate_beta(beta)
    penalty_rate = _validated_penalty_rate(spec.penalty_rate)

    rng = random.Random(spec.seed)
    wins = [0] * len(ratings)
    standard_deviations = [math.hypot(sigma, beta) for _, _, sigma in ratings]
    deadline = time.monotonic() + budget.max_seconds
    iterations = 0
    converged = False

    while iterations < budget.max_iterations:
        if iterations and iterations % 64 == 0 and time.monotonic() >= deadline:
            break
        ranked: list[tuple[float, str, int]] = []
        for index, ((athlete_id, mu, _sigma), standard_deviation) in enumerate(zip(ratings, standard_deviations)):
            if rng.random() < penalty_rate:
                continue
            ranked.append((rng.gauss(mu, standard_deviation), athlete_id, index))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        for _score, _athlete_id, index in ranked[: spec.advance_count]:
            wins[index] += 1
        iterations += 1

        if iterations >= budget.min_iterations and _all_ci_widths_within(wins, iterations, budget.target_ci_width):
            converged = True
            break

    estimates = tuple(
        AdvanceEstimate(
            athlete_id=athlete_id,
            advance_prob=win_count / iterations,
            ci_low=interval[0],
            ci_high=interval[1],
        )
        for (athlete_id, _mu, _sigma), win_count, interval in (
            (rating, win_count, wilson_interval(win_count, iterations))
            for rating, win_count in zip(ratings, wins)
        )
    )
    return HeatResult(probabilities=estimates, iterations=iterations, converged=converged)


def simulation_cache_key(spec: HeatSpec, *, beta: float, run_id: str, model_version: str = "heat-v1") -> str:
    """Build an order-independent key whose rounded inputs match cached simulation slots."""

    ratings = _normalized_ratings(spec)
    payload = {
        "ratings": sorted((round(mu, 1), round(sigma, 1)) for _athlete_id, mu, sigma in ratings),
        "advance_count": spec.advance_count,
        "penalty_rate": round(_validated_penalty_rate(spec.penalty_rate), 6),
        "beta": round(beta, 6),
        "run_id": run_id,
        "seed": spec.seed,
        "model_version": model_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def wilson_interval(successes: int, trials: int, *, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials < 1:
        raise ValueError("trials must be positive")
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between zero and trials")
    proportion = successes / trials
    denominator = 1.0 + (z * z / trials)
    center = (proportion + (z * z / (2.0 * trials))) / denominator
    half_width = (z / denominator) * math.sqrt(
        (proportion * (1.0 - proportion) / trials) + (z * z / (4.0 * trials * trials))
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def _all_ci_widths_within(wins: list[int], iterations: int, target_width: float) -> bool:
    return all((high - low) <= target_width for low, high in (wilson_interval(win_count, iterations) for win_count in wins))


def _normalized_ratings(spec: HeatSpec) -> list[tuple[str, float, float]]:
    if len(spec.athletes) < 2:
        raise ValueError("at least two athletes are required")
    if not isinstance(spec.advance_count, int) or not 1 <= spec.advance_count < len(spec.athletes):
        raise ValueError("advance_count must be between one and the athlete count minus one")
    normalized: list[tuple[str, float, float]] = []
    for athlete in spec.athletes:
        if isinstance(athlete, AthleteRef):
            raise ValueError("AthleteRef must be resolved to ExplicitRating before simulation")
        athlete_id = athlete.athlete_id.strip()
        if not athlete_id:
            raise ValueError("athlete_id must not be empty")
        if not math.isfinite(athlete.mu) or not math.isfinite(athlete.sigma) or athlete.sigma < 0:
            raise ValueError("mu must be finite and sigma must be finite and non-negative")
        normalized.append((athlete_id, float(athlete.mu), float(athlete.sigma)))
    identifiers = [athlete_id for athlete_id, _mu, _sigma in normalized]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("athlete identifiers must be unique")
    return sorted(normalized, key=lambda rating: rating[0])


def _validated_penalty_rate(penalty_rate: float | None) -> float:
    if penalty_rate is None:
        raise ValueError("penalty_rate must be supplied after resolving the default")
    if not math.isfinite(penalty_rate) or not 0.0 <= penalty_rate <= 1.0:
        raise ValueError("penalty_rate must be finite and in [0, 1]")
    return float(penalty_rate)


def _validate_budget(budget: SimBudget) -> None:
    if budget.min_iterations < 1 or budget.max_iterations < budget.min_iterations:
        raise ValueError("iteration budget is invalid")
    if not 0.0 < budget.target_ci_width <= 1.0:
        raise ValueError("target_ci_width must be in (0, 1]")
    if not math.isfinite(budget.max_seconds) or budget.max_seconds <= 0.0:
        raise ValueError("max_seconds must be positive and finite")


def _validate_beta(beta: float) -> None:
    if not math.isfinite(beta) or beta <= 0.0:
        raise ValueError("beta must be positive and finite")


_ROUND_ORDER = {"heat": 0, "quarterfinal": 1, "semifinal": 2, "final_b": 3, "final": 4}


def _advance_labels_for_meet(meet_races: Sequence[object]) -> dict[str, tuple[int, dict[str, int]]]:
    """Recover observable advancement from later rounds in the same event division."""

    labels: dict[str, tuple[int, dict[str, int]]] = {}
    for race in meet_races:
        round_class = str(getattr(race, "round_class"))
        if round_class != "heat":
            continue
        participants = tuple(getattr(race, "participants"))
        participant_ids = {str(getattr(participant, "athlete_id")) for participant in participants}
        later_ids: set[str] = set()
        for candidate in meet_races:
            if _ROUND_ORDER.get(str(getattr(candidate, "round_class")), -1) <= _ROUND_ORDER["heat"]:
                continue
            if (
                getattr(candidate, "event") != getattr(race, "event")
                or getattr(candidate, "division_text") != getattr(race, "division_text")
                or getattr(candidate, "gender") != getattr(race, "gender")
                or getattr(candidate, "grade_text") != getattr(race, "grade_text")
            ):
                continue
            later_ids.update(str(getattr(participant, "athlete_id")) for participant in getattr(candidate, "participants"))
        advance_count = len(participant_ids.intersection(later_ids))
        if not 1 <= advance_count < len(participants):
            continue
        labels[str(getattr(race, "race_id"))] = (
            advance_count,
            {athlete_id: int(athlete_id in later_ids) for athlete_id in participant_ids},
        )
    return labels


def run_holdout_calibration(
    *,
    ledger_path: Path,
    registry_root: Path,
    holdout_seasons: int,
    iterations: int,
    output_path: Path,
    penalty_results_path: Path | None = None,
) -> None:
    """Evaluate raw heat advancement probabilities without using holdout results as ratings."""

    from rating.calibration import Calibrator
    from rating.eval.backtest import _build_model, _build_schedule, _select_holdout_seasons, _to_races
    from rating.eval.metrics import compute_metrics, write_calibration_svg
    from rating.ledger.extract import estimate_penalty_rate
    from rating.ledger.schema import load_race_ledger, validate_ledger

    from .deps import load_pinned_run

    if iterations < 100:
        raise ValueError("iterations must be at least 100")
    ledger = load_race_ledger(ledger_path)
    validate_ledger(ledger)
    pinned_run = load_pinned_run(registry_root)
    beta = _run_beta(pinned_run.engine_params)
    tau = _run_positive_float(pinned_run.engine_params, "tau")
    initial_sigma = _run_positive_float(pinned_run.engine_params, "initial_sigma")
    pairwise_calibrator = Calibrator.from_dict(pinned_run.calibrator_spec)
    races = _to_races(ledger)
    holdout_set = set(_select_holdout_seasons(races, holdout_seasons))
    model = _build_model(
        "trueskill",
        "meet",
        tau=tau,
        beta=beta,
        trueskill_initial_sigma=initial_sigma,
    )
    if penalty_results_path is not None and penalty_results_path.is_file():
        penalty_rate = estimate_penalty_rate(penalty_results_path)
        penalty_source = f"R-02 results ({penalty_results_path.as_posix()})"
    else:
        penalty_rate = ledger.filter(ledger["status"] == "PEN").height / ledger.height
        penalty_source = f"ledger fallback ({ledger_path.as_posix()})"
    budget = SimBudget(
        min_iterations=iterations,
        max_iterations=iterations,
        target_ci_width=0.0001,
        max_seconds=2.0,
    )
    raw_actuals: list[int] = []
    raw_probabilities: list[float] = []
    transferred_probabilities: list[float] = []
    skipped_heats = 0
    for step in _build_schedule(races, races, "meet"):
        for meet_races in step.eval_meets:
            labels_by_race = _advance_labels_for_meet(meet_races)
            for race in meet_races:
                if race.season_year not in holdout_set or race.race_id not in labels_by_race:
                    continue
                advance_count, labels = labels_by_race[race.race_id]
                ratings = [
                    (
                        participant.athlete_id,
                        model.filtered_rating_as_of(participant.athlete_id, race.race_date),
                    )
                    for participant in race.participants
                ]
                if len(ratings) < 2:
                    skipped_heats += 1
                    continue
                seed = int.from_bytes(
                    hashlib.sha256(f"{pinned_run.run_id}|{race.race_id}".encode("utf-8")).digest()[:8],
                    byteorder="big",
                )
                result = simulate_heat(
                    HeatSpec(
                        athletes=[
                            ExplicitRating(athlete_id=athlete_id, mu=rating.mu, sigma=rating.sigma)
                            for athlete_id, rating in ratings
                        ],
                        advance_count=advance_count,
                        penalty_rate=penalty_rate,
                        seed=seed,
                    ),
                    budget,
                    beta=beta,
                )
                for estimate in result.probabilities:
                    raw_actuals.append(labels[estimate.athlete_id])
                    raw_probabilities.append(estimate.advance_prob)
                    transferred_probabilities.append(pairwise_calibrator.apply(estimate.advance_prob))
        model.update(step.train_races)

    if not raw_actuals:
        raise ValueError("No holdout heat has an observable later-round advancement label.")
    raw_metrics = compute_metrics(raw_actuals, raw_probabilities)
    transferred_metrics = compute_metrics(raw_actuals, transferred_probabilities)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path = output_path.with_suffix(".svg")
    write_calibration_svg(svg_path, raw_metrics.calibration, "Heat advancement calibration (raw)")
    lines = [
        "# Heat simulation calibration report (R-14)",
        "",
        f"- run_id: `{pinned_run.run_id}`",
        f"- holdout seasons: {', '.join(str(value) for value in sorted(holdout_set))}",
        f"- observable heat-athlete labels: **{len(raw_actuals):,}**",
        f"- skipped heats without an observable later round: **{skipped_heats:,}**",
        f"- Monte Carlo iterations per heat: **{iterations:,}**",
        f"- penalty rate source: `{penalty_source}`",
        f"- penalty rate: **{penalty_rate:.3%}**",
        "",
        "## Holdout results",
        "",
        "| probability path | log loss | Brier | ECE |",
        "| --- | ---: | ---: | ---: |",
        f"| raw heat simulation | {raw_metrics.log_loss:.5f} | {raw_metrics.brier:.5f} | {raw_metrics.calibration.ece:.5f} |",
        f"| pairwise Platt transfer (reference only) | {transferred_metrics.log_loss:.5f} | {transferred_metrics.brier:.5f} | {transferred_metrics.calibration.ece:.5f} |",
        "",
        "## Decision",
        "",
        "- The pairwise Platt calibrator is not applied to heat advancement probabilities.",
        "- Applying an independent binary transform to each athlete does not preserve the heat's fixed number of advancement slots.",
        "- The API therefore returns raw Monte Carlo advancement probabilities until a separately fitted, constraint-preserving heat calibrator is validated.",
        "",
        f"Raw calibration curve: `{svg_path.as_posix()}`",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_beta(params: dict[str, object]) -> float:
    return _run_positive_float(params, "beta")


def _run_positive_float(params: dict[str, object], key: str) -> float:
    raw = params.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"Published run is missing a numeric {key}.")
    value = float(raw)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"Published run has an invalid {key}.")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="R-14 heat simulation evaluation")
    parser.add_argument("--calibrate", action="store_true", help="run the heat advancement calibration evaluation")
    parser.add_argument("--holdout", action="store_true", help="evaluate only held-out recent seasons")
    parser.add_argument("--ledger", default="out/ledger", help="race ledger directory or parquet file")
    parser.add_argument("--registry-root", default="out/rating_runs", help="published rating registry root")
    parser.add_argument("--holdout-seasons", type=int, default=2, help="number of most recent seasons to hold out")
    parser.add_argument("--iterations", type=int, default=2_000, help="Monte Carlo iterations per historical heat")
    parser.add_argument(
        "--penalty-results",
        default="data/records_full.csv",
        help="R-02 source results used to estimate the default penalty rate",
    )
    parser.add_argument("--out", default="out/sim_calibration.md", help="Markdown report path")
    args = parser.parse_args()
    if not args.calibrate or not args.holdout:
        parser.error("--calibrate and --holdout are both required")
    run_holdout_calibration(
        ledger_path=Path(args.ledger).expanduser(),
        registry_root=Path(args.registry_root).expanduser(),
        holdout_seasons=args.holdout_seasons,
        iterations=args.iterations,
        output_path=Path(args.out).expanduser(),
        penalty_results_path=Path(args.penalty_results).expanduser(),
    )
    print(f"[ok] sim_calibration={args.out}")


if __name__ == "__main__":
    main()
