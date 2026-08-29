import ast
import inspect
import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.calibration import IDENTITY_CALIBRATOR
from rating.engine.glicko2 import Glicko2Engine, Glicko2Params
from rating.eval.backtest import evaluate
from rating.ledger.ordering import make_ordering_key, make_race_ordering_key

ROOT = Path(__file__).resolve().parents[1]
BACKTEST_PATH = ROOT / "rating" / "eval" / "backtest.py"
ALLOWED_RAW_CALLS = {"predict_calibrated", "_fit_engine_tau", "_fit_calibrator", "_evaluate_config"}


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


def _minimal_holdout() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a1", rank=1),
            _row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a2", rank=2),
        ]
    )


def _find_enclosing_function(path: Path, line_number: int) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        start = getattr(node, "lineno", -1)
        end = getattr(node, "end_lineno", -1)
        if start <= line_number <= end:
            return node.name
    return "<module>"


def test_evaluate_requires_calibrator_argument():
    signature = inspect.signature(evaluate)
    param = signature.parameters["calibrator"]
    assert param.default is inspect._empty

    with pytest.raises(TypeError):
        evaluate(Glicko2Engine(params=Glicko2Params(rating_period="meet")), _minimal_holdout(), rating_period="meet")

    metrics = evaluate(
        Glicko2Engine(params=Glicko2Params(rating_period="meet")),
        _minimal_holdout(),
        calibrator=IDENTITY_CALIBRATOR,
        rating_period="meet",
    )
    assert metrics.sample_size == 1


def test_predict_raw_calls_are_allowlisted():
    tree = ast.parse(BACKTEST_PATH.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "predict_raw":
            continue
        fn = _find_enclosing_function(BACKTEST_PATH, node.lineno)
        if fn not in ALLOWED_RAW_CALLS:
            violations.append(f"{BACKTEST_PATH.name}:{node.lineno} in {fn}")
    assert not violations, f"allow-list 밖 원시 확률 경로가 있습니다: {violations}"
