import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

import polars as pl

from rating.replay.registry import RatingRegistry
from rating.replay.snapshot import run_id


ROOT = Path(__file__).resolve().parents[1]
BUILD_STATIC_PATH = ROOT / "site" / "build_static.py"


def _build_static_module():
    spec = importlib.util.spec_from_file_location("splits_build_static", BUILD_STATIC_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _complete_run(registry: RatingRegistry, snapshots: pl.DataFrame) -> str:
    engine_params = {"engine": "trueskill", "seed": "static"}
    calibrator_spec = {"method": "platt", "slope": 1.0, "intercept": 0.0}
    selected_run_id = run_id(
        algo_version="rating.replay.v6",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_id="b" * 64,
    )
    registry.begin(
        run_id=selected_run_id,
        algo_version="rating.replay.v6",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_snapshot_id="b" * 64,
        git_sha="test",
    )
    registry.complete(selected_run_id, snapshots, smoothed_snapshots=snapshots)
    return selected_run_id


def test_static_artifacts_hide_small_cohorts_and_internal_ids(tmp_path: Path):
    salt = "test-salt"
    public_figures = tmp_path / "public_figures.csv"
    public_rows = ["idNo,상태"]
    athlete_ids = []
    for number in range(10):
        id_no = f"public-{number}"
        public_rows.append(f"{id_no},active")
        athlete_ids.append(hashlib.sha256(f"{id_no}{salt}".encode("utf-8")).hexdigest()[:12])
    public_figures.write_text("\n".join(public_rows) + "\n", encoding="utf-8")

    small_cohort_ids = ["small-cohort-hash-1", "small-cohort-hash-2"]
    snapshots = pl.DataFrame(
        {
            "athlete_id": athlete_ids + small_cohort_ids,
            "valid_date": [date(2025, 2, 1)] * 12,
            "mu": [20.0 + number for number in range(12)],
            "sigma": [2.5] * 12,
            "n_games": [10] * 12,
        }
    )
    registry = RatingRegistry(tmp_path / "rating-runs")
    _complete_run(registry, snapshots)

    ledger = tmp_path / "ledger" / "race_ledger"
    ledger.mkdir(parents=True)
    pl.DataFrame(
        {
            "athlete_id": athlete_ids + small_cohort_ids,
            "season_year": [2025] * 12,
            "gender": ["남"] * 12,
            "grade_text": ["초5"] * 10 + ["초6"] * 2,
        }
    ).write_parquet(ledger / "part.parquet")

    output_root = tmp_path / "static"
    build_static = _build_static_module()
    build_static.build_static_artifacts(
        registry_root=registry.root,
        opaque_id_db=tmp_path / "private" / "opaque_ids.sqlite",
        public_figures=public_figures,
        ledger=ledger.parent,
        output_root=output_root,
        salt=salt,
    )

    cohort = json.loads((output_root / "cohort" / "남" / "초5" / "2025.json").read_text(encoding="utf-8"))
    assert cohort["sample_size"] == 10
    assert not (output_root / "cohort" / "남" / "초6" / "2025.json").exists()

    trajectories = list((output_root / "athlete").glob("*.json"))
    assert len(trajectories) == 10
    payloads = "\n".join(path.read_text(encoding="utf-8") for path in trajectories)
    assert all(athlete_id not in payloads for athlete_id in athlete_ids)
    assert '"mode":"smoothed"' in payloads


def test_static_frontend_has_no_runtime_api_dependency():
    frontend = ROOT / "web" / "src"
    source = "\n".join(path.read_text(encoding="utf-8") for path in frontend.rglob("*") if path.is_file())
    assert "/v1/" not in source
    assert "fetch(" not in source
    assert "readFileSync" in (frontend / "lib" / "data.ts").read_text(encoding="utf-8")
    assert 'Path("static")' in (ROOT / "build_site.py").read_text(encoding="utf-8")
