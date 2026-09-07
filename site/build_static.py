from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_env import load_local_env
from rating.ledger.schema import load_race_ledger
from server.deps import load_pinned_run, open_registry_readonly
from server.opaque_ids import sync_active_opaque_ids


K_ANONYMITY_MIN = 10
DEFAULT_OUTPUT_ROOT = Path("web/public/static")
DEFAULT_OPAQUE_ID_DB = Path("out/private/opaque_ids.sqlite")
DEFAULT_PUBLIC_FIGURES = Path("data/public_figures.csv")
DEFAULT_LEDGER = Path("out/ledger")


def _public_athlete_ids(path: Path, salt: str) -> list[str]:
    if not salt:
        raise ValueError("[error] 공개 선수 opaque ID 발급에는 SPLITS_ANON_SALT가 필요합니다.")
    if not path.is_file():
        raise FileNotFoundError(f"[error] 공개 선수 명단이 없습니다: {path}")
    athlete_ids: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("상태", "").strip() != "active":
                continue
            id_no = row.get("idNo", "").strip()
            if not id_no:
                raise ValueError("[error] 공개 선수 명단에 idNo가 비어 있습니다.")
            athlete_ids.append(hashlib.sha256(f"{id_no}{salt}".encode("utf-8")).hexdigest()[:12])
    if not athlete_ids:
        raise ValueError("[error] 공개 선수 명단에 active 선수가 없습니다.")
    return sorted(set(athlete_ids))


def build_static_artifacts(
    *,
    registry_root: Path,
    opaque_id_db: Path,
    public_figures: Path,
    ledger: Path,
    output_root: Path,
    salt: str,
) -> None:
    public_athlete_ids = _public_athlete_ids(public_figures, salt)
    opaque_by_athlete = sync_active_opaque_ids(opaque_id_db, public_athlete_ids)
    run = load_pinned_run(registry_root)
    filtered, smoothed = _load_snapshots(registry_root, run.run_id)
    ledger_frame = load_race_ledger(ledger)

    temporary_root = output_root.with_name(f".{output_root.name}.tmp")
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    temporary_root.mkdir(parents=True)
    _write_cohorts(temporary_root / "cohort", filtered, ledger_frame)
    _write_public_trajectories(temporary_root / "athlete", smoothed, opaque_by_athlete, run.run_id)
    if output_root.exists():
        shutil.rmtree(output_root)
    temporary_root.replace(output_root)


def _load_snapshots(registry_root: Path, run_id: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    with open_registry_readonly(registry_root) as connection:
        filtered_rows = connection.execute(
            """
            SELECT athlete_id, valid_date, mu, sigma, n_games
            FROM rating_snapshot WHERE run_id = ? ORDER BY valid_date, athlete_id
            """,
            (run_id,),
        ).fetchall()
        smoothed_rows = connection.execute(
            """
            SELECT athlete_id, valid_date, mu, sigma, n_games
            FROM rating_smoothed_snapshot WHERE run_id = ? ORDER BY valid_date, athlete_id
            """,
            (run_id,),
        ).fetchall()
    schema = {
        "athlete_id": pl.Utf8,
        "valid_date": pl.Utf8,
        "mu": pl.Float64,
        "sigma": pl.Float64,
        "n_games": pl.Int64,
    }

    def _frame(rows: list[Any]) -> pl.DataFrame:
        return pl.DataFrame([dict(row) for row in rows], schema=schema, strict=False).with_columns(
            pl.col("valid_date").str.to_date(strict=True)
        )

    return (
        _frame(filtered_rows),
        _frame(smoothed_rows),
    )


def _write_cohorts(output_root: Path, snapshots: pl.DataFrame, ledger: pl.DataFrame) -> None:
    profile = (
        ledger.select(["athlete_id", "season_year", "gender", "grade_text"])
        .with_columns(
            [
                pl.col("athlete_id").cast(pl.Utf8).str.strip_chars(),
                pl.col("season_year").cast(pl.Int64),
                pl.col("gender").cast(pl.Utf8).str.strip_chars().str.slice(0, 1).alias("sex"),
                pl.col("grade_text").cast(pl.Utf8).str.strip_chars().alias("grade"),
            ]
        )
        .filter((pl.col("athlete_id") != "") & (pl.col("sex") != "") & (pl.col("grade") != ""))
        .group_by(["athlete_id", "season_year"])
        .agg(
            [
                pl.col("sex").mode().first().alias("sex"),
                pl.col("grade").mode().first().alias("grade"),
            ]
        )
    )
    latest = (
        snapshots.with_columns(pl.col("valid_date").dt.year().alias("season_year"))
        .sort(["athlete_id", "season_year", "valid_date"])
        .group_by(["athlete_id", "season_year"])
        .last()
        .join(profile, on=["athlete_id", "season_year"], how="inner")
    )
    for row in latest.group_by(["sex", "grade", "season_year"]).agg(
        [
            pl.len().alias("sample_size"),
            pl.col("mu").quantile(0.10).alias("mu_p10"),
            pl.col("mu").quantile(0.50).alias("mu_p50"),
            pl.col("mu").quantile(0.90).alias("mu_p90"),
        ]
    ).sort(["sex", "grade", "season_year"]).to_dicts():
        if int(row["sample_size"]) < K_ANONYMITY_MIN:
            continue
        path = output_root / str(row["sex"]) / str(row["grade"]) / f"{int(row['season_year'])}.json"
        _write_json(
            path,
            {
                "sample_size": int(row["sample_size"]),
                "mu_p10": round(float(row["mu_p10"]), 4),
                "mu_p50": round(float(row["mu_p50"]), 4),
                "mu_p90": round(float(row["mu_p90"]), 4),
            },
        )


def _write_public_trajectories(
    output_root: Path,
    snapshots: pl.DataFrame,
    opaque_by_athlete: dict[str, str],
    run_id: str,
) -> None:
    for athlete_id, opaque_id in sorted(opaque_by_athlete.items(), key=lambda item: item[1]):
        rows = snapshots.filter(pl.col("athlete_id") == athlete_id).sort("valid_date").to_dicts()
        _write_json(
            output_root / f"{opaque_id}.json",
            {
                "provenance": {"run_id": run_id, "mode": "smoothed"},
                "points": [
                    {
                        "as_of": _date_text(row["valid_date"]),
                        "mu": round(float(row["mu"]), 4),
                        "sigma": round(float(row["sigma"]), 4),
                        "n_games": int(row["n_games"]),
                    }
                    for row in rows
                ],
            },
        )


def _date_text(value: Any) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="정적 코호트·공개 선수 레이팅 산출물을 생성합니다.")
    parser.add_argument("--registry-root", default="out/rating_runs")
    parser.add_argument("--opaque-id-db", default=str(DEFAULT_OPAQUE_ID_DB))
    parser.add_argument("--public-figures", default=str(DEFAULT_PUBLIC_FIGURES))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_ROOT))
    return parser


def main() -> None:
    load_local_env()
    args = build_parser().parse_args()
    build_static_artifacts(
        registry_root=Path(args.registry_root).expanduser(),
        opaque_id_db=Path(args.opaque_id_db).expanduser(),
        public_figures=Path(args.public_figures).expanduser(),
        ledger=Path(args.ledger).expanduser(),
        output_root=Path(args.out).expanduser(),
        salt=os.environ.get("SPLITS_ANON_SALT", "").strip(),
    )
    print(f"[ok] static artifacts={Path(args.out).expanduser()}")


if __name__ == "__main__":
    main()
