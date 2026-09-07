import math
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from rating.eval.baselines import RaceObservation, RaceParticipant
from rating.ledger.extract import estimate_penalty_rate
from rating.ledger.ordering import make_ordering_key, make_race_ordering_key
from rating.replay.registry import RatingRegistry
from rating.replay.snapshot import run_id
from server.deps import ApiConfig
from server.main import create_app
from server.opaque_ids import sync_active_opaque_ids
from server.cache import ExpiringLruCache
from server.simulate import (
    ExplicitRating,
    HeatSpec,
    SimBudget,
    _advance_labels_for_meet,
    run_holdout_calibration,
    simulate_heat,
    simulation_cache_key,
)


def _spec(*ratings: ExplicitRating, seed: int = 7, penalty_rate: float = 0.0) -> HeatSpec:
    return HeatSpec(athletes=ratings, advance_count=1, penalty_rate=penalty_rate, seed=seed)


def test_two_athlete_simulation_matches_trueskill_analytic_probability():
    left = ExplicitRating("left", mu=27.0, sigma=2.0)
    right = ExplicitRating("right", mu=24.0, sigma=3.0)
    beta = 4.166666666666667
    result = simulate_heat(
        _spec(left, right),
        SimBudget(min_iterations=80_000, max_iterations=80_000, target_ci_width=0.0001, max_seconds=5.0),
        beta=beta,
    )

    simulated = next(item.advance_prob for item in result.probabilities if item.athlete_id == "left")
    analytic = 0.5 * (
        1.0
        + math.erf(
            (left.mu - right.mu)
            / math.sqrt(2.0 * beta * beta + left.sigma * left.sigma + right.sigma * right.sigma)
            / math.sqrt(2.0)
        )
    )
    assert simulated == pytest.approx(analytic, abs=0.012)


def test_simulation_is_seeded_order_independent_and_ci_narrows():
    athletes = (
        ExplicitRating("a", mu=29.0, sigma=2.0),
        ExplicitRating("b", mu=25.0, sigma=3.0),
        ExplicitRating("c", mu=21.0, sigma=2.0),
    )
    wide = simulate_heat(
        _spec(*athletes, seed=99),
        SimBudget(min_iterations=200, max_iterations=200, target_ci_width=0.0001, max_seconds=1.0),
        beta=4.0,
    )
    narrow = simulate_heat(
        _spec(*reversed(athletes), seed=99),
        SimBudget(min_iterations=8_000, max_iterations=8_000, target_ci_width=0.0001, max_seconds=2.0),
        beta=4.0,
    )

    assert narrow.probabilities == simulate_heat(
        _spec(*athletes, seed=99),
        SimBudget(min_iterations=8_000, max_iterations=8_000, target_ci_width=0.0001, max_seconds=2.0),
        beta=4.0,
    ).probabilities
    assert max(item.ci_high - item.ci_low for item in narrow.probabilities) < max(
        item.ci_high - item.ci_low for item in wide.probabilities
    )


def test_cache_key_is_order_independent_but_seed_specific():
    athletes = (
        ExplicitRating("a", mu=29.04, sigma=2.03),
        ExplicitRating("b", mu=25.01, sigma=3.02),
    )
    first = _spec(*athletes, seed=1)
    reordered = _spec(*reversed(athletes), seed=1)
    different_seed = _spec(*athletes, seed=2)

    assert simulation_cache_key(first, beta=4.0, run_id="a" * 16) == simulation_cache_key(
        reordered, beta=4.0, run_id="a" * 16
    )
    assert simulation_cache_key(first, beta=4.0, run_id="a" * 16) != simulation_cache_key(
        different_seed, beta=4.0, run_id="a" * 16
    )


def test_cache_skips_a_repeated_calculation():
    cache = ExpiringLruCache[int](max_entries=1, ttl_seconds=60.0)
    calls = 0

    def compute() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert cache.get_or_compute("key", compute).hit is False
    assert cache.get_or_compute("key", compute).hit is True
    assert calls == 1


