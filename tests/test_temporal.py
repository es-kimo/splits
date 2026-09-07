from __future__ import annotations

from datetime import date
from pathlib import Path
from time import perf_counter

import polars as pl
import pytest

from rating.engine.runner import run_replay
from rating.engine.types import RaceEntry, RaceResult
from rating.ledger.ordering import make_ordering_key, make_race_ordering_key
from rating.query.smoother import _with_reflected_date
from rating.query.temporal import (
    FilteredRating,
    SmoothedRating,
    compare_filter_smoother,
    rating_as_of,
    rating_retrospective,
)
from rating.replay.registry import RatingRegistry


def _row(
    *,
    race_date: str,
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


def _write_ledger(root: Path, *, include_future: bool) -> Path:
    rows = [
        _row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a1", rank=1),
        _row(race_date="20240101", meet_id="m1", race_seq=1, race_id="r1", athlete_id="a2", rank=2),
        _row(race_date="20240110", meet_id="m2", race_seq=1, race_id="r2", athlete_id="a1", rank=1),
        _row(race_date="20240110", meet_id="m2", race_seq=1, race_id="r2", athlete_id="a2", rank=2),
    ]
    if include_future:
        rows.extend(
            [
                _row(race_date="20240301", meet_id="m3", race_seq=1, race_id="r3", athlete_id="a2", rank=1),
                _row(race_date="20240301", meet_id="m3", race_seq=1, race_id="r3", athlete_id="a1", rank=2),
            ]
        )
    ledger_root = root / "ledger" / "race_ledger" / "season=2024"
    ledger_root.mkdir(parents=True)
    pl.DataFrame(rows).write_parquet(ledger_root / "part.parquet")
    return root / "ledger"


def _registered_replay(ledger: Path, registry_root: Path):
    return run_replay(
        ledger_path=ledger,
        output_path=registry_root / "unused.parquet",
        report_path=registry_root / "unused.md",
        engine_name="trueskill",
        registry_root=registry_root,
    )


def test_rating_as_of_never_uses_later_races(tmp_path: Path):
    initial_ledger = _write_ledger(tmp_path / "initial", include_future=False)
    initial_registry = RatingRegistry(tmp_path / "initial-runs")
    initial_run = _registered_replay(initial_ledger, initial_registry.root)
    initial = rating_as_of("a1", date(2024, 1, 10), initial_run.run_id, registry=initial_registry)

    extended_ledger = _write_ledger(tmp_path / "extended", include_future=True)
    extended_registry = RatingRegistry(tmp_path / "extended-runs")
    extended_run = _registered_replay(extended_ledger, extended_registry.root)
    extended = rating_as_of("a1", date(2024, 1, 10), extended_run.run_id, registry=extended_registry)

    assert initial.mu == pytest.approx(extended.mu)
    assert initial.sigma == pytest.approx(extended.sigma)
    assert initial.as_of == extended.as_of == date(2024, 1, 10)
    assert initial.run_id != extended.run_id


def test_temporal_queries_are_indexed_and_types_are_separate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ledger = _write_ledger(tmp_path, include_future=True)
    registry = RatingRegistry(tmp_path / "runs")
    result = _registered_replay(ledger, registry.root)

    calls = 0
    original = registry.filtered_snapshot_as_of

    def indexed_lookup(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(registry, "filtered_snapshot_as_of", indexed_lookup)
    started = perf_counter()
    filtered = rating_as_of("a1", date(2024, 1, 10), result.run_id, registry=registry)
    elapsed = perf_counter() - started
    smoothed = rating_retrospective("a1", date(2024, 1, 10), result.run_id, registry=registry)

    assert calls == 1
    assert elapsed < 0.1
    assert isinstance(filtered, FilteredRating)
    assert isinstance(smoothed, SmoothedRating)
    assert filtered.run_id == smoothed.run_id == result.run_id
    assert smoothed.valid_date <= date(2024, 1, 10)
    assert smoothed.sigma < filtered.sigma
    assert registry.load_smoothed_snapshots(result.run_id).snapshots.height == result.smoothed_snapshots.height
    with pytest.raises(LookupError, match="필터 레이팅"):
        rating_as_of("a1", date(2023, 12, 31), result.run_id, registry=registry)
    report = compare_filter_smoother(
        athlete_ids=["a1"],
        run_id=result.run_id,
        registry=registry,
    )
    assert "| a1 |" in report
    assert "회고 분석 전용" in report


def test_reflected_reverse_races_keep_results_unchanged():
    original = _row(race_date="20240110", meet_id="m2", race_seq=1, race_id="r2", athlete_id="a1", rank=1)
    opponent = _row(race_date="20240110", meet_id="m2", race_seq=1, race_id="r2", athlete_id="a2", rank=2)
    race = RaceResult(
        race_id="r2",
        race_date=date(2024, 1, 10),
        meet_id="m2",
        entries=tuple(
            RaceEntry(
                athlete_id=str(row["athlete_id"]),
                rank=int(row["rank"]),
                status=str(row["status"]),
            )
            for row in (original, opponent)
        ),
    )

    reflected = _with_reflected_date(race, date(2024, 1, 1), date(2024, 3, 1))

    assert reflected.race_date == date(2024, 2, 21)
    assert reflected.entries == race.entries
