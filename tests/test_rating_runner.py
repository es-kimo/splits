import hashlib
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.engine.runner import run_replay
from rating.ledger.ordering import make_ordering_key, make_race_ordering_key


def _ledger_row(
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
        "place_num": rank,
        "time_sec": 43.0 + rank,
        "weight": 1.0,
    }


def _build_ledger_dir(tmp_path: Path) -> Path:
    rows = [
        _ledger_row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a1", rank=1),
        _ledger_row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a2", rank=2),
        _ledger_row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a3", rank=3),
        _ledger_row(race_date="20240110", meet_id="m2", race_seq=1, race_id="r2", athlete_id="a1", rank=1),
        _ledger_row(race_date="20240110", meet_id="m2", race_seq=1, race_id="r2", athlete_id="a2", rank=2),
        _ledger_row(race_date="20240205", meet_id="m3", race_seq=1, race_id="r3", athlete_id="a2", rank=1),
        _ledger_row(race_date="20240205", meet_id="m3", race_seq=1, race_id="r3", athlete_id="a3", rank=2),
    ]
    frame = pl.DataFrame(rows)
    race_root = tmp_path / "ledger" / "race_ledger" / "season=2024"
    race_root.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(race_root / "part.parquet")
    return tmp_path / "ledger"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_run_replay_generates_snapshot_and_report(tmp_path: Path):
    ledger_dir = _build_ledger_dir(tmp_path)
    out_path = tmp_path / "out" / "ratings_baseline.parquet"
    report_path = tmp_path / "out" / "baseline_report.md"
    result = run_replay(ledger_path=ledger_dir, output_path=out_path, report_path=report_path, engine_name="glicko2")

    assert result.race_count == 3
    assert result.period_count == 3
    assert out_path.exists()
    assert report_path.exists()

    out = pl.read_parquet(out_path)
    assert out.columns == ["athlete_id", "valid_date", "mu", "phi", "sigma", "n_games"]
    assert out.height > 0
    assert "phi > 300 선수 비율" in report_path.read_text(encoding="utf-8")


def test_run_replay_is_byte_deterministic(tmp_path: Path):
    ledger_dir = _build_ledger_dir(tmp_path)
    out_a = tmp_path / "run-a.parquet"
    out_b = tmp_path / "run-b.parquet"
    report_a = tmp_path / "report-a.md"
    report_b = tmp_path / "report-b.md"

    run_replay(ledger_path=ledger_dir, output_path=out_a, report_path=report_a, engine_name="glicko2")
    run_replay(ledger_path=ledger_dir, output_path=out_b, report_path=report_b, engine_name="glicko2")

    assert _digest(out_a) == _digest(out_b)


def test_month_period_collapses_same_month_meets(tmp_path: Path):
    ledger_dir = _build_ledger_dir(tmp_path)
    meet_out = tmp_path / "meet.parquet"
    month_out = tmp_path / "month.parquet"
    meet_report = tmp_path / "meet.md"
    month_report = tmp_path / "month.md"

    meet_result = run_replay(
        ledger_path=ledger_dir,
        output_path=meet_out,
        report_path=meet_report,
        engine_name="glicko2",
        rating_period="meet",
    )
    month_result = run_replay(
        ledger_path=ledger_dir,
        output_path=month_out,
        report_path=month_report,
        engine_name="glicko2",
        rating_period="month",
    )

    assert meet_result.period_count == 3
    assert month_result.period_count == 2