def test_time_budget_returns_current_confidence_interval_without_converging():
    result = simulate_heat(
        _spec(ExplicitRating("a", 25.0, 3.0), ExplicitRating("b", 25.0, 3.0)),
        SimBudget(min_iterations=10_000, max_iterations=50_000, target_ci_width=0.01, max_seconds=1e-9),
        beta=4.0,
    )

    assert result.iterations == 64
    assert result.converged is False
    assert all(0.0 <= item.ci_low <= item.advance_prob <= item.ci_high <= 1.0 for item in result.probabilities)


def test_holdout_labels_use_only_later_round_participants_in_same_division():
    heat = RaceObservation(
        race_id="heat",
        race_date=date(2025, 1, 1),
        meet_id="meet",
        season_year=2025,
        event="500m",
        round_class="heat",
        grade_text="elementary",
        gender="M",
        division_text="division",
        participants=tuple(RaceParticipant(athlete_id=value, rank=index, status="FIN", time_sec=None) for index, value in enumerate(("a", "b", "c"), 1)),
    )
    semifinal = RaceObservation(
        race_id="semi",
        race_date=date(2025, 1, 1),
        meet_id="meet",
        season_year=2025,
        event="500m",
        round_class="semifinal",
        grade_text="elementary",
        gender="M",
        division_text="division",
        participants=tuple(RaceParticipant(athlete_id=value, rank=index, status="FIN", time_sec=None) for index, value in enumerate(("a", "b"), 1)),
    )

    assert _advance_labels_for_meet((heat, semifinal)) == {"heat": (2, {"a": 1, "b": 1, "c": 0})}


def test_default_penalty_rate_uses_statuses_before_policy_excludes_penalties(tmp_path: Path):
    path = tmp_path / "results.csv"
    pl.DataFrame(
        {
            "race_id": ["r1", "r1", "r1"],
            "athlete_hash": ["a", "b", "c"],
            "라운드": ["예선1조", "예선1조", "예선1조"],
            "라운드종류": ["예선", "예선", "예선"],
            "순위": ["1", "2", ""],
            "기록_초": ["44.1", "44.2", ""],
            "사유": ["", "", "PEN(S2)"],
            "대회연도": ["2024", "2024", "2024"],
            "종별": ["남자초등부", "남자초등부", "남자초등부"],
            "대회명": ["쇼트트랙 테스트", "쇼트트랙 테스트", "쇼트트랙 테스트"],
            "classCd": ["2", "2", "2"],
        }
    ).write_csv(path)

    assert estimate_penalty_rate(path) == pytest.approx(1 / 3)


def _simulation_client_config(tmp_path: Path) -> tuple[ApiConfig, list[str]]:
    registry = RatingRegistry(tmp_path / "rating-runs")
    engine_params = {"engine": "trueskill", "beta": 4.166666666666667}
    calibrator_spec = {"method": "platt", "slope": 1.0, "intercept": 0.0}
    selected_run = run_id(
        algo_version="rating.replay.v6",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_id="a" * 64,
    )
    registry.begin(
        run_id=selected_run,
        algo_version="rating.replay.v6",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_snapshot_id="a" * 64,
        git_sha="test",
    )
    registry.complete(
        selected_run,
        pl.DataFrame(
            {
                "athlete_id": ["internal-a", "internal-b"],
                "valid_date": [date(2025, 2, 1), date(2025, 2, 1)],
                "mu": [27.0, 23.0],
                "sigma": [2.0, 3.0],
                "n_games": [12, 18],
            }
        ),
        smoothed_snapshots=None,
    )
    opaque_by_athlete = sync_active_opaque_ids(
        tmp_path / "private" / "opaque_ids.sqlite", ["internal-a", "internal-b"]
    )
    ledger_path = tmp_path / "ledger" / "season=2025"
    ledger_path.mkdir(parents=True)
    pl.DataFrame({"status": ["FIN", "FIN", "PEN", "FIN"]}).write_parquet(ledger_path / "part.parquet")
    return (
        ApiConfig(
            registry_root=registry.root,
            opaque_id_db=tmp_path / "private" / "opaque_ids.sqlite",
            penalty_ledger_path=tmp_path / "ledger",
        ),
        [opaque_by_athlete["internal-a"], opaque_by_athlete["internal-b"]],
    )


