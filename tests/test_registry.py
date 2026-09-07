import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rating.replay.registry import RatingRegistry, RegistryError, RegisteredSnapshots, require_single_run
from rating.replay.snapshot import canonical_json, input_snapshot_id, run_id


def _snapshots() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "athlete_id": ["athlete-b", "athlete-a"],
            "valid_date": [date(2024, 1, 2), date(2024, 1, 1)],
            "mu": [24.5, 25.5],
            "sigma": [7.5, 8.5],
            "n_games": [2, 1],
        }
    )


def _begin(registry: RatingRegistry, seed: str) -> str:
    engine_params = {"tau": 0.08333333333333333, "engine": "trueskill", "seed": seed}
    calibrator_spec = {"method": "platt", "slope": 1.0, "intercept": 0.0}
    run_id_value = run_id(
        algo_version="rating.replay.v2",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_id="a" * 64,
    )
    registry.begin(
        run_id=run_id_value,
        algo_version="rating.replay.v2",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_snapshot_id="a" * 64,
        git_sha="test",
    )
    return run_id_value


def test_canonical_json_is_order_independent_and_uses_fixed_floats():
    assert canonical_json({"b": 1.5, "a": [True, 0.1]}) == canonical_json({"a": [True, 0.1], "b": 1.5})
    small = canonical_json({"value": 1e-20})
    assert "1e-" not in small
    assert small != canonical_json({"value": 0.0})


def test_content_address_changes_for_all_identity_inputs():
    base = {
        "algo_version": "rating.replay.v2",
        "engine_params": {"engine": "trueskill", "tau": 0.1},
        "calibrator_spec": {"method": "platt", "slope": 1.0, "intercept": 0.0},
        "input_id": "a" * 64,
    }
    stable = run_id(**base)
    assert stable == run_id(
        algo_version=base["algo_version"],
        engine_params={"tau": 0.1, "engine": "trueskill"},
        calibrator_spec={"intercept": 0.0, "method": "platt", "slope": 1.0},
        input_id=base["input_id"],
    )
    assert stable != run_id(**{**base, "engine_params": {"engine": "trueskill", "tau": 0.2}})
    assert stable != run_id(
        **{**base, "calibrator_spec": {"method": "platt", "slope": 1.1, "intercept": 0.0}}
    )
    assert stable != run_id(**{**base, "input_id": "b" * 64})


def test_input_snapshot_hashes_content_not_mtime(tmp_path: Path):
    ledger = tmp_path / "ledger"
    nested = ledger / "race_ledger"
    nested.mkdir(parents=True)
    source = nested / "part.parquet"
    source.write_bytes(b"first")
    before = input_snapshot_id(ledger)
    os.utime(source, (1_700_000_000, 1_700_000_000))
    assert input_snapshot_id(ledger) == before
    source.write_bytes(b"second")
    assert input_snapshot_id(ledger) != before


def test_registry_excludes_failed_runs_and_pins_current_snapshot(tmp_path: Path):
    registry = RatingRegistry(tmp_path / "rating-runs")
    first = _begin(registry, "first")
    registry.complete(first, _snapshots(), metrics={"race_count": 2})
    loaded = registry.load_snapshots()
    assert loaded.run_id == first
    assert loaded.snapshots.columns == ["athlete_id", "valid_date", "mu", "sigma", "n_games"]

    failed = _begin(registry, "failed")
    (registry.run_directory(failed) / "partial.txt").write_text("debug", encoding="utf-8")
    registry.fail(failed, "simulated error")
    assert [run.run_id for run in registry.list_runs()] == [first]
    assert (registry.run_directory(failed) / "partial.txt").exists()

    second = _begin(registry, "second")
    registry.complete(second, _snapshots())
    assert loaded.run_id == first
    assert registry.load_snapshots().run_id == second


def test_registry_rejects_incomplete_publication_and_mixed_runs(tmp_path: Path):
    registry = RatingRegistry(tmp_path / "rating-runs")
    running = _begin(registry, "running")
    with pytest.raises(RegistryError, match="완료되지 않은"):
        registry.publish(running)

    completed = _begin(registry, "completed")
    registry.complete(completed, _snapshots())
    first = registry.load_snapshots(completed)
    second = RegisteredSnapshots(run_id=running, snapshots=_snapshots())
    with pytest.raises(RegistryError, match="서로 다른 실행"):
        require_single_run(first, second)


def test_algorithm_version_guard_requires_version_file_for_engine_changes():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_rating_algorithm_version.py"
    failed = subprocess.run(
        [sys.executable, str(script), "--changed-file", "rating/engine/trueskill_wrapper.py"],
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    passed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--changed-file",
            "rating/engine/trueskill_wrapper.py",
            "--changed-file",
            "rating/replay/version.py",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "passed" in passed.stdout
