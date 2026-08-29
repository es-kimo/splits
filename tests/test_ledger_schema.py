import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.ledger.build import (
    _build_athlete_meta,
    _build_race_ledger,
    _merge_external_athlete_meta,
    _snapshot_parquet_hashes,
    _write_partitioned,
)
from rating.ledger.extract import _prepare_rows_for_policy
from rating.ledger.ordering import build_race_sequence_map, make_ordering_key, make_race_ordering_key
from rating.ledger.policies import CONSERVATIVE
from rating.ledger.schema import build_pairwise_view, build_ranking_view, validate_ledger


def _ledger_row(
    *,
    race_date: str,
    meet_id: str,
    race_seq: int,
    race_id: str,
    athlete_id: str,
    rank: int,
    status: str,
    round_class: str = "final",
) -> dict:
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
        "status": status,
        "race_date": race_date,
        "season_year": 2024,
        "meet_id": meet_id,
        "race_seq": race_seq,
        "event": "500m",
        "round": "결승Final",
        "round_kind": "결승",
        "round_class": round_class,
        "grade_text": "5,6",
        "gender": "남",
        "division_text": "초등",
        "birth_year": 2013,
        "place_num": rank if status != "DNF" else None,
        "time_sec": 43.0 + rank,
        "weight": 1.0,
    }


def test_validate_ledger_and_views_are_lossless():
    frame = pl.DataFrame(
        [
            _ledger_row(
                race_date="20240101",
                meet_id="2024:meet-a",
                race_seq=1,
                race_id="r1",
                athlete_id="a1",
                rank=1,
                status="FIN",
            ),
            _ledger_row(
                race_date="20240101",
                meet_id="2024:meet-a",
                race_seq=1,
                race_id="r1",
                athlete_id="a2",
                rank=2,
                status="FIN",
            ),
            _ledger_row(
                race_date="20240101",
                meet_id="2024:meet-a",
                race_seq=1,
                race_id="r1",
                athlete_id="a3",
                rank=3,
                status="PEN",
            ),
            _ledger_row(
                race_date="20240101",
                meet_id="2024:meet-a",
                race_seq=1,
                race_id="r1",
                athlete_id="a4",
                rank=4,
                status="DNF",
            ),
            _ledger_row(
                race_date="20240102",
                meet_id="2024:meet-b",
                race_seq=1,
                race_id="r2",
                athlete_id="b1",
                rank=1,
                status="FIN",
            ),
            _ledger_row(
                race_date="20240102",
                meet_id="2024:meet-b",
                race_seq=1,
                race_id="r2",
                athlete_id="b2",
                rank=2,
                status="ADV",
            ),
        ]
    )

    validate_ledger(frame)

    pairwise = build_pairwise_view(frame)
    got_pairs = {(row["winner_id"], row["loser_id"], row["source_status"]) for row in pairwise.to_dicts()}
    assert got_pairs == {
        ("a1", "a2", "FIN-FIN"),
        ("a1", "a3", "FIN-PEN"),
        ("a2", "a3", "FIN-PEN"),
        ("a1", "a4", "FIN-DNF"),
        ("a2", "a4", "FIN-DNF"),
        ("b1", "b2", "FIN-ADV"),
    }

    ranking = build_ranking_view(frame)
    original_rank = (
        frame.sort(["race_id", "rank", "athlete_id"], nulls_last=True)
        .select(["race_id", "athlete_id", "rank", "status"])
        .to_dicts()
    )
    ranking_rank = ranking.sort(["race_id", "rank", "athlete_id"], nulls_last=True).select(
        ["race_id", "athlete_id", "rank", "status"]
    )
    assert ranking_rank.to_dicts() == original_rank


def test_validate_ledger_rejects_duplicate_ordering_key():
    row = _ledger_row(
        race_date="20240101",
        meet_id="2024:meet-a",
        race_seq=1,
        race_id="r1",
        athlete_id="a1",
        rank=1,
        status="FIN",
    )
    frame = pl.DataFrame([row, {**row, "athlete_id": "a2", "rank": 2}])
    with pytest.raises(ValueError, match="ordering_key"):
        validate_ledger(frame)


def test_validate_ledger_rejects_unknown_round_class():
    frame = pl.DataFrame(
        [
            _ledger_row(
                race_date="20240101",
                meet_id="2024:meet-a",
                race_seq=1,
                race_id="r1",
                athlete_id="a1",
                rank=1,
                status="FIN",
                round_class="mystery",
            )
        ]
    )
    with pytest.raises(ValueError, match="round_class"):
        validate_ledger(frame)


def test_validate_ledger_allows_crowded_tie_when_times_are_missing():
    rows = [
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a1", rank=1, status="FIN"),
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a2", rank=2, status="FIN"),
    ]
    for idx in range(3, 8):
        rows.append(
            {
                **_ledger_row(
                    race_date="20250321",
                    meet_id="m1",
                    race_seq=1,
                    race_id="r1",
                    athlete_id=f"a{idx}",
                    rank=3,
                    status="FIN",
                ),
                "time_sec": None,
                "place_num": 3,
            }
        )
    validate_ledger(pl.DataFrame(rows))


