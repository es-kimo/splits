from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from rating.engine.glicko2 import Rating
from rating.engine.runner import ledger_digest, to_race_results
from rating.ledger.ordering import make_ordering_key
from rating.ledger.schema import load_race_ledger, validate_ledger

from .checkpoint import DEFAULT_CHECKPOINT_ROOT, Checkpoint, find_nearest, params_digest
from .orchestrator import ReplayParams, ReplayResult, replay


@dataclass(frozen=True)
class IdentityMerge:
    primary_id: str
    secondary_id: str

    def __post_init__(self) -> None:
        if not self.primary_id or not self.secondary_id or self.primary_id == self.secondary_id:
            raise ValueError("[error] 병합 ID는 서로 다른 비어 있지 않은 값이어야 합니다.")


@dataclass(frozen=True)
class MergeReplayResult:
    merge: IdentityMerge
    merge_at: date
    replay: ReplayResult
    resumed_from: Checkpoint | None


def _first_appearance(race_ledger: pl.DataFrame, athlete_id: str) -> date:
    dates: list[date] = []
    for race in to_race_results(race_ledger):
        if any(entry.athlete_id == athlete_id for entry in race.entries):
            dates.append(race.race_date)
    if not dates:
        raise ValueError(f"[error] 병합 대상 선수를 레저에서 찾을 수 없습니다: {athlete_id}")
    return min(dates)


def _merge_start(race_ledger: pl.DataFrame, merge: IdentityMerge) -> date:
    return min(_first_appearance(race_ledger, merge.primary_id), _first_appearance(race_ledger, merge.secondary_id))


def _affected_race_ids(race_ledger: pl.DataFrame, merge_at: date, primary_id: str) -> tuple[set[str], set[str]]:
    races = [race for race in to_race_results(race_ledger) if race.race_date >= merge_at]
    race_members = {race.race_id: {entry.athlete_id for entry in race.entries} for race in races}
    athlete_races: dict[str, set[str]] = {}
    for race_id, athlete_ids in race_members.items():
        for athlete_id in athlete_ids:
            athlete_races.setdefault(athlete_id, set()).add(race_id)
    affected_ids = {primary_id}
    frontier = {primary_id}
    while frontier:
        connected_races = {race_id for athlete_id in frontier for race_id in athlete_races.get(athlete_id, set())}
        next_frontier = set().union(*(race_members[race_id] for race_id in connected_races)).difference(affected_ids)
        affected_ids.update(next_frontier)
        frontier = next_frontier
    affected_races = {race_id for race_id, athlete_ids in race_members.items() if athlete_ids.intersection(affected_ids)}
    return affected_ids, affected_races


def apply_identity_merge(race_ledger: pl.DataFrame, merge: IdentityMerge) -> pl.DataFrame:
    """Return a new ledger where the secondary identity is mapped to the primary identity."""
    validate_ledger(race_ledger)
    ids = set(race_ledger["athlete_id"].to_list())
    missing = sorted({merge.primary_id, merge.secondary_id}.difference(ids))
    if missing:
        raise ValueError(f"[error] 병합 대상 선수를 레저에서 찾을 수 없습니다: {', '.join(missing)}")

    merged = race_ledger.with_columns(
        pl.when(pl.col("athlete_id") == merge.secondary_id)
        .then(pl.lit(merge.primary_id))
        .otherwise(pl.col("athlete_id"))
        .alias("athlete_id")
    ).with_columns(
        pl.struct(["race_date", "meet_id", "race_seq", "race_id", "rank", "athlete_id"])
        .map_elements(make_ordering_key, return_dtype=pl.Utf8)
        .alias("ordering_key")
    )
    duplicate = merged.group_by(["race_id", "athlete_id"]).len().filter(pl.col("len") > 1)
    if not duplicate.is_empty():
        row = duplicate.sort(["race_id", "athlete_id"]).row(0, named=True)
        raise ValueError(
            "[error] 병합 뒤 같은 race에 같은 선수가 중복됩니다: "
            f"race_id={row['race_id']}, athlete_id={row['athlete_id']}"
        )
    merged = merged.sort(["ordering_key", "athlete_id"], nulls_last=True)
    validate_ledger(merged)
    return merged


def _write_ledger(race_ledger: pl.DataFrame, root: Path) -> None:
    race_root = root / "race_ledger"
    race_root.mkdir(parents=True, exist_ok=True)
    race_ledger.write_parquet(race_root / "part.parquet")


def replay_after_identity_merge(
    ledger_path: Path,
    merge: IdentityMerge,
    params: ReplayParams,
    *,
    checkpoint_root: Path = DEFAULT_CHECKPOINT_ROOT,
    baseline_final_state: dict[str, Rating] | None = None,
) -> MergeReplayResult:
    """Replay a merged ledger from a checkpoint strictly before the secondary ID first appears."""
    original = load_race_ledger(ledger_path)
    validate_ledger(original)
    merge_at = _merge_start(original, merge)
    merged = apply_identity_merge(original, merge)
    original_input_hash = ledger_digest(ledger_path)
    checkpoint = find_nearest(
        merge_at - timedelta(days=1),
        params.algorithm_version,
        params_digest(params.fingerprint()),
        original_input_hash,
        root=checkpoint_root,
    )
    affected_ids, affected_races = _affected_race_ids(merged, merge_at, merge.primary_id)
    baseline_state = (
        dict(baseline_final_state)
        if baseline_final_state is not None
        else dict(replay(ledger_path, params, checkpoint_root=checkpoint_root).final_state)
    )
    with tempfile.TemporaryDirectory(prefix="splits-merged-ledger-") as directory:
        merged_root = Path(directory)
        _write_ledger(merged, merged_root)
        result = replay(
            merged_root,
            params,
            from_checkpoint=checkpoint,
            checkpoint_root=checkpoint_root,
            checkpoint_input_hash=original_input_hash if checkpoint is not None else None,
            included_race_ids=frozenset(affected_races),
        )
    final_state = baseline_state
    final_state.pop(merge.secondary_id, None)
    final_state.update({athlete_id: rating for athlete_id, rating in result.final_state.items() if athlete_id in affected_ids})
    resolved = ReplayResult(
        final_state=final_state,
        run_id=result.run_id,
        input_hash=result.input_hash,
        params_hash=result.params_hash,
        resumed_from=result.resumed_from,
        saved_checkpoints=result.saved_checkpoints,
        race_count=result.race_count,
        period_count=result.period_count,
        elapsed_seconds=result.elapsed_seconds,
        season_elapsed_seconds=result.season_elapsed_seconds,
    )
    return MergeReplayResult(merge=merge, merge_at=merge_at, replay=resolved, resumed_from=checkpoint)


def materialize_identity_merge(ledger_path: Path, output_path: Path, merge: IdentityMerge) -> Path:
    """Write a standalone merged ledger. Removing the mapping leaves the source ledger untouched."""
    original = load_race_ledger(ledger_path)
    merged = apply_identity_merge(original, merge)
    if output_path.exists():
        raise FileExistsError(f"[error] 병합 레저 출력 경로가 이미 존재합니다: {output_path}")
    _write_ledger(merged, output_path)
    return output_path
