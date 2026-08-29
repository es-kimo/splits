import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.calibration import IDENTITY_CALIBRATOR
from rating.engine.glicko2 import Glicko2Engine, Glicko2Params
from rating.eval.backtest import evaluate
from rating.ledger.ordering import make_ordering_key, make_race_ordering_key


def _row(
    *,
    race_date: str,
    meet_id: str,
    race_seq: int,
    race_id: str,
    athlete_id: str,
    rank: int,
) -> dict[str, object]:
    race_ordering_key = make_race_ordering_key(
        {"race_date": race_date, "meet_id": meet_id, "race_seq": race_seq, "race_id": race_id}
    )
    ordering_key = make_ordering_key(
        {
            "race_date": race_date,
            "meet_id": meet_id,
            "race_seq": race_seq,
            "race_id": race_id,
            "rank": rank,
            "athlete_id": athlete_id,
        }
    )
    return {
        "ordering_key": ordering_key,
        "race_ordering_key": race_ordering_key,
        "race_id": race_id,
        "athlete_id": athlete_id,
        "rank": rank,
        "status": "FIN",
        "race_date": race_date,
        "season_year": 2024,
        "meet_id": meet_id,
        "race_seq": race_seq,
        "event": "500m",
        "round": "결승Final",
        "round_kind": "결승",
        "round_class": "final",
        "grade_text": "5,6",
        "gender": "남",
        "place_num": rank,
        "time_sec": 43.0 + rank,
        "weight": 1.0,
    }


def test_meet_period_uses_pre_meet_state_for_all_races():
    frame = pl.DataFrame(
        [
            _row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a1", rank=1),
            _row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a2", rank=2),
            _row(race_date="20240101", meet_id="m1", race_seq=2, race_id="r2", athlete_id="a2", rank=1),
            _row(race_date="20240101", meet_id="m1", race_seq=2, race_id="r2", athlete_id="a1", rank=2),
        ]
    )

    metrics = evaluate(
        Glicko2Engine(params=Glicko2Params(rating_period="meet")),
        frame,
        calibrator=IDENTITY_CALIBRATOR,
        rating_period="meet",
    )
    probs = metrics.predictions.sort("comparison_id")["probability"].to_list()
    assert len(probs) == 2
    assert probs[0] == pytest.approx(probs[1], rel=1e-9)


def test_month_period_uses_pre_month_state_for_all_races():
    frame = pl.DataFrame(
        [
            _row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a1", rank=1),
            _row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a2", rank=2),
            _row(race_date="20240120", meet_id="m2", race_seq=1, race_id="r2", athlete_id="a2", rank=1),
            _row(race_date="20240120", meet_id="m2", race_seq=1, race_id="r2", athlete_id="a1", rank=2),
        ]
    )

    metrics = evaluate(
        Glicko2Engine(params=Glicko2Params(rating_period="month")),
        frame,
        calibrator=IDENTITY_CALIBRATOR,
        rating_period="month",
    )
    probs = metrics.predictions.sort("comparison_id")["probability"].to_list()
    assert len(probs) == 2
    assert probs[0] == pytest.approx(probs[1], rel=1e-9)