def test_validate_ledger_rejects_crowded_tie_with_mixed_times():
    rows = [
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a1", rank=1, status="FIN"),
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a2", rank=2, status="FIN"),
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a3", rank=3, status="FIN"),
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a4", rank=3, status="FIN"),
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a5", rank=3, status="FIN"),
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a6", rank=3, status="FIN"),
        _ledger_row(race_date="20250321", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a7", rank=3, status="FIN"),
    ]
    rows[2]["time_sec"] = 100.0
    rows[3]["time_sec"] = 101.0
    with pytest.raises(ValueError, match="한 순위에"):
        validate_ledger(pl.DataFrame(rows))


def test_race_sequence_fallback_is_deterministic():
    rows = [
        {
            "race_id": "r2",
            "race_seq_num": None,
            "date": "2024-01-01",
            "season_year": 2024,
            "meet_id": "m1",
            "event": "1000m",
            "round": "예선2조Heat 2",
            "round_kind": "예선",
            "round_class": "heat",
            "distance_text": "1000",
        },
        {
            "race_id": "r1",
            "race_seq_num": None,
            "date": "2024-01-01",
            "season_year": 2024,
            "meet_id": "m1",
            "event": "500m",
            "round": "예선1조Heat 1",
            "round_kind": "예선",
            "round_class": "heat",
            "distance_text": "500",
        },
    ]
    first = build_race_sequence_map(pl.DataFrame(rows))
    second = build_race_sequence_map(pl.DataFrame(list(reversed(rows))))
    assert first == second
    assert set(first.keys()) == {"r1", "r2"}
    assert sorted(first.values()) == [1, 2]


def test_rebuild_hashes_are_identical_for_same_input(tmp_path: Path):
    rows = [
        {
            "race_id": "r1",
            "athlete_hash": "a1",
            "라운드": "결승Final",
            "라운드종류": "결승",
            "순위": "1",
            "기록_초": "43.1",
            "사유": "",
            "대회연도": "2024",
            "종별": "남자초등부",
            "대회명": "쇼트트랙 테스트",
            "classCd": "2",
            "toCd": "2024001",
            "일자": "2024-01-01",
        },
        {
            "race_id": "r1",
            "athlete_hash": "a2",
            "라운드": "결승Final",
            "라운드종류": "결승",
            "순위": "2",
            "기록_초": "43.3",
            "사유": "",
            "대회연도": "2024",
            "종별": "남자초등부",
            "대회명": "쇼트트랙 테스트",
            "classCd": "2",
            "toCd": "2024001",
            "일자": "2024-01-01",
        },
    ]

    policy = CONSERVATIVE
    prepared_first = _prepare_rows_for_policy(pl.DataFrame(rows), policy)[1]
    prepared_second = _prepare_rows_for_policy(pl.DataFrame(list(reversed(rows))), policy)[1]
    ledger_first = _build_race_ledger(prepared_first, "conservative", policy)
    ledger_second = _build_race_ledger(prepared_second, "conservative", policy)
    assert ledger_first.to_dicts() == ledger_second.to_dicts()

    out_dir = tmp_path / "race_ledger"
    _write_partitioned(ledger_first, out_dir, ["ordering_key", "athlete_id"])
    first_hashes = _snapshot_parquet_hashes(out_dir)
    _write_partitioned(ledger_second, out_dir, ["ordering_key", "athlete_id"])
    second_hashes = _snapshot_parquet_hashes(out_dir)
    assert first_hashes == second_hashes


def test_build_athlete_meta_summarizes_debut_and_birth_year():
    frame = pl.DataFrame(
        [
            {"athlete_id": "a1", "season_year": 2023, "birth_year": 2013, "gender": "남", "division_text": "초등"},
            {"athlete_id": "a1", "season_year": 2023, "birth_year": 2013, "gender": "남", "division_text": "초등"},
            {"athlete_id": "a1", "season_year": 2024, "birth_year": 2013, "gender": "남", "division_text": "중등"},
            {"athlete_id": "a2", "season_year": 2025, "birth_year": None, "gender": "", "division_text": ""},
        ]
    )
    meta = _build_athlete_meta(frame)
    assert meta.columns == ["athlete_id", "birth_year", "sex", "debut_season", "debut_division", "last_season", "n_seasons"]
    got = {row["athlete_id"]: row for row in meta.to_dicts()}
    assert got["a1"]["birth_year"] == 2013
    assert got["a1"]["sex"] == "남"
    assert got["a1"]["debut_season"] == 2023
    assert got["a1"]["debut_division"] == "초등"
    assert got["a1"]["last_season"] == 2024
    assert got["a1"]["n_seasons"] == 2
    assert got["a2"]["birth_year"] is None
    assert got["a2"]["debut_season"] == 2025


def test_build_athlete_meta_rejects_birth_year_conflict():
    frame = pl.DataFrame(
        [
            {"athlete_id": "a1", "season_year": 2024, "birth_year": 2012, "gender": "남", "division_text": "초등"},
            {"athlete_id": "a1", "season_year": 2025, "birth_year": 2013, "gender": "남", "division_text": "중등"},
        ]
    )
    with pytest.raises(ValueError, match="출생연도 충돌"):
        _build_athlete_meta(frame)


def test_merge_external_athlete_meta_fills_missing_fields():
    base = pl.DataFrame(
        [
            {
                "athlete_id": "a1",
                "birth_year": None,
                "sex": "",
                "debut_season": 2023,
                "debut_division": "초등",
                "last_season": 2024,
                "n_seasons": 2,
            }
        ]
    )
    external = pl.DataFrame([{"athlete_id": "a1", "birth_year": 2013, "sex": "남"}])
    merged = _merge_external_athlete_meta(base, external)
    row = merged.row(0, named=True)
    assert row["birth_year"] == 2013
    assert row["sex"] == "남"


def test_merge_external_athlete_meta_rejects_conflict():
    base = pl.DataFrame(
        [
            {
                "athlete_id": "a1",
                "birth_year": 2012,
                "sex": "남",
                "debut_season": 2023,
                "debut_division": "초등",
                "last_season": 2024,
                "n_seasons": 2,
            }
        ]
    )
    external = pl.DataFrame([{"athlete_id": "a1", "birth_year": 2013, "sex": "남"}])
    with pytest.raises(ValueError, match="출생연도 충돌"):
        _merge_external_athlete_meta(base, external)
