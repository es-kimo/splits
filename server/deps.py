from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any, cast

import polars as pl

from rating.ledger.extract import estimate_penalty_rate
from rating.ledger.schema import load_race_ledger

from .opaque_ids import load_active_opaque_ids, open_readonly_connection


RUN_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class ApiDataError(ValueError):
    """The published run cannot be safely served."""


@dataclass(frozen=True)
class ApiConfig:
    registry_root: Path
    opaque_id_db: Path
    age_adjusted_path: Path | None = None
    penalty_ledger_path: Path | None = None
    penalty_results_path: Path | None = None

    @classmethod
    def from_env(cls) -> "ApiConfig":
        age_adjusted = os.environ.get("SPLITS_AGE_ADJUSTED_PATH", "").strip()
        penalty_ledger = os.environ.get("SPLITS_SIM_PENALTY_LEDGER", "out/ledger").strip()
        penalty_results = os.environ.get("SPLITS_SIM_PENALTY_RESULTS", "data/records_full.csv").strip()
        return cls(
            registry_root=Path(os.environ.get("SPLITS_RATING_REGISTRY_ROOT", "out/rating_runs")).expanduser(),
            opaque_id_db=Path(os.environ.get("SPLITS_OPAQUE_ID_DB", "out/private/opaque_ids.sqlite")).expanduser(),
            age_adjusted_path=Path(age_adjusted).expanduser() if age_adjusted else None,
            penalty_ledger_path=Path(penalty_ledger).expanduser() if penalty_ledger else None,
            penalty_results_path=Path(penalty_results).expanduser() if penalty_results else None,
        )


@dataclass(frozen=True)
class PinnedRun:
    run_id: str
    algo_version: str
    created_at: str
    calibrator: str
    data_as_of: date
    engine_params: dict[str, Any]
    calibrator_spec: dict[str, Any]


@dataclass(frozen=True)
class RatingSnapshot:
    valid_date: date
    mu: float
    sigma: float
    n_games: int
    z_vs_age: float | None


class ReadOnlyRatingRepository:
    """Serves one completed run pinned for the lifetime of this process."""

    def __init__(self, config: ApiConfig, *, today: date | None = None) -> None:
        self.config = config
        self.pinned_run = load_pinned_run(config.registry_root)
        self._opaque_to_athlete = load_active_opaque_ids(config.opaque_id_db)
        self._z_by_snapshot = load_age_adjusted_z(config.age_adjusted_path, self.pinned_run.run_id)
        self._today = today or date.today()
        self._default_penalty_rate: float | None = None
        self._penalty_lock = Lock()

    def athlete_id_for(self, opaque_id: str) -> str | None:
        return self._opaque_to_athlete.get(opaque_id)

    def rating_as_of(self, athlete_id: str, as_of: date) -> RatingSnapshot | None:
        if as_of > self.pinned_run.data_as_of:
            as_of = self.pinned_run.data_as_of
        row = self._snapshot_row("rating_snapshot", athlete_id, as_of)
        return self._rating_from_row(row) if row is not None else None

    def filtered_trajectory(self, athlete_id: str) -> list[RatingSnapshot]:
        with open_registry_readonly(self.config.registry_root) as connection:
            rows = connection.execute(
                """
                SELECT athlete_id, valid_date, mu, sigma, n_games
                FROM rating_snapshot
                WHERE run_id = ? AND athlete_id = ?
                ORDER BY valid_date
                """,
                (self.pinned_run.run_id, athlete_id),
            ).fetchall()
        return [self._rating_from_row(row) for row in rows]

    def stale_days(self) -> int:
        return max(0, (self._today - self.pinned_run.data_as_of).days)

    def simulation_beta(self) -> float:
        raw_beta: object = self.pinned_run.engine_params.get("beta")
        if isinstance(raw_beta, bool) or not isinstance(raw_beta, (int, float)):
            raise ApiDataError("[error] 공개된 레이팅 실행에 TrueSkill beta가 없습니다.")
        beta = float(raw_beta)
        if not math.isfinite(beta) or beta <= 0.0:
            raise ApiDataError("[error] 공개된 레이팅 실행의 TrueSkill beta가 올바르지 않습니다.")
        return beta

    def default_penalty_rate(self) -> float:
        with self._penalty_lock:
            if self._default_penalty_rate is not None:
                return self._default_penalty_rate
            results_path = self.config.penalty_results_path
            if results_path is not None and results_path.is_file():
                try:
                    self._default_penalty_rate = estimate_penalty_rate(results_path)
                except ValueError as error:
                    raise ApiDataError(str(error)) from error
                return self._default_penalty_rate
            path = self.config.penalty_ledger_path
            if path is None or not path.exists():
                raise ApiDataError("[error] 시뮬레이션 기본 실격률 레저가 없습니다.")
            ledger = load_race_ledger(path)
            if ledger.is_empty() or "status" not in ledger.columns:
                raise ApiDataError("[error] 시뮬레이션 기본 실격률을 계산할 상태 데이터가 없습니다.")
            total = ledger.height
            penalty_count = ledger.filter(pl.col("status") == "PEN").height
            self._default_penalty_rate = penalty_count / total
            return self._default_penalty_rate

    def _snapshot_row(self, table: str, athlete_id: str, as_of: date) -> sqlite3.Row | None:
        with open_registry_readonly(self.config.registry_root) as connection:
            return cast(
                sqlite3.Row | None,
                connection.execute(
                    f"""
                    SELECT athlete_id, valid_date, mu, sigma, n_games
                    FROM {table}
                    WHERE run_id = ? AND athlete_id = ? AND valid_date <= ?
                    ORDER BY valid_date DESC
                    LIMIT 1
                    """,
                    (self.pinned_run.run_id, athlete_id, as_of.isoformat()),
                ).fetchone(),
            )

    def _rating_from_row(self, row: sqlite3.Row) -> RatingSnapshot:
        valid_date = date.fromisoformat(str(row["valid_date"]))
        return RatingSnapshot(
            valid_date=valid_date,
            mu=float(row["mu"]),
            sigma=float(row["sigma"]),
            n_games=int(row["n_games"]),
            z_vs_age=self._z_by_snapshot.get((str(row["athlete_id"]) if "athlete_id" in row.keys() else "", valid_date)),
        )


