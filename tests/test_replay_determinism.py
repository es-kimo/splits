import subprocess
import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rating.engine.glicko2 import Rating
from rating.ledger.ordering import make_ordering_key, make_race_ordering_key
from rating.replay.checkpoint import CheckpointError, checkpoint_id, find_nearest, load, params_digest, save
from rating.replay.orchestrator import ReplayParams, replay


def _ledger_row(
    *,
    race_date: str,
    season_year: int,
    meet_id: str,
    race_seq: int,
    race_id: str,
    athlete_id: str,
    rank: int,
) -> dict[str, object]:
    return {
        "ordering_key": make_ordering_key(
            {
                "race_date": race_date,
                "meet_id": meet_id,
                "race_seq": race_seq,
                "race_id": race_id,
                "rank": rank,
                "athlete_id": athlete_id,
            }
        ),
        "race_ordering_key": make_race_ordering_key(
            {"race_date": race_date, "meet_id": meet_id, "race_seq": race_seq, "race_id": race_id}
        ),
        "race_id": race_id,
        "athlete_id": athlete_id,
        "rank": rank,
        "status": "FIN",
        "race_date": race_date,
        "season_year": season_year,
        "meet_id": meet_id,
        "race_seq": race_seq,
        "event": "500m",
        "round": "결승Final",
        "round_kind": "결승",
        "round_class": "final",
        "place_num": rank,
        "time_sec": 43.0 + rank,
        "weight": 1.0,
    }


def _ledger_path(tmp_path: Path) -> Path:
    races = [
        ("20230110", 2022, "m1", "r1", ("a1", "a2", "a3")),
        ("20231010", 2023, "m2", "r2", ("a2", "a1", "a3")),
        ("20240210", 2023, "m3", "r3", ("a1", "a3", "a2")),
        ("20240910", 2024, "m4", "r4", ("a3", "a2", "a1")),
    ]
    rows = [
        _ledger_row(
            race_date=race_date,
            season_year=season_year,
            meet_id=meet_id,
            race_seq=1,
            race_id=race_id,
            athlete_id=athlete_id,
            rank=rank,
        )
        for race_date, season_year, meet_id, race_id, athlete_ids in races
        for rank, athlete_id in enumerate(athlete_ids, start=1)
    ]
    ledger = tmp_path / "ledger" / "race_ledger" / "season=2022"
    ledger.mkdir(parents=True)
    pl.DataFrame(rows).write_parquet(ledger / "part.parquet")
    return ledger.parent.parent


def test_replay_resume_matches_full_state_byte_for_byte(tmp_path: Path):
    ledger_path = _ledger_path(tmp_path)
    checkpoint_root = tmp_path / "checkpoints"
    params = ReplayParams(engine_name="glicko2", tau=0.5)

    full = replay(ledger_path, params, checkpoint_root=checkpoint_root)
    checkpoint = find_nearest(
        date(2024, 5, 1),
        params.algorithm_version,
        full.params_hash,
        full.input_hash,
        root=checkpoint_root,
    )
    assert checkpoint is not None

    resumed = replay(ledger_path, params, from_checkpoint=checkpoint, checkpoint_root=checkpoint_root)

    assert resumed.resumed_from == checkpoint
    assert resumed.state_digest() == full.state_digest()
    assert resumed.final_state == full.final_state


def test_replay_only_saves_completed_season_checkpoints(tmp_path: Path):
    ledger_path = _ledger_path(tmp_path)
    checkpoint_root = tmp_path / "checkpoints"
    params = ReplayParams(engine_name="glicko2", tau=0.5)

    partial = replay(
        ledger_path,
        params,
        until=date(2023, 11, 1),
        checkpoint_root=checkpoint_root,
    )

    assert [checkpoint.cutoff_date for checkpoint in partial.saved_checkpoints] == [date(2023, 1, 10)]


def test_checkpoint_round_trip_preserves_full_rating_state(tmp_path: Path):
    root = tmp_path / "checkpoints"
    cutoff = date(2024, 6, 30)
    params_hash = params_digest({"engine": "trueskill", "tau": 0.08333333333333333})
    cid = checkpoint_id("rating.replay.v1", params_hash, "input-hash", cutoff)
    state = {
        "athlete-a": Rating(25.125, 8.333333333333334, 0.0, date(2024, 2, 3), 11),
        "athlete-b": Rating(24.875, 7.125, 0.06, None, 4),
    }

    save(
        state,
        cid,
        root=root,
        algorithm_version="rating.replay.v1",
        params_hash=params_hash,
        input_hash="input-hash",
        cutoff_date=cutoff,
    )

    assert load(cid, root=root) == state


def test_checkpoint_identity_changes_for_all_cache_inputs():
    params_hash = params_digest({"engine": "trueskill", "tau": 0.1})
    assert checkpoint_id("v1", params_hash, "input-a", date(2024, 6, 30)) != checkpoint_id(
        "v2", params_hash, "input-a", date(2024, 6, 30)
    )
    assert checkpoint_id("v1", params_hash, "input-a", date(2024, 6, 30)) != checkpoint_id(
        "v1", params_digest({"engine": "trueskill", "tau": 0.2}), "input-a", date(2024, 6, 30)
    )
    assert checkpoint_id("v1", params_hash, "input-a", date(2024, 6, 30)) != checkpoint_id(
        "v1", params_hash, "input-b", date(2024, 6, 30)
    )
    assert checkpoint_id("v1", params_hash, "input-a", date(2024, 6, 30)) != checkpoint_id(
        "v1", params_hash, "input-a", date(2025, 6, 30)
    )


def test_replay_rejects_stale_checkpoint(tmp_path: Path):
    ledger_path = _ledger_path(tmp_path)
    checkpoint_root = tmp_path / "checkpoints"
    original = ReplayParams(engine_name="glicko2", tau=0.5)
    first = replay(ledger_path, original, checkpoint_root=checkpoint_root)
    stale = first.saved_checkpoints[0]

    with pytest.raises(CheckpointError, match="호환되지 않습니다"):
        replay(
            ledger_path,
            ReplayParams(engine_name="glicko2", tau=0.6),
            from_checkpoint=stale,
            checkpoint_root=checkpoint_root,
        )


def test_cli_writes_benchmark_report(tmp_path: Path):
    ledger_path = _ledger_path(tmp_path)
    report_path = tmp_path / "replay_bench.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rating.replay.orchestrator",
            "--ledger",
            str(ledger_path),
            "--engine",
            "glicko2",
            "--bench",
            "--out",
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "[ok] benchmark=" in completed.stdout
    report = report_path.read_text(encoding="utf-8")
    assert "전체 리플레이(콜드)" in report
    assert "최대 메모리" in report
    assert "프로파일 상위 항목" in report
