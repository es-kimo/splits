from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping

import polars as pl

from .snapshot import canonical_json, run_id as content_run_id

RunStatus = Literal["running", "complete", "failed"]
DEFAULT_REGISTRY_ROOT = Path("out/rating_runs")

_SNAPSHOT_SCHEMA = {
    "athlete_id": pl.Utf8,
    "valid_date": pl.Date,
    "mu": pl.Float64,
    "sigma": pl.Float64,
    "n_games": pl.Int64,
}

_SMOOTHED_SNAPSHOT_SCHEMA = {
    "athlete_id": pl.Utf8,
    "valid_date": pl.Date,
    "mu": pl.Float64,
    "sigma": pl.Float64,
    "n_games": pl.Int64,
}


class RegistryError(ValueError):
    """A rating execution cannot safely be registered or consumed."""


@dataclass(frozen=True)
class RatingRun:
    run_id: str
    algo_version: str
    params_json: str
    calibrator_json: str
    input_snapshot_id: str
    created_at: str
    status: RunStatus
    metrics_json: str | None
    git_sha: str


@dataclass(frozen=True)
class RegisteredSnapshots:
    run_id: str
    snapshots: pl.DataFrame


def require_single_run(*values: RegisteredSnapshots) -> str:
    run_ids = {value.run_id for value in values}
    if len(run_ids) != 1:
        raise RegistryError("[error] 서로 다른 실행의 레이팅은 한 계산에 함께 사용할 수 없습니다.")
    return next(iter(run_ids))


