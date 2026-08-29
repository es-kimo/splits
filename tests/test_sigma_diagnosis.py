from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.engine.trueskill_wrapper import TrueSkillEngine, TrueSkillParams
from rating.engine.types import elapsed_periods
from rating.eval.sigma_diagnosis import (
    BUG_VERDICT_MIN_QUANTILES,
    INVERSION_MARGIN,
    MIN_CELL_SIZE,
    MU_QUANTILE_COUNT,
    QuantileRow,
    _decide,
    _mu_edges,
    _spearman,
)


def _row(label: str, low: float, high: float, *, reliable: bool = True) -> QuantileRow:
    return QuantileRow(
        label=label,
        mu_low=0.0,
        mu_high=1.0,
        n=1_000,
        low_sigma_log_loss=low,
        high_sigma_log_loss=high,
        reliable=reliable,
    )


def test_confounding_verdict_when_control_removes_the_inversion():
    """통제 후 대부분의 분위에서 정상 방향이면 교락으로 판정해야 합니다."""
    rows = [
        _row("Q1", 0.687, 0.684),
        _row("Q2", 0.664, 0.666),
        _row("Q3", 0.578, 0.619),
        _row("Q4", 0.436, 0.529),
        _row("Q5", 0.416, 0.346),
    ]
    verdict = _decide(rows, uncontrolled_gap=-0.106)
    assert verdict.label == "교락"
    assert verdict.inverted_quantiles == 1
    assert verdict.comparable_quantiles == MU_QUANTILE_COUNT


def test_bug_verdict_when_inversion_survives_the_control():
    """낮은 sigma가 실력 차이와 무관하게 손해를 보면 버그로 판정해야 합니다."""
    rows = [_row(f"Q{index}", 0.70, 0.55) for index in range(1, MU_QUANTILE_COUNT + 1)]
    verdict = _decide(rows, uncontrolled_gap=-0.15)
    assert verdict.label == "버그"
    assert verdict.inverted_quantiles == MU_QUANTILE_COUNT


def test_bug_threshold_is_not_crossed_one_quantile_early():
    """경계 바로 아래에서는 버그로 넘어가지 않아야 규칙이 의미를 갖습니다."""
    inverted = BUG_VERDICT_MIN_QUANTILES - 1
    rows = [_row(f"Q{index}", 0.70, 0.55) for index in range(1, inverted + 1)]
    rows += [_row(f"Q{index}", 0.55, 0.70) for index in range(inverted + 1, MU_QUANTILE_COUNT + 1)]
    verdict = _decide(rows, uncontrolled_gap=-0.15)
    assert verdict.label == "교락"


def test_differences_within_the_noise_margin_are_not_counted_as_inversion():
    gap = INVERSION_MARGIN / 2.0
    rows = [_row(f"Q{index}", 0.60, 0.60 - gap) for index in range(1, MU_QUANTILE_COUNT + 1)]
    verdict = _decide(rows, uncontrolled_gap=-0.15)
    assert verdict.inverted_quantiles == 0
    assert verdict.label == "교락"


def test_unreliable_cells_are_excluded_from_the_verdict():
    """표본이 부족한 칸은 역전으로도 정상으로도 세지 않습니다."""
    rows = [_row(f"Q{index}", 0.70, 0.55, reliable=False) for index in range(1, MU_QUANTILE_COUNT + 1)]
    verdict = _decide(rows, uncontrolled_gap=-0.15)
    assert verdict.comparable_quantiles == 0
    assert verdict.inverted_quantiles == 0
    assert verdict.label == "교락"


def test_no_inversion_verdict_when_the_uncontrolled_gap_is_normal():
    rows = [_row(f"Q{index}", 0.55, 0.70) for index in range(1, MU_QUANTILE_COUNT + 1)]
    verdict = _decide(rows, uncontrolled_gap=0.15)
    assert verdict.label == "역전 없음"


def test_mu_edges_split_the_sample_into_equal_quantiles():
    values = [float(value) for value in range(1000)]
    edges = _mu_edges(values)
    assert len(edges) == MU_QUANTILE_COUNT - 1
    assert edges == tuple(sorted(edges))
    for index, edge in enumerate(edges):
        share = sum(1 for value in values if value <= edge) / len(values)
        assert share == pytest.approx((index + 1) / MU_QUANTILE_COUNT, abs=0.02)


def test_spearman_detects_monotone_decrease():
    xs = [float(value) for value in range(50)]
    ys = [-float(value) for value in range(50)]
    assert _spearman(xs, ys) == pytest.approx(-1.0)
    assert _spearman(xs, xs) == pytest.approx(1.0)


def test_spearman_handles_ties_without_blowing_up():
    xs = [1.0, 1.0, 1.0, 2.0, 2.0]
    ys = [3.0, 3.0, 1.0, 2.0, 2.0]
    value = _spearman(xs, ys)
    assert math.isfinite(value)
    assert -1.0 <= value <= 1.0


def test_min_cell_size_guard_is_meaningful():
    """표본 하한이 0이면 노이즈 칸이 판정에 섞이므로 규칙이 무력해집니다."""
    assert MIN_CELL_SIZE > 0


