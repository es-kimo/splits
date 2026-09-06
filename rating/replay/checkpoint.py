from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

import polars as pl

from rating.engine.glicko2 import Rating

DEFAULT_CHECKPOINT_ROOT = Path("out/replay_checkpoints")

_STATE_SCHEMA = {
    "athlete_id": pl.Utf8,
    "mu": pl.Float64,
    "phi": pl.Float64,
    "sigma": pl.Float64,
    "last_active": pl.Date,
    "n_games": pl.Int64,
}


class CheckpointError(ValueError):
    """A checkpoint cannot safely be used for the requested replay."""


@dataclass(frozen=True)
class Checkpoint:
    cid: str
    cutoff_date: date
    algorithm_version: str
    params_hash: str
    input_hash: str
    state_path: Path
    metadata_path: Path


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _as_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise CheckpointError(f"[error] checkpoint cutoff_date 형식이 올바르지 않습니다: {value}") from error


def params_digest(params: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(dict(params)).encode("utf-8")).hexdigest()


def checkpoint_id(algo_version: str, params_hash: str, input_hash: str, cutoff_date: date | str) -> str:
    payload = {
        "algorithm_version": str(algo_version),
        "cutoff_date": _as_date(cutoff_date).isoformat(),
        "input_hash": str(input_hash),
        "params_hash": str(params_hash),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _paths(root: Path, cid: str) -> tuple[Path, Path]:
    if not cid or any(char not in "0123456789abcdef" for char in cid):
        raise CheckpointError("[error] checkpoint ID는 소문자 SHA-256 16진수여야 합니다.")
    return root / f"{cid}.parquet", root / f"{cid}.json"


def _checkpoint_from_metadata(metadata_path: Path) -> Checkpoint:
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        cid = str(raw["cid"])
        cutoff_date = _as_date(str(raw["cutoff_date"]))
        algorithm_version = str(raw["algorithm_version"])
        params_hash = str(raw["params_hash"])
        input_hash = str(raw["input_hash"])
        state_sha256 = str(raw["state_sha256"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise CheckpointError(f"[error] checkpoint 메타데이터를 읽을 수 없습니다: {metadata_path}") from error
    expected_cid = checkpoint_id(algorithm_version, params_hash, input_hash, cutoff_date)
    if cid != expected_cid:
        raise CheckpointError(f"[error] checkpoint ID가 메타데이터와 일치하지 않습니다: {metadata_path}")
    state_path, _ = _paths(metadata_path.parent, cid)
    if not state_path.exists():
        raise CheckpointError(f"[error] checkpoint 상태 파일이 없습니다: {state_path}")
    if _digest_file(state_path) != state_sha256:
        raise CheckpointError(f"[error] checkpoint 상태 파일 해시가 일치하지 않습니다: {state_path}")
    return Checkpoint(
        cid=cid,
        cutoff_date=cutoff_date,
        algorithm_version=algorithm_version,
        params_hash=params_hash,
        input_hash=input_hash,
        state_path=state_path,
        metadata_path=metadata_path,
    )


def save(
    state: Mapping[str, Rating],
    cid: str,
    *,
    root: Path = DEFAULT_CHECKPOINT_ROOT,
    algorithm_version: str,
    params_hash: str,
    input_hash: str,
    cutoff_date: date,
) -> Path:
    expected_cid = checkpoint_id(algorithm_version, params_hash, input_hash, cutoff_date)
    if cid != expected_cid:
        raise CheckpointError("[error] checkpoint ID가 상태 메타데이터와 일치하지 않습니다.")
    state_path, metadata_path = _paths(root, cid)
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "athlete_id": athlete_id,
            "mu": float(rating.mu),
            "phi": float(rating.phi),
            "sigma": float(rating.sigma),
            "last_active": rating.last_active,
            "n_games": int(rating.n_games),
        }
        for athlete_id, rating in sorted(state.items())
    ]
    frame = pl.DataFrame(rows, schema=_STATE_SCHEMA)
    temp_state = state_path.with_suffix(".parquet.tmp")
    temp_metadata = metadata_path.with_suffix(".json.tmp")
    frame.write_parquet(temp_state)
    metadata = {
        "algorithm_version": algorithm_version,
        "cid": cid,
        "cutoff_date": cutoff_date.isoformat(),
        "input_hash": input_hash,
        "params_hash": params_hash,
        "state_sha256": _digest_file(temp_state),
    }
    temp_metadata.write_text(_canonical_json(metadata) + "\n", encoding="utf-8")
    os.replace(temp_state, state_path)
    os.replace(temp_metadata, metadata_path)
    return state_path


def load(
    cid: str,
    *,
    root: Path = DEFAULT_CHECKPOINT_ROOT,
    expected: Checkpoint | None = None,
) -> dict[str, Rating] | None:
    state_path, metadata_path = _paths(root, cid)
    if not state_path.exists() and not metadata_path.exists():
        return None
    if not state_path.exists() or not metadata_path.exists():
        raise CheckpointError(f"[error] checkpoint 파일 쌍이 완전하지 않습니다: {cid}")
    checkpoint = _checkpoint_from_metadata(metadata_path)
    if checkpoint.cid != cid:
        raise CheckpointError(f"[error] checkpoint ID가 요청과 일치하지 않습니다: {cid}")
    if expected is not None and checkpoint != expected:
        raise CheckpointError(f"[error] 요청한 재생과 호환되지 않는 checkpoint입니다: {cid}")
    frame = pl.read_parquet(state_path)
    if frame.schema != _STATE_SCHEMA:
        raise CheckpointError(f"[error] checkpoint 상태 스키마가 일치하지 않습니다: {state_path}")
    if frame["athlete_id"].n_unique() != frame.height:
        raise CheckpointError(f"[error] checkpoint athlete_id가 중복됩니다: {state_path}")
    result: dict[str, Rating] = {}
    for row in frame.sort("athlete_id").to_dicts():
        result[str(row["athlete_id"])] = Rating(
            mu=float(row["mu"]),
            phi=float(row["phi"]),
            sigma=float(row["sigma"]),
            last_active=row["last_active"],
            n_games=int(row["n_games"]),
        )
    return result


def find_nearest(
    target_date: date,
    algorithm_version: str,
    params_hash: str,
    input_hash: str,
    *,
    root: Path = DEFAULT_CHECKPOINT_ROOT,
) -> Checkpoint | None:
    if not root.exists():
        return None
    matches: list[Checkpoint] = []
    for metadata_path in sorted(root.glob("*.json")):
        checkpoint = _checkpoint_from_metadata(metadata_path)
        if (
            checkpoint.cutoff_date <= target_date
            and checkpoint.algorithm_version == algorithm_version
            and checkpoint.params_hash == params_hash
            and checkpoint.input_hash == input_hash
        ):
            matches.append(checkpoint)
    return max(matches, key=lambda item: item.cutoff_date) if matches else None
