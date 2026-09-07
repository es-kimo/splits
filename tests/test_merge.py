from datetime import date
import subprocess
import sys

import polars as pl
import pytest

from rating.ledger.ordering import make_ordering_key, make_race_ordering_key
from rating.replay.blast_radius import (
    RaceHypergraph,
    affected_athletes,
    load_confirmed_merges,
    measure,
    render_report,
    sample_merges,
)
from rating.replay.merge import IdentityMerge, apply_identity_merge, materialize_identity_merge, replay_after_identity_merge
from rating.replay.orchestrator import ReplayParams, replay


def _row(race_date: str, season_year: int, race_id: str, athlete_id: str, rank: int) -> dict[str, object]:
    return {
        "ordering_key": make_ordering_key(
            {
                "race_date": race_date,
                "meet_id": race_id,
                "race_seq": 1,
                "race_id": race_id,
                "rank": rank,
                "athlete_id": athlete_id,
            }
        ),
        "race_ordering_key": make_race_ordering_key(
            {"race_date": race_date, "meet_id": race_id, "race_seq": 1, "race_id": race_id}
        ),
        "race_id": race_id,
        "athlete_id": athlete_id,
        "rank": rank,
        "status": "FIN",
        "race_date": race_date,
        "season_year": season_year,
        "meet_id": race_id,
        "race_seq": 1,
        "event": "500m",
        "round": "결승Final",
        "round_kind": "결승",
        "round_class": "final",
        "place_num": rank,
        "time_sec": 40.0 + rank,
        "weight": 1.0,
    }


def _ledger(tmp_path) -> tuple[pl.DataFrame, object]:
    races = [
        ("20230110", 2022, "r1", ("historic-a", "historic-b")),
        ("20231010", 2023, "r2", ("historic-a", "historic-c")),
        ("20240101", 2023, "r3", ("primary", "c")),
        ("20240110", 2023, "r4", ("secondary", "d", "e")),
        ("20240210", 2023, "r5", ("e", "f")),
        ("20240310", 2023, "r6", ("f", "g")),
        ("20240410", 2023, "r7", ("g", "h")),
        ("20240415", 2023, "r8", ("isolated-a", "isolated-b")),
    ]
    frame = pl.DataFrame(
        [
            _row(race_date, season_year, race_id, athlete_id, rank)
            for race_date, season_year, race_id, athlete_ids in races
            for rank, athlete_id in enumerate(athlete_ids, start=1)
        ]
    )
    root = tmp_path / "ledger"
    race_root = root / "race_ledger" / "season=2022"
    race_root.mkdir(parents=True)
    frame.write_parquet(race_root / "part.parquet")
    return frame, root


def test_affected_athletes_expands_by_race_hyperedge(tmp_path):
    frame, _ = _ledger(tmp_path)
    graph = RaceHypergraph.from_ledger(frame)

    hops = list(affected_athletes(date(2024, 1, 10), ("primary", "secondary"), graph))

    assert hops == [{"d", "e"}, {"f"}, {"g"}, {"h"}]


def test_measure_reports_reach_threshold_and_synthetic_samples(tmp_path):
    frame, _ = _ledger(tmp_path)
    graph = RaceHypergraph.from_ledger(frame)
    sample = measure(graph, (IdentityMerge("primary", "secondary"),))[0]

    assert sample.population_size == 10
    assert sample.hop_to_ninety_percent is None
    assert len(sample_merges(graph, 3)) == 3
    report = render_report((sample,))
    assert "하이퍼엣지" in report
    assert "미도달" in report
    assert "| 1 | 4 |" in report


def test_confirmed_merge_history_is_used_when_its_ids_are_in_the_ledger(tmp_path):
    frame, _ = _ledger(tmp_path)
    history_path = tmp_path / "id_merges.csv"
    history_path.write_text("부idNo,주idNo\nsecondary,primary\n", encoding="utf-8")

    assert load_confirmed_merges(history_path, RaceHypergraph.from_ledger(frame)) == (IdentityMerge("primary", "secondary"),)


def test_merge_rejects_same_race_identity_collision(tmp_path):
    frame, _ = _ledger(tmp_path)
    collision = pl.concat([frame, pl.DataFrame([_row("20240110", 2023, "r4", "primary", 4)])])

    with pytest.raises(ValueError, match="같은 race에 같은 선수"):
        apply_identity_merge(collision, IdentityMerge("primary", "secondary"))


def test_blast_radius_cli_writes_report(tmp_path):
    _, ledger_path = _ledger(tmp_path)
    report_path = tmp_path / "blast_radius.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rating.replay.blast_radius",
            "--ledger",
            str(ledger_path),
            "--sample-merges",
            "3",
            "--skip-replay-timing",
            "--out",
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "[ok] report=" in completed.stdout
    report = report_path.read_text(encoding="utf-8")
    assert "같은 race의 모든 공동 참가자" in report
    assert "| 3 |" in report


@pytest.mark.parametrize("params", [ReplayParams(engine_name="glicko2", tau=0.5), ReplayParams()])
def test_partial_merge_replay_matches_cold_merged_replay_and_unmerge(tmp_path, params):
    _, ledger_path = _ledger(tmp_path)
    checkpoints = tmp_path / "checkpoints"
    original = replay(ledger_path, params, checkpoint_root=checkpoints)
    merge = IdentityMerge("primary", "secondary")

    resumed = replay_after_identity_merge(
        ledger_path,
        merge,
        params,
        checkpoint_root=checkpoints,
        baseline_final_state=original.final_state,
    )
    merged_path = materialize_identity_merge(ledger_path, tmp_path / "merged", merge)
    cold_merged = replay(merged_path, params, checkpoint_root=tmp_path / "cold")
    unmerged = replay(ledger_path, params, checkpoint_root=tmp_path / "unmerged")

    assert resumed.resumed_from is not None
    assert resumed.replay.state_digest() == cold_merged.state_digest()
    assert resumed.replay.final_state == cold_merged.final_state
    assert resumed.replay.race_count < cold_merged.race_count
    assert unmerged.state_digest() == original.state_digest()
