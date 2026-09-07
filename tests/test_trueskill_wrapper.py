import sys
import math
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("trueskill")

from rating.engine.trueskill_wrapper import TrueSkillEngine
from rating.engine.trueskill_wrapper import TrueSkillParams
from rating.engine.types import RaceEntry, RaceResult


def test_trueskill_engine_updates_state_and_probs():
    engine = TrueSkillEngine()
    races = [
        RaceResult(
            race_id="r1",
            race_date=date(2024, 1, 1),
            meet_id="m1",
            entries=(RaceEntry("a1", 1, "FIN"), RaceEntry("a2", 2, "FIN"), RaceEntry("a3", 3, "FIN")),
        )
    ]
    state = engine.update({}, races)
    assert state["a1"].mu > state["a2"].mu
    assert state["a2"].mu > state["a3"].mu
    prob = engine.predict_prob("a1", "a3", date(2024, 1, 2))
    assert 0.5 < prob < 1.0


def test_trueskill_effective_rating_recovers_after_layoff_and_caps():
    params = TrueSkillParams(rating_period="month")
    engine = TrueSkillEngine(params=params)
    race = RaceResult(
        race_id="r1",
        race_date=date(2020, 1, 1),
        meet_id="m1",
        entries=(RaceEntry("a1", 1, "FIN"), RaceEntry("a2", 2, "FIN")),
    )
    state = engine.update({}, [race])
    stored = state["a1"]
    one_month_later = engine.effective_rating("a1", date(2020, 2, 1))
    far_future = engine.effective_rating("a1", date(9999, 1, 1))
    assert one_month_later.phi > stored.phi
    assert far_future.phi >= one_month_later.phi
    assert far_future.phi == pytest.approx(params.initial_sigma)


def test_trueskill_update_uses_inactivity_adjusted_sigma(monkeypatch: pytest.MonkeyPatch):
    from rating.engine.glicko2 import Rating

    params = TrueSkillParams(rating_period="month", tau=1.0)
    engine = TrueSkillEngine(params=params)
    state = {
        "a": Rating(mu=params.initial_mu, phi=2.0, sigma=0.0, last_active=date(2020, 1, 1), n_games=10),
        "b": Rating(mu=params.initial_mu, phi=2.0, sigma=0.0, last_active=date(2020, 1, 1), n_games=10),
    }
    captured_sigmas: list[float] = []

    def fake_rate(*, rating_groups, ranks, min_delta):
        del ranks
        assert min_delta == params.convergence_tolerance
        for group in rating_groups:
            for rating in group:
                captured_sigmas.append(float(rating.sigma))
        return rating_groups

    monkeypatch.setattr(engine._env, "rate", fake_rate)
    race = RaceResult(
        race_id="r2",
        race_date=date(2020, 4, 1),
        meet_id="m2",
        entries=(RaceEntry("a", 1, "FIN"), RaceEntry("b", 2, "FIN")),
    )
    updated = engine.update(state, [race])
    expected = math.sqrt((2.0 * 2.0) + (params.tau * params.tau * 3.0))
    assert captured_sigmas == pytest.approx([expected, expected])
    assert updated["a"].phi == pytest.approx(expected)
    assert updated["b"].phi == pytest.approx(expected)


def test_trueskill_update_passes_nondefault_entry_weights(monkeypatch: pytest.MonkeyPatch):
    engine = TrueSkillEngine()
    captured_weights: list[tuple[float, ...]] = []

    def fake_rate(*, rating_groups, ranks, weights, min_delta):
        del ranks, min_delta
        captured_weights.extend(weights)
        return rating_groups

    monkeypatch.setattr(engine._env, "rate", fake_rate)
    engine.update(
        {},
        [
            RaceResult(
                race_id="weighted",
                race_date=date(2024, 1, 1),
                meet_id="m1",
                entries=(RaceEntry("a", 1, "FIN", weight=1.5), RaceEntry("b", 2, "FIN", weight=1.5)),
            )
        ],
    )

    assert captured_weights == [(1.5,), (1.5,)]