def load_pinned_run(registry_root: Path) -> PinnedRun:
    pointer = registry_root / "runs" / "current"
    try:
        run_id = pointer.read_text(encoding="ascii").strip()
    except OSError as error:
        raise ApiDataError("[error] 공개된 레이팅 실행이 없습니다.") from error
    if not RUN_ID_RE.fullmatch(run_id):
        raise ApiDataError("[error] current run ID 형식이 올바르지 않습니다.")

    with open_registry_readonly(registry_root) as connection:
        row = connection.execute(
            """
            SELECT run_id, algo_version, created_at, calibrator_json, params_json
            FROM rating_run
            WHERE run_id = ? AND status = 'complete'
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise ApiDataError("[error] current가 완료된 실행을 가리키지 않습니다.")
        data_row = connection.execute(
            "SELECT MAX(valid_date) AS data_as_of FROM rating_snapshot WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if data_row is None or data_row["data_as_of"] is None:
        raise ApiDataError("[error] 공개된 레이팅 실행에 필터 스냅샷이 없습니다.")
    return PinnedRun(
        run_id=str(row["run_id"]),
        algo_version=str(row["algo_version"]),
        created_at=str(row["created_at"]),
        calibrator=_calibrator_name(str(row["calibrator_json"])),
        data_as_of=date.fromisoformat(str(data_row["data_as_of"])),
        engine_params=_engine_params(str(row["params_json"])),
        calibrator_spec=_calibrator_spec(str(row["calibrator_json"])),
    )


def open_registry_readonly(registry_root: Path) -> sqlite3.Connection:
    path = (registry_root / "registry.sqlite").expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"[error] 레이팅 레지스트리 파일이 없습니다: {path}")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_age_adjusted_z(path: Path | None, run_id: str) -> dict[tuple[str, date], float | None]:
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"[error] 연령 보정 레이팅 파일이 없습니다: {path}")
    frame = pl.read_parquet(path)
    required = {"run_id", "athlete_id", "valid_date", "z"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ApiDataError(f"[error] 연령 보정 레이팅 컬럼이 없습니다: {', '.join(missing)}")
    selected = frame.filter(pl.col("run_id") == run_id)
    if selected.height != frame.height:
        raise ApiDataError("[error] 연령 보정 레이팅이 현재 공개 run과 일치하지 않습니다.")
    return {
        (str(row["athlete_id"]), date.fromisoformat(str(row["valid_date"]))): (
            float(row["z"]) if row["z"] is not None else None
        )
        for row in selected.select(["athlete_id", "valid_date", "z"]).to_dicts()
    }


def _calibrator_name(raw: str) -> str:
    payload = _calibrator_spec(raw)
    return f"{payload['method'].strip()}-v1"


def _calibrator_spec(raw: str) -> dict[str, Any]:
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ApiDataError("[error] 레이팅 실행의 보정기 메타데이터가 올바른 JSON이 아닙니다.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("method"), str) or not payload["method"].strip():
        raise ApiDataError("[error] 레이팅 실행의 보정기 메타데이터에 method가 없습니다.")
    return payload


def _engine_params(raw: str) -> dict[str, Any]:
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ApiDataError("[error] 레이팅 실행의 엔진 파라미터가 올바른 JSON이 아닙니다.") from error
    if not isinstance(payload, dict):
        raise ApiDataError("[error] 레이팅 실행의 엔진 파라미터는 객체여야 합니다.")
    return payload
