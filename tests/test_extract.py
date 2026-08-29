import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.ledger.extract import extract_comparisons
from rating.ledger.policies import AGGRESSIVE, CONSERVATIVE, PLACE_ONLY


def _as_pairs(df: pl.DataFrame) -> list[tuple[str, str, str]]:
    rows = df.select(["winner_id", "loser_id", "source_status"]).to_dicts()
    return [(row["winner_id"], row["loser_id"], row["source_status"]) for row in rows]


def test_finishers_only_generates_full_pairwise():
    frame = pl.DataFrame(
        [
            {"race_id": "r1", "athlete_hash": "a1", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "1", "기록_초": "44.10", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a2", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "2", "기록_초": "44.20", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a3", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "3", "기록_초": "44.30", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a4", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "4", "기록_초": "44.40", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a5", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "5", "기록_초": "44.50", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a6", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "6", "기록_초": "44.60", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
        ]
    )
    out = extract_comparisons(frame, CONSERVATIVE)
    assert out.height == 15
    assert set(out["source_status"].to_list()) == {"FIN-FIN"}


def test_penalty_mode_changes_pair_count():
    frame = pl.DataFrame(
        [
            {"race_id": "r1", "athlete_hash": "a1", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "1", "기록_초": "44.1", "사유": "", "대회연도": "2024", "종별": "남자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a2", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "2", "기록_초": "44.2", "사유": "", "대회연도": "2024", "종별": "남자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a3", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "", "기록_초": "", "사유": "PEN(S2)", "대회연도": "2024", "종별": "남자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
        ]
    )
    conservative = extract_comparisons(frame, CONSERVATIVE)
    aggressive = extract_comparisons(frame, AGGRESSIVE)

    assert conservative.height == 1
    assert aggressive.height == 3
    assert ("a1", "a3", "FIN-PEN") in _as_pairs(aggressive)
    assert ("a2", "a3", "FIN-PEN") in _as_pairs(aggressive)


def test_dnf_policy_loss_to_finishers():
    frame = pl.DataFrame(
        [
            {"race_id": "r1", "athlete_hash": "a1", "라운드": "준결승1조Semi Final 1", "라운드종류": "준결승", "순위": "1", "기록_초": "44.1", "사유": "", "대회연도": "2024", "종별": "남자중학부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a2", "라운드": "준결승1조Semi Final 1", "라운드종류": "준결승", "순위": "2", "기록_초": "44.2", "사유": "", "대회연도": "2024", "종별": "남자중학부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a3", "라운드": "준결승1조Semi Final 1", "라운드종류": "준결승", "순위": "", "기록_초": "", "사유": "DNF", "대회연도": "2024", "종별": "남자중학부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
        ]
    )
    conservative = extract_comparisons(frame, CONSERVATIVE)
    aggressive = extract_comparisons(frame, AGGRESSIVE)

    assert conservative.height == 1
    assert aggressive.height == 3
    assert ("a1", "a3", "FIN-DNF") in _as_pairs(aggressive)
    assert ("a2", "a3", "FIN-DNF") in _as_pairs(aggressive)


def test_ties_do_not_create_comparison():
    frame = pl.DataFrame(
        [
            {"race_id": "r1", "athlete_hash": "a1", "라운드": "결승Final", "라운드종류": "결승", "순위": "1", "기록_초": "43.1", "사유": "", "대회연도": "2024", "종별": "여자중학부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a2", "라운드": "결승Final", "라운드종류": "결승", "순위": "1", "기록_초": "43.3", "사유": "", "대회연도": "2024", "종별": "여자중학부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a3", "라운드": "결승Final", "라운드종류": "결승", "순위": "3", "기록_초": "43.5", "사유": "", "대회연도": "2024", "종별": "여자중학부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
        ]
    )
    out = extract_comparisons(frame, AGGRESSIVE)
    assert out.height == 2
    assert ("a1", "a2", "FIN-FIN") not in _as_pairs(out)


def test_unknown_status_raises():
    frame = pl.DataFrame(
        [
            {"race_id": "r1", "athlete_hash": "a1", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "", "기록_초": "", "사유": "MYSTERY", "대회연도": "2024", "종별": "남자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r1", "athlete_hash": "a2", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "1", "기록_초": "44.1", "사유": "", "대회연도": "2024", "종별": "남자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
        ]
    )
    with pytest.raises(ValueError):
        extract_comparisons(frame, CONSERVATIVE)


def test_race_boundary_and_policy_filters():
    frame = pl.DataFrame(
        [
            {"race_id": "r_final", "athlete_hash": "a1", "라운드": "결승Final", "라운드종류": "결승", "순위": "1", "기록_초": "43.1", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r_final", "athlete_hash": "a2", "라운드": "결승Final", "라운드종류": "결승", "순위": "2", "기록_초": "43.3", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r_heat", "athlete_hash": "a1", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "1", "기록_초": "44.1", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r_heat", "athlete_hash": "a3", "라운드": "예선1조Heat 1", "라운드종류": "예선", "순위": "2", "기록_초": "44.5", "사유": "", "대회연도": "2024", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r_old", "athlete_hash": "a4", "라운드": "결승Final", "라운드종류": "결승", "순위": "1", "기록_초": "45.1", "사유": "", "대회연도": "2012", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r_old", "athlete_hash": "a5", "라운드": "결승Final", "라운드종류": "결승", "순위": "2", "기록_초": "45.2", "사유": "", "대회연도": "2012", "종별": "남자초등5,6학년", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r_hobby", "athlete_hash": "a6", "라운드": "결승Final", "라운드종류": "결승", "순위": "1", "기록_초": "45.1", "사유": "", "대회연도": "2024", "종별": "남자동호인부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r_hobby", "athlete_hash": "a7", "라운드": "결승Final", "라운드종류": "결승", "순위": "2", "기록_초": "45.2", "사유": "", "대회연도": "2024", "종별": "남자동호인부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
            {"race_id": "r_speed", "athlete_hash": "a8", "라운드": "1조", "라운드종류": "", "순위": "1", "기록_초": "40.1", "사유": "", "대회연도": "2024", "종별": "남자부", "대회명": "전국 스피드스케이팅 선수권", "classCd": "2"},
            {"race_id": "r_speed", "athlete_hash": "a9", "라운드": "1조", "라운드종류": "", "순위": "2", "기록_초": "40.3", "사유": "", "대회연도": "2024", "종별": "남자부", "대회명": "전국 스피드스케이팅 선수권", "classCd": "2"},
        ]
    )
    out = extract_comparisons(frame, PLACE_ONLY)
    assert out.height == 1
    assert out["race_id"].to_list() == ["r_final"]


def test_output_order_is_deterministic():
    rows = [
        {"race_id": "r2", "athlete_hash": "b2", "라운드": "결승Final", "라운드종류": "결승", "순위": "2", "기록_초": "43.4", "사유": "", "대회연도": "2024", "종별": "여자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
        {"race_id": "r1", "athlete_hash": "a2", "라운드": "결승Final", "라운드종류": "결승", "순위": "2", "기록_초": "44.4", "사유": "", "대회연도": "2024", "종별": "남자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
        {"race_id": "r1", "athlete_hash": "a1", "라운드": "결승Final", "라운드종류": "결승", "순위": "1", "기록_초": "44.1", "사유": "", "대회연도": "2024", "종별": "남자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
        {"race_id": "r2", "athlete_hash": "b1", "라운드": "결승Final", "라운드종류": "결승", "순위": "1", "기록_초": "43.2", "사유": "", "대회연도": "2024", "종별": "여자초등부", "대회명": "쇼트트랙 테스트", "classCd": "2"},
    ]
    first = extract_comparisons(pl.DataFrame(rows), CONSERVATIVE)
    second = extract_comparisons(pl.DataFrame(list(reversed(rows))), CONSERVATIVE)

    assert first.to_dicts() == second.to_dicts()