def test_holdout_calibration_writes_raw_curve_and_rejects_pairwise_transfer(tmp_path: Path):
    registry = RatingRegistry(tmp_path / "rating-runs")
    engine_params = {"engine": "trueskill", "beta": 4.0, "tau": 0.5, "initial_sigma": 8.333}
    calibrator_spec = {
        "method": "platt",
        "slope": 1.0,
        "intercept": 0.0,
        "sample_size": 1,
        "fit_fold": "test",
        "fit_iterations": 1,
        "fit_learning_rate": 1.0,
    }
    selected_run = run_id(
        algo_version="rating.replay.v6",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_id="b" * 64,
    )
    registry.begin(
        run_id=selected_run,
        algo_version="rating.replay.v6",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_snapshot_id="b" * 64,
        git_sha="test",
    )
    registry.complete(
        selected_run,
        pl.DataFrame(
            {
                "athlete_id": ["a"],
                "valid_date": [date(2025, 1, 1)],
                "mu": [25.0],
                "sigma": [4.0],
                "n_games": [6],
            }
        ),
    )
    rows: list[dict[str, object]] = []
    for season in (2024, 2025):
        race_date = f"{season}0101"
        meet_id = f"meet-{season}"
        for race_id, round_class, athlete_ids in (
            (f"heat-{season}", "heat", ("a", "b", "c")),
            (f"semi-{season}", "semifinal", ("a", "b")),
        ):
            race_ordering_key = make_race_ordering_key(
                {"race_date": race_date, "meet_id": meet_id, "race_seq": 1, "race_id": race_id}
            )
            for rank, athlete_id in enumerate(athlete_ids, start=1):
                rows.append(
                    {
                        "ordering_key": make_ordering_key(
                            {
                                "race_date": race_date,
                                "meet_id": meet_id,
                                "race_seq": 1,
                                "race_id": race_id,
                                "rank": rank,
                                "athlete_id": athlete_id,
                            }
                        ),
                        "race_ordering_key": race_ordering_key,
                        "race_id": race_id,
                        "athlete_id": athlete_id,
                        "rank": rank,
                        "status": "FIN",
                        "race_date": race_date,
                        "season_year": season,
                        "meet_id": meet_id,
                        "race_seq": 1,
                        "event": "500m",
                        "round": round_class,
                        "round_kind": round_class,
                        "round_class": round_class,
                        "place_num": rank,
                        "time_sec": 40.0 + rank,
                        "weight": 1.0,
                    }
                )
    ledger_path = tmp_path / "ledger"
    ledger_path.mkdir()
    pl.DataFrame(rows).write_parquet(ledger_path / "part.parquet")
    output_path = tmp_path / "sim_calibration.md"

    run_holdout_calibration(
        ledger_path=ledger_path,
        registry_root=registry.root,
        holdout_seasons=1,
        iterations=100,
        output_path=output_path,
    )

    assert output_path.exists()
    assert output_path.with_suffix(".svg").exists()
    assert "pairwise Platt calibrator is not applied" in output_path.read_text(encoding="utf-8")


def test_heat_api_uses_opaque_ids_and_cache_without_leaking_internal_ids(tmp_path: Path):
    config, opaque_ids = _simulation_client_config(tmp_path)
    with TestClient(create_app(config, today=date(2025, 2, 4))) as client:
        first = client.post(
            "/v1/simulate/heat",
            json={"athletes": opaque_ids, "advance_count": 1, "seed": 101},
        )
        second = client.post(
            "/v1/simulate/heat",
            json={"athletes": list(reversed(opaque_ids)), "advance_count": 1, "seed": 101},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True
    assert first.json()["provenance"]["penalty_source"] == "ledger"
    assert "internal-a" not in first.text
    assert "internal-b" not in first.text


def test_heat_api_rate_limits_cached_requests(tmp_path: Path):
    config, opaque_ids = _simulation_client_config(tmp_path)
    request = {"athletes": opaque_ids, "advance_count": 1, "penalty_rate": 0.0, "seed": 101}
    with TestClient(create_app(config)) as client:
        responses = [client.post("/v1/simulate/heat", json=request) for _ in range(21)]

    assert all(response.status_code == 200 for response in responses[:20])
    assert responses[20].status_code == 429
    assert responses[20].headers["Retry-After"]
