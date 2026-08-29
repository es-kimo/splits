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

    def fake_rate(*, rating_groups, ranks):
        del ranks
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