class RatingRegistry:
    def __init__(self, root: Path = DEFAULT_REGISTRY_ROOT) -> None:
        self.root = root.expanduser()
        self.runs_root = self.root / "runs"
        self.database_path = self.root / "registry.sqlite"

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rating_run (
                    run_id TEXT PRIMARY KEY,
                    algo_version TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    input_snapshot_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('running', 'complete', 'failed')),
                    metrics_json TEXT,
                    git_sha TEXT NOT NULL,
                    calibrator_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rating_snapshot (
                    run_id TEXT NOT NULL REFERENCES rating_run(run_id),
                    athlete_id TEXT NOT NULL,
                    valid_date TEXT NOT NULL,
                    mu REAL NOT NULL,
                    sigma REAL NOT NULL,
                    n_games INTEGER NOT NULL,
                    PRIMARY KEY (run_id, athlete_id, valid_date)
                );
                CREATE INDEX IF NOT EXISTS rating_snapshot_run_date
                    ON rating_snapshot(run_id, valid_date);
                CREATE TABLE IF NOT EXISTS rating_smoothed_snapshot (
                    run_id TEXT NOT NULL REFERENCES rating_run(run_id),
                    athlete_id TEXT NOT NULL,
                    valid_date TEXT NOT NULL,
                    mu REAL NOT NULL,
                    sigma REAL NOT NULL,
                    n_games INTEGER NOT NULL,
                    PRIMARY KEY (run_id, athlete_id, valid_date)
                );
                CREATE INDEX IF NOT EXISTS rating_smoothed_snapshot_run_date
                    ON rating_smoothed_snapshot(run_id, valid_date);
                """
            )

    def run_directory(self, run_id: str) -> Path:
        _validate_run_id(run_id)
        return self.runs_root / run_id

    def get_run(self, run_id: str, *, include_incomplete: bool = False) -> RatingRun | None:
        self.initialize()
        query = "SELECT * FROM rating_run WHERE run_id = ?"
        if not include_incomplete:
            query += " AND status = 'complete'"
        with self._connect() as connection:
            row = connection.execute(query, (run_id,)).fetchone()
        return _run_from_row(row) if row is not None else None

    def find_reusable(
        self,
        *,
        algo_version: str,
        engine_params: Mapping[str, object],
        input_snapshot_id: str,
    ) -> RatingRun | None:
        """Return the sole completed run for an otherwise identical engine execution."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM rating_run
                WHERE algo_version = ? AND params_json = ? AND input_snapshot_id = ? AND status = 'complete'
                ORDER BY created_at DESC, run_id DESC
                """,
                (algo_version, canonical_json(dict(engine_params)), input_snapshot_id),
            ).fetchall()
        if len(rows) == 1:
            return _run_from_row(rows[0])
        return None

    def begin(
        self,
        *,
        run_id: str,
        algo_version: str,
        engine_params: Mapping[str, object],
        calibrator_spec: Mapping[str, object],
        input_snapshot_id: str,
        git_sha: str | None = None,
    ) -> RatingRun:
        self.initialize()
        _validate_run_id(run_id)
        params_json = canonical_json(dict(engine_params))
        calibrator_json = canonical_json(dict(calibrator_spec))
        expected_run_id = content_run_id(
            algo_version=algo_version,
            engine_params=engine_params,
            calibrator_spec=calibrator_spec,
            input_id=input_snapshot_id,
        )
        if run_id != expected_run_id:
            raise RegistryError("[error] run_id가 실행 정의의 콘텐츠 주소와 일치하지 않습니다.")
        with self._connect() as connection:
            existing = connection.execute("SELECT * FROM rating_run WHERE run_id = ?", (run_id,)).fetchone()
            if existing is not None:
                run = _run_from_row(existing)
                expected = (algo_version, params_json, calibrator_json, input_snapshot_id)
                observed = (run.algo_version, run.params_json, run.calibrator_json, run.input_snapshot_id)
                if observed != expected:
                    raise RegistryError("[error] 같은 run_id에 서로 다른 실행 정의를 등록할 수 없습니다.")
                if run.status == "failed":
                    connection.execute(
                        "UPDATE rating_run SET status = 'running', metrics_json = NULL WHERE run_id = ?",
                        (run_id,),
                    )
                    run = RatingRun(
                        run_id=run.run_id,
                        algo_version=run.algo_version,
                        params_json=run.params_json,
                        calibrator_json=run.calibrator_json,
                        input_snapshot_id=run.input_snapshot_id,
                        created_at=run.created_at,
                        status="running",
                        metrics_json=None,
                        git_sha=run.git_sha,
                    )
                return run
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            connection.execute(
                """
                INSERT INTO rating_run (
                    run_id, algo_version, params_json, input_snapshot_id, created_at,
                    status, metrics_json, git_sha, calibrator_json
                ) VALUES (?, ?, ?, ?, ?, 'running', NULL, ?, ?)
                """,
                (run_id, algo_version, params_json, input_snapshot_id, created_at, git_sha or _git_sha(), calibrator_json),
            )
        self.run_directory(run_id).mkdir(parents=True, exist_ok=True)
        run = self.get_run(run_id, include_incomplete=True)
        if run is None:
            raise RegistryError("[error] 등록한 실행을 다시 읽을 수 없습니다.")
        return run

    def complete(
        self,
        run_id: str,
        snapshots: pl.DataFrame,
        *,
        smoothed_snapshots: pl.DataFrame | None = None,
        metrics: Mapping[str, object] | None = None,
    ) -> RatingRun:
        self.initialize()
        prepared = _prepare_snapshots(snapshots)
        prepared_smoothed = (
            _prepare_smoothed_snapshots(smoothed_snapshots) if smoothed_snapshots is not None else None
        )
        with self._connect() as connection:
            run = self._require_running(connection, run_id)
            connection.execute("DELETE FROM rating_snapshot WHERE run_id = ?", (run_id,))
            connection.executemany(
                """
                INSERT INTO rating_snapshot (run_id, athlete_id, valid_date, mu, sigma, n_games)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        row["athlete_id"],
                        row["valid_date"].isoformat(),
                        row["mu"],
                        row["sigma"],
                        row["n_games"],
                    )
                    for row in prepared.to_dicts()
                ],
            )
            if prepared_smoothed is not None:
                connection.execute("DELETE FROM rating_smoothed_snapshot WHERE run_id = ?", (run_id,))
                connection.executemany(
                    """
                    INSERT INTO rating_smoothed_snapshot (run_id, athlete_id, valid_date, mu, sigma, n_games)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            row["athlete_id"],
                            row["valid_date"].isoformat(),
                            row["mu"],
                            row["sigma"],
                            row["n_games"],
                        )
                        for row in prepared_smoothed.to_dicts()
                    ],
                )
            connection.execute(
                "UPDATE rating_run SET status = 'complete', metrics_json = ? WHERE run_id = ?",
                (canonical_json(dict(metrics or {})), run_id),
            )
        self.publish(run_id)
        completed = self.get_run(run_id)
        if completed is None:
            raise RegistryError("[error] 완료한 실행을 다시 읽을 수 없습니다.")
        return completed

    def fail(self, run_id: str, error: Exception | str) -> RatingRun:
        self.initialize()
        with self._connect() as connection:
            self._require_running(connection, run_id)
            metrics = canonical_json({"error": str(error)})
            connection.execute(
                "UPDATE rating_run SET status = 'failed', metrics_json = ? WHERE run_id = ?",
                (metrics, run_id),
            )
        failed = self.get_run(run_id, include_incomplete=True)
        if failed is None:
            raise RegistryError("[error] 실패한 실행을 다시 읽을 수 없습니다.")
        return failed

    def publish(self, run_id: str) -> None:
        if self.get_run(run_id) is None:
            raise RegistryError("[error] 완료되지 않은 실행은 current로 공개할 수 없습니다.")
        self.runs_root.mkdir(parents=True, exist_ok=True)
        target = self.runs_root / "current"
        temporary = self.runs_root / f".current-{os.getpid()}-{run_id}.tmp"
        temporary.write_text(f"{run_id}\n", encoding="ascii")
        os.replace(temporary, target)

    def current_run_id(self) -> str:
        pointer = self.runs_root / "current"
        try:
            run_id = pointer.read_text(encoding="ascii").strip()
        except OSError as error:
            raise RegistryError("[error] 공개된 레이팅 실행이 없습니다.") from error
        _validate_run_id(run_id)
        if self.get_run(run_id) is None:
            raise RegistryError("[error] current가 완료되지 않았거나 없는 실행을 가리킵니다.")
        return run_id

    def load_snapshots(self, run_id: str | None = None) -> RegisteredSnapshots:
        selected = run_id or self.current_run_id()
        if self.get_run(selected) is None:
            raise RegistryError("[error] 완료된 레이팅 실행만 조회할 수 있습니다.")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT athlete_id, valid_date, mu, sigma, n_games
                FROM rating_snapshot WHERE run_id = ?
                ORDER BY valid_date, athlete_id
                """,
                (selected,),
            ).fetchall()
        records = [dict(row) for row in rows]
        frame = (
            pl.DataFrame(records)
            if records
            else pl.DataFrame(
                schema={
                    "athlete_id": pl.Utf8,
                    "valid_date": pl.Utf8,
                    "mu": pl.Float64,
                    "sigma": pl.Float64,
                    "n_games": pl.Int64,
                }
            )
        )
        return RegisteredSnapshots(
            run_id=selected,
            snapshots=frame.select(list(_SNAPSHOT_SCHEMA)).with_columns(
                [
                    pl.col("athlete_id").cast(pl.Utf8, strict=True),
                    pl.col("valid_date").cast(pl.Utf8, strict=True).str.to_date(strict=True),
                    pl.col("mu").cast(pl.Float64, strict=True),
                    pl.col("sigma").cast(pl.Float64, strict=True),
                    pl.col("n_games").cast(pl.Int64, strict=True),
                ]
            ),
        )

    def load_smoothed_snapshots(self, run_id: str | None = None) -> RegisteredSnapshots:
        selected = run_id or self.current_run_id()
        if self.get_run(selected) is None:
            raise RegistryError("[error] 완료된 레이팅 실행만 조회할 수 있습니다.")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT athlete_id, valid_date, mu, sigma, n_games
                FROM rating_smoothed_snapshot WHERE run_id = ?
                ORDER BY valid_date, athlete_id
                """,
                (selected,),
            ).fetchall()
        records = [dict(row) for row in rows]
        frame = (
            pl.DataFrame(records)
            if records
            else pl.DataFrame(
                schema={
                    "athlete_id": pl.Utf8,
                    "valid_date": pl.Utf8,
                    "mu": pl.Float64,
                    "sigma": pl.Float64,
                    "n_games": pl.Int64,
                }
            )
        )
        return RegisteredSnapshots(
            run_id=selected,
            snapshots=frame.select(list(_SMOOTHED_SNAPSHOT_SCHEMA)).with_columns(
                [
                    pl.col("athlete_id").cast(pl.Utf8, strict=True),
                    pl.col("valid_date").cast(pl.Utf8, strict=True).str.to_date(strict=True),
                    pl.col("mu").cast(pl.Float64, strict=True),
                    pl.col("sigma").cast(pl.Float64, strict=True),
                    pl.col("n_games").cast(pl.Int64, strict=True),
                ]
            ),
        )

    def filtered_snapshot_as_of(
        self,
        athlete_id: str,
        as_of: date,
        run_id: str | None = None,
    ) -> dict[str, object] | None:
        return self._snapshot_as_of("rating_snapshot", athlete_id, as_of, run_id)

    def smoothed_snapshot_as_of(
        self,
        athlete_id: str,
        valid_date: date,
        run_id: str | None = None,
    ) -> dict[str, object] | None:
        return self._snapshot_as_of("rating_smoothed_snapshot", athlete_id, valid_date, run_id)

    def _snapshot_as_of(
        self,
        table: Literal["rating_snapshot", "rating_smoothed_snapshot"],
        athlete_id: str,
        valid_date: date,
        run_id: str | None,
    ) -> dict[str, object] | None:
        selected = run_id or self.current_run_id()
        if self.get_run(selected) is None:
            raise RegistryError("[error] 완료된 레이팅 실행만 조회할 수 있습니다.")
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT athlete_id, valid_date, mu, sigma, n_games
                FROM {table}
                WHERE run_id = ? AND athlete_id = ? AND valid_date <= ?
                ORDER BY valid_date DESC
                LIMIT 1
                """,
                (selected, athlete_id, valid_date.isoformat()),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_runs(self, *, include_incomplete: bool = False) -> list[RatingRun]:
        self.initialize()
        query = "SELECT * FROM rating_run"
        if not include_incomplete:
            query += " WHERE status = 'complete'"
        query += " ORDER BY created_at DESC, run_id DESC"
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [_run_from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _require_running(connection: sqlite3.Connection, run_id: str) -> RatingRun:
        row = connection.execute("SELECT * FROM rating_run WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise RegistryError("[error] 등록되지 않은 실행입니다.")
        run = _run_from_row(row)
        if run.status != "running":
            raise RegistryError(f"[error] 실행 상태 전환이 허용되지 않습니다: {run.status}")
        return run


def _prepare_snapshots(snapshots: pl.DataFrame) -> pl.DataFrame:
    required = set(_SNAPSHOT_SCHEMA)
    missing = sorted(required.difference(snapshots.columns))
    if missing:
        raise RegistryError(f"[error] 레이팅 스냅샷 컬럼이 없습니다: {', '.join(missing)}")
    selected = snapshots.select(list(_SNAPSHOT_SCHEMA)).with_columns(
        [
            pl.col("athlete_id").cast(pl.Utf8, strict=True),
            pl.col("valid_date").cast(pl.Date, strict=True),
            pl.col("mu").cast(pl.Float64, strict=True),
            pl.col("sigma").cast(pl.Float64, strict=True),
            pl.col("n_games").cast(pl.Int64, strict=True),
        ]
    )
    if selected.null_count().sum_horizontal().item() != 0:
        raise RegistryError("[error] 레이팅 스냅샷에는 NULL 값이 있을 수 없습니다.")
    if selected.unique(subset=["athlete_id", "valid_date"]).height != selected.height:
        raise RegistryError("[error] 실행 안에서 선수와 기준일 조합이 중복됩니다.")
    return selected.sort(["valid_date", "athlete_id"])


def _prepare_smoothed_snapshots(snapshots: pl.DataFrame) -> pl.DataFrame:
    required = set(_SMOOTHED_SNAPSHOT_SCHEMA)
    missing = sorted(required.difference(snapshots.columns))
    if missing:
        raise RegistryError(f"[error] 스무딩 레이팅 스냅샷 컬럼이 없습니다: {', '.join(missing)}")
    selected = snapshots.select(list(_SMOOTHED_SNAPSHOT_SCHEMA)).with_columns(
        [
            pl.col("athlete_id").cast(pl.Utf8, strict=True),
            pl.col("valid_date").cast(pl.Date, strict=True),
            pl.col("mu").cast(pl.Float64, strict=True),
            pl.col("sigma").cast(pl.Float64, strict=True),
            pl.col("n_games").cast(pl.Int64, strict=True),
        ]
    )
    if selected.null_count().sum_horizontal().item() != 0:
        raise RegistryError("[error] 스무딩 레이팅 스냅샷에는 NULL 값이 있을 수 없습니다.")
    if selected.unique(subset=["athlete_id", "valid_date"]).height != selected.height:
        raise RegistryError("[error] 실행 안에서 선수와 기준일 조합이 중복됩니다.")
    return selected.sort(["valid_date", "athlete_id"])


def _validate_run_id(run_id: str) -> None:
    if len(run_id) != 16 or any(char not in "0123456789abcdef" for char in run_id):
        raise RegistryError("[error] run_id는 16자리 소문자 SHA-256 접두어여야 합니다.")


def _run_from_row(row: sqlite3.Row) -> RatingRun:
    return RatingRun(
        run_id=str(row["run_id"]),
        algo_version=str(row["algo_version"]),
        params_json=str(row["params_json"]),
        calibrator_json=str(row["calibrator_json"]),
        input_snapshot_id=str(row["input_snapshot_id"]),
        created_at=str(row["created_at"]),
        status=str(row["status"]),
        metrics_json=str(row["metrics_json"]) if row["metrics_json"] is not None else None,
        git_sha=str(row["git_sha"]),
    )


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="레이팅 실행 레지스트리")
    parser.add_argument("--root", default=str(DEFAULT_REGISTRY_ROOT), help="레지스트리 루트 디렉터리")
    parser.add_argument("--list", action="store_true", help="완료된 실행 목록을 표시합니다")
    parser.add_argument("--include-incomplete", action="store_true", help="running/failed 실행도 표시합니다")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    registry = RatingRegistry(Path(args.root))
    registry.initialize()
    if not args.list:
        return
    for run in registry.list_runs(include_incomplete=bool(args.include_incomplete)):
        print(f"{run.run_id}\t{run.status}\t{run.algo_version}\t{run.input_snapshot_id}\t{run.created_at}")


if __name__ == "__main__":
    main()
