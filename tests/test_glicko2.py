import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.engine.glicko2 import Glicko2Engine, Glicko2Params, Rating
from rating.engine.types import Comparison, RaceEntry, RaceResult


def test_glickman_example_reproduces_reference_numbers():
    params = Glicko2Params(tau=0.5, initial_mu=1500.0, initial_phi=350.0, initial_sigma=0.06, rating_period="meet")
    engine = Glicko2Engine(params=params)
    state = {
        "player": Rating(mu=1500.0, phi=200.0, sigma=0.06, last_active=date(2024, 1, 1), n_games=0),
        "opp_a": Rating(mu=1400.0, phi=30.0, sigma=0.06, last_active=date(2024, 1, 1), n_games=0),
        "opp_b": Rating(mu=1550.0, phi=100.0, sigma=0.06, last_active=date(2024, 1, 1), n_games=0),
        "opp_c": Rating(mu=1700.0, phi=300.0, sigma=0.06, last_active=date(2024, 1, 1), n_games=0),
    }
    comps = [
        Comparison(winner_id="player", loser_id="opp_a", race_date=date(2024, 2, 1), outcome=1.0, weight=1.0),
        Comparison(winner_id="opp_b", loser_id="player", race_date=date(2024, 2, 1), outcome=1.0, weight=1.0),
        Comparison(winner_id="opp_c", loser_id="player", race_date=date(2024, 2, 1), outcome=1.0, weight=1.0),
    ]
    updated = engine.process_period(state, comps)
    player = updated["player"]
    assert player.mu == pytest.approx(1464.06, rel=1e-4)
    assert player.phi == pytest.approx(151.52, rel=1e-4)
    assert player.sigma == pytest.approx(0.05999, rel=1e-4)
    assert player.n_games == 3


def test_longer_inactivity_increases_phi_but_stays_bounded():
    params = Glicko2Params(initial_phi=350.0, rating_period="meet")
    engine = Glicko2Engine(params=params)
    base_state = {
        "a": Rating(mu=1550.0, phi=60.0, sigma=0.06, last_active=date(2024, 1, 1), n_games=20),
        "b": Rating(mu=1500.0, phi=60.0, sigma=0.06, last_active=date(2024, 1, 1), n_games=20),
    }
    short_gap = [
        RaceResult(
            race_id="r-short",
            race_date=date(2024, 2, 1),
            meet_id="m-short",
            entries=(RaceEntry("a", 1, "FIN"), RaceEntry("b", 2, "FIN")),
        )
    ]
    long_gap = [
        RaceResult(
            race_id="r-long",
            race_date=date(2024, 6, 1),
            meet_id="m-long",
            entries=(RaceEntry("a", 1, "FIN"), RaceEntry("b", 2, "FIN")),
        )
    ]

    short_state = engine.update(dict(base_state), short_gap)
    long_state = engine.update(dict(base_state), long_gap)
    assert long_state["a"].phi > short_state["a"].phi
    assert long_state["a"].phi <= params.initial_phi


def test_pairwise_size_weight_reduces_large_race_impact():
    race = [
        RaceResult(
            race_id="r1",
            race_date=date(2024, 3, 1),
            meet_id="m1",
            entries=(
                RaceEntry("a1", 1, "FIN"),
                RaceEntry("a2", 2, "FIN"),
                RaceEntry("a3", 3, "FIN"),
                RaceEntry("a4", 4, "FIN"),
            ),
        )
    ]
    weighted = Glicko2Engine(pairwise_size_weight=True).update({}, race)
    unweighted = Glicko2Engine(pairwise_size_weight=False).update({}, race)

    assert weighted["a1"].mu < unweighted["a1"].mu
    assert weighted["a4"].mu > unweighted["a4"].mu



def test_volatility_solver_converges_when_illinois_stalls():
    """Illinois는 B가 해에 도달해도 부호가 안 바뀌면 A가 따라오지 못해 멈춥니다.

    이 인자 조합에서 괄호 폭이 6.4e-06에 고정된 채 반복만 소모하다
    max_iterations에서 터졌습니다. tau=1.2 격자를 돌릴 때 실제로 발생했습니다.
    """
    engine = Glicko2Engine(params=Glicko2Params(tau=1.2))
    sigma_prime = engine._solve_volatility(0.1, 0.06, -1.0, 0.05)
    assert sigma_prime == pytest.approx(0.22566, rel=1e-4)


@pytest.mark.parametrize("tau", [0.2, 0.35, 0.5, 0.8, 1.2])
def test_volatility_solver_converges_across_the_tau_grid(tau):
    engine = Glicko2Engine(params=Glicko2Params(tau=tau))
    for phi in (0.05, 0.5, 2.0):
        for sigma in (0.01, 0.06, 0.2):
            for delta in (-5.0, -1.0, 0.5, 5.0):
                for variance in (0.01, 0.5, 5.0):
                    assert engine._solve_volatility(phi, sigma, delta, variance) > 0.0