def test_trueskill_initial_rating_uses_prior_provider():
    params = TrueSkillParams(initial_mu=25.0, initial_sigma=8.0)
    engine = TrueSkillEngine(params=params, prior_provider=lambda athlete_id: (30.0, 4.0) if athlete_id == "rookie" else None)
    rookie = engine.effective_rating("rookie", date(2024, 1, 1))
    veteran = engine.effective_rating("veteran", date(2024, 1, 1))
    assert rookie.mu == pytest.approx(30.0)
    assert rookie.phi == pytest.approx(4.0)
    assert veteran.mu == pytest.approx(25.0)
    assert veteran.phi == pytest.approx(8.0)


def test_trueskill_constant_tau_provider_matches_scalar_tau():
    params = TrueSkillParams(tau=0.5, rating_period="meet")
    scalar = TrueSkillEngine(params=params)
    per_athlete = TrueSkillEngine(params=params, tau_provider=lambda _athlete_id, _as_of: 0.5)
    races = [
        RaceResult(
            race_id="r1",
            race_date=date(2024, 1, 1),
            meet_id="m1",
            entries=(RaceEntry("a1", 1, "FIN"), RaceEntry("a2", 2, "FIN"), RaceEntry("a3", 3, "FIN")),
        ),
        RaceResult(
            race_id="r2",
            race_date=date(2024, 2, 1),
            meet_id="m2",
            entries=(RaceEntry("a2", 1, "FIN"), RaceEntry("a1", 2, "FIN"), RaceEntry("a3", 3, "FIN")),
        ),
    ]
    scalar_state = scalar.update({}, races)
    provider_state = per_athlete.update({}, races)
    for athlete_id in scalar_state:
        assert provider_state[athlete_id].mu == pytest.approx(scalar_state[athlete_id].mu)
        assert provider_state[athlete_id].phi == pytest.approx(scalar_state[athlete_id].phi)


def test_trueskill_is_invariant_to_entry_order():
    params = TrueSkillParams(convergence_tolerance=1e-4)
    ordered = RaceResult(
        race_id="r1",
        race_date=date(2024, 1, 1),
        meet_id="m1",
        entries=(RaceEntry("a1", 1, "FIN"), RaceEntry("a2", 2, "FIN"), RaceEntry("a3", 3, "FIN")),
    )
    shuffled = RaceResult(
        race_id="r1",
        race_date=date(2024, 1, 1),
        meet_id="m1",
        entries=(RaceEntry("a3", 3, "FIN"), RaceEntry("a1", 1, "FIN"), RaceEntry("a2", 2, "FIN")),
    )

    assert TrueSkillEngine(params=params).update({}, [ordered]) == TrueSkillEngine(params=params).update({}, [shuffled])


def test_trueskill_ep_configuration_changes_result():
    race = RaceResult(
        race_id="r1",
        race_date=date(2024, 1, 1),
        meet_id="m1",
        entries=tuple(RaceEntry(f"a{index}", index, "FIN") for index in range(1, 7)),
    )
    precise = TrueSkillEngine(
        params=TrueSkillParams(convergence_tolerance=1e-8, ep_max_iterations=10)
    ).update({}, [race])
    loose = TrueSkillEngine(
        params=TrueSkillParams(convergence_tolerance=1e-8, ep_max_iterations=1)
    ).update({}, [race])

    assert any(precise[athlete_id].mu != loose[athlete_id].mu for athlete_id in precise)


def test_trueskill_all_tied_race_does_not_update_or_fail():
    race = RaceResult(
        race_id="r1",
        race_date=date(2024, 1, 1),
        meet_id="m1",
        entries=(RaceEntry("a1", 1, "FIN"), RaceEntry("a2", 1, "FIN")),
    )

    assert TrueSkillEngine().update({}, [race]) == {}