class _Example:
    """`pair_diagnostics`가 필요로 하는 최소 필드만 가진 대역입니다."""

    def __init__(self, winner_id: str, loser_id: str, race_date: date) -> None:
        self.winner_id = winner_id
        self.loser_id = loser_id
        self.race_date = race_date


def test_pair_diagnostics_reads_prediction_time_state_only():
    """진단 컬럼이 갱신 이후 정보를 담으면 진단 자체가 결과를 훔쳐봅니다."""
    from rating.eval.backtest import _build_model
    from rating.engine.types import RaceEntry, RaceResult

    model = _build_model("trueskill", "meet")
    race = RaceResult(
        race_id="r1",
        race_date=date(2024, 5, 1),
        meet_id="m1",
        entries=(
            RaceEntry(athlete_id="a", rank=1, status="OK"),
            RaceEntry(athlete_id="b", rank=2, status="OK"),
        ),
    )

    before = model.pair_diagnostics(_Example("a", "b", date(2024, 5, 1)))
    assert before["pair_n_games_max"] == 0
    assert before["pair_sigma_max"] == pytest.approx(TrueSkillParams().initial_sigma)
    assert before["pair_mu_abs_diff"] == pytest.approx(0.0)

    model.state = model.predictor.update(model.state, [race])
    after = model.pair_diagnostics(_Example("a", "b", date(2024, 6, 1)))
    assert after["pair_n_games_max"] == 1
    assert after["pair_sigma_max"] < before["pair_sigma_max"]
    assert after["pair_mu_abs_diff"] > 0.0


def test_trueskill_sigma_decreases_with_more_races():
    """보조 확인의 전제: 출전이 쌓이면 불확실성이 줄어야 합니다."""
    from rating.engine.types import RaceEntry, RaceResult

    engine = TrueSkillEngine()
    state: dict = {}
    sigmas: list[float] = []
    for index in range(6):
        race = RaceResult(
            race_id=f"r{index}",
            race_date=date(2024, 1 + index, 1),
            meet_id=f"m{index}",
            entries=(
                RaceEntry(athlete_id="a", rank=1, status="OK"),
                RaceEntry(athlete_id="b", rank=2, status="OK"),
            ),
        )
        state = engine.update(state, [race])
        sigmas.append(state["a"].phi)
    assert sigmas == sorted(sigmas, reverse=True)


def test_trueskill_sigma_does_not_recover_after_a_layoff():
    """R-19가 기록한 결함을 고정합니다.

    Glicko-2는 쉬는 동안 불확실성을 되돌리지만 TrueSkill은 그러지 않습니다.
    이 동작이 바뀌면 ADR 0007의 관측이 낡은 것이므로 함께 갱신해야 합니다.
    """
    from rating.engine.types import RaceEntry, RaceResult

    engine = TrueSkillEngine(params=TrueSkillParams(rating_period="meet"))
    race = RaceResult(
        race_id="r0",
        race_date=date(2020, 1, 1),
        meet_id="m0",
        entries=(
            RaceEntry(athlete_id="a", rank=1, status="OK"),
            RaceEntry(athlete_id="b", rank=2, status="OK"),
        ),
    )
    engine.update({}, [race])

    right_after = engine.effective_rating("a", date(2020, 2, 1))
    four_years_later = engine.effective_rating("a", date(2024, 1, 1))
    assert elapsed_periods(right_after.last_active, date(2024, 1, 1), "meet") == 48
    assert four_years_later.phi == pytest.approx(right_after.phi)


def test_glicko2_effective_rating_reflects_the_inactivity_decay():
    """대조군: Glicko-2는 예측 시점 불확실성을 되돌립니다."""
    from rating.engine.glicko2 import Glicko2Engine
    from rating.engine.types import RaceEntry, RaceResult

    engine = Glicko2Engine()
    race = RaceResult(
        race_id="r0",
        race_date=date(2020, 1, 1),
        meet_id="m0",
        entries=(
            RaceEntry(athlete_id="a", rank=1, status="OK"),
            RaceEntry(athlete_id="b", rank=2, status="OK"),
        ),
    )
    engine.update({}, [race])
    soon = engine.effective_rating("a", date(2020, 2, 1))
    later = engine.effective_rating("a", date(2024, 1, 1))
    assert later.phi > soon.phi


def test_sigma_bucket_and_mu_bucket_partition_every_row():
    """모든 행이 정확히 한 칸에 들어가야 합계가 표본과 맞습니다."""
    from rating.eval.sigma_diagnosis import _mu_bucket_expr, _sigma_bucket_expr

    frame = pl.DataFrame(
        {
            "pair_sigma_max": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "pair_mu_abs_diff": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
        }
    )
    edges = _mu_edges(frame["pair_mu_abs_diff"].to_list())
    tagged = frame.with_columns([_sigma_bucket_expr(2.0, 4.0), _mu_bucket_expr(edges)])
    assert tagged["sigma_bucket"].null_count() == 0
    assert tagged["mu_bucket"].null_count() == 0
    assert set(tagged["sigma_bucket"].to_list()) <= {"low", "mid", "high"}
    assert tagged.group_by("mu_bucket").len()["len"].sum() == frame.height
