import sqlite3
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from rating.replay.registry import RatingRegistry
from rating.replay.snapshot import run_id
from server.deps import ApiConfig, open_registry_readonly
from server.main import create_app
from server.opaque_ids import sync_active_opaque_ids


def _complete_run(registry: RatingRegistry, seed: str, snapshots: pl.DataFrame) -> str:
    engine_params = {"engine": "trueskill", "seed": seed}
    calibrator_spec = {"method": "platt", "slope": 1.0, "intercept": 0.0}
    selected_run_id = run_id(
        algo_version="rating.replay.v6",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_id="a" * 64,
    )
    registry.begin(
        run_id=selected_run_id,
        algo_version="rating.replay.v6",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_snapshot_id="a" * 64,
        git_sha="test",
    )
    registry.complete(selected_run_id, snapshots, smoothed_snapshots=snapshots)
    return selected_run_id


def _snapshots() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "athlete_id": ["internal-athlete-hash", "internal-athlete-hash", "new-athlete-hash"],
            "valid_date": [date(2025, 1, 1), date(2025, 2, 1), date(2025, 2, 1)],
            "mu": [25.0, 27.4, 24.0],
            "sigma": [3.0, 2.31, 7.0],
            "n_games": [6, 23, 5],
        }
    )


def _client_config(tmp_path: Path) -> tuple[ApiConfig, str, str, RatingRegistry]:
    registry = RatingRegistry(tmp_path / "rating-runs")
    selected_run_id = _complete_run(registry, "first", _snapshots())
    opaque_by_athlete = sync_active_opaque_ids(
        tmp_path / "private" / "opaque_ids.sqlite",
        ["internal-athlete-hash", "new-athlete-hash"],
    )
    age_adjusted = tmp_path / "age-adjusted.parquet"
    pl.DataFrame(
        {
            "run_id": [selected_run_id],
            "athlete_id": ["internal-athlete-hash"],
            "valid_date": [date(2025, 2, 1)],
            "z": [0.42],
        }
    ).write_parquet(age_adjusted)
    return (
        ApiConfig(
            registry_root=registry.root,
            opaque_id_db=tmp_path / "private" / "opaque_ids.sqlite",
            age_adjusted_path=age_adjusted,
        ),
        opaque_by_athlete["internal-athlete-hash"],
        opaque_by_athlete["new-athlete-hash"],
        registry,
    )


def test_rating_response_has_provenance_freshness_and_no_internal_identifier(tmp_path: Path):
    config, opaque_id, _new_opaque_id, _registry = _client_config(tmp_path)
    with TestClient(create_app(config, today=date(2025, 2, 4))) as client:
        response = client.get(f"/v1/athletes/{opaque_id}/rating", params={"as_of": "2025-02-02"})
        trajectory = client.get(f"/v1/athletes/{opaque_id}/trajectory")

    assert response.status_code == 200
    assert trajectory.status_code == 200
    payload = response.json()
    assert payload["value"] == {"mu": 27.4, "sigma": 2.31, "z_vs_age": 0.42}
    assert payload["confidence"] == "high"
    assert payload["n_games"] == 23
    assert payload["provenance"]["mode"] == "filtered"
    assert payload["provenance"]["calibrator"] == "platt-v1"
    assert payload["freshness"] == {"data_as_of": "2025-02-01", "stale_days": 3}
    assert "internal-athlete-hash" not in response.text
    assert trajectory.json()["provenance"]["mode"] == "filtered"
    assert "internal-athlete-hash" not in trajectory.text


def test_new_athlete_hides_rating_numbers(tmp_path: Path):
    config, _opaque_id, new_opaque_id, _registry = _client_config(tmp_path)
    with TestClient(create_app(config)) as client:
        response = client.get(f"/v1/athletes/{new_opaque_id}/rating", params={"as_of": "2025-02-01"})

    assert response.status_code == 200
    assert response.json()["value"] is None
    assert response.json()["confidence"] == "low"
    assert response.json()["message"] == "아직 판단하기 이릅니다 (경기 5회)"


def test_api_pins_current_run_and_rejects_smoothed_mode(tmp_path: Path):
    config, opaque_id, _new_opaque_id, registry = _client_config(tmp_path)
    first = registry.current_run_id()
    second = _complete_run(
        registry,
        "second",
        pl.DataFrame(
            {
                "athlete_id": ["internal-athlete-hash"],
                "valid_date": [date(2025, 3, 1)],
                "mu": [30.0],
                "sigma": [2.0],
                "n_games": [30],
            }
        ),
    )
    registry.publish(first)

    with TestClient(create_app(config)) as client:
        registry.publish(second)
        current = client.get("/v1/runs/current")
        rejected = client.get(
            f"/v1/athletes/{opaque_id}/trajectory",
            params={"mode": "smoothed"},
        )
        openapi = client.get("/openapi.json")

    assert current.status_code == 200
    assert current.json()["run_id"] == first
    assert rejected.status_code == 422
    assert "/v1/athletes/{opaque_id}/rating" in openapi.json()["paths"]


def test_registry_connection_is_physically_read_only(tmp_path: Path):
    config, _opaque_id, _new_opaque_id, _registry = _client_config(tmp_path)
    with open_registry_readonly(config.registry_root) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM rating_run")
