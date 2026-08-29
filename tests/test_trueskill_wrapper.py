import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("trueskill")

from rating.engine.trueskill_wrapper import TrueSkillEngine
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

