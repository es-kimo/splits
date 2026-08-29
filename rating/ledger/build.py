from __future__ import annotations

import argparse
import hashlib
import math
import shutil
from pathlib import Path
from typing import Any

import polars as pl

from .extract import _prepare_rows_for_policy, _status_filtered_participants, load_results_csv
from .ordering import build_race_sequence_map, make_ordering_key, make_race_ordering_key
from .policies import POLICIES, get_policy
from .schema import build_pairwise_view, build_ranking_view, validate_ledger
from .season import infer_season_year, race_date_token


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def _resolve_meet_id(row: dict[str, Any]) -> str:
    meet = _norm(row.get("meet_id"))
    if meet:
        return meet
    race_id = _norm(row.get("race_id"))
    if "|" in race_id:
        return _norm(race_id.split("|", 1)[0])
    return "-"


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_race_ledger(prepared_rows: pl.DataFrame, policy_name: str, policy: Any) -> pl.DataFrame:
    if prepared_rows.is_empty():
        return pl.DataFrame(
            schema={
                "ordering_key": pl.Utf8,
                "race_ordering_key": pl.Utf8,
                "race_id": pl.Utf8,
                "athlete_id": pl.Utf8,
                "rank": pl.Int64,
                "status": pl.Utf8,
                "race_date": pl.Utf8,
                "season_year": pl.Int64,
                "meet_id": pl.Utf8,
                "race_seq": pl.Int64,
                "event": pl.Utf8,
                "round": pl.Utf8,
                "round_kind": pl.Utf8,
                "round_class": pl.Utf8,
                "grade_text": pl.Utf8,
                "gender": pl.Utf8,
                "place_num": pl.Int64,
                "time_sec": pl.Float64,
                "weight": pl.Float64,
                "policy": pl.Utf8,
            }
        )

    race_seq_map = build_race_sequence_map(prepared_rows)
    out_rows: list[dict[str, Any]] = []

    for race in prepared_rows.sort(["race_id", "athlete_id", "place_num", "time_sec"], nulls_last=True).partition_by(
        "race_id", maintain_order=True
    ):
        race_rows = race.to_dicts()
        if len(race_rows) < 2:
            continue

        ranked_rows, dnf_rows, _ = _status_filtered_participants(race_rows, policy)
        if not ranked_rows and not dnf_rows:
            continue

        max_rank = max((int(row["effective_place"]) for row in ranked_rows if row.get("effective_place") is not None), default=0)
        dnf_sorted = sorted(
            dnf_rows,
            key=lambda row: (
                math.inf if row.get("time_sec") is None else float(row.get("time_sec")),
                _norm(row.get("athlete_id")),
            ),
        )

        race_athletes: list[dict[str, Any]] = []
        for row in ranked_rows:
            rank = _to_int(row.get("effective_place"))
            if rank is None or rank <= 0:
                continue
            copied = dict(row)
            copied["rank"] = rank
            race_athletes.append(copied)

        for idx, row in enumerate(dnf_sorted, start=1):
            copied = dict(row)
            copied["rank"] = max_rank + idx
            race_athletes.append(copied)

        race_athletes.sort(key=lambda row: (int(row["rank"]), _norm(row.get("athlete_id"))))

        for row in race_athletes:
            race_id = _norm(row.get("race_id"))
            athlete_id = _norm(row.get("athlete_id"))
            if not race_id or not athlete_id:
                continue

            meet_id = _resolve_meet_id(row)
            season_fallback = _to_int(row.get("season_year"))
            season_year = infer_season_year(row.get("date"), fallback_year=season_fallback)
            if season_year is None:
                raise ValueError(f"[error] season_year를 계산할 수 없습니다: race_id={race_id}")

            race_seq = race_seq_map.get(race_id, 1)
            race_date = race_date_token(row.get("date"), fallback_year=season_year)
            rank = int(row["rank"])
            status = _norm(row.get("status_norm"))

            race_ordering_key = make_race_ordering_key(
                {
                    "race_date": race_date,
                    "meet_id": meet_id,
                    "race_seq": race_seq,
                    "race_id": race_id,
                    "season_year": season_year,
                }
            )
            ordering_key = make_ordering_key(
                {
                    "race_date": race_date,
                    "meet_id": meet_id,
                    "race_seq": race_seq,
                    "race_id": race_id,
                    "rank": rank,
                    "athlete_id": athlete_id,
                    "season_year": season_year,
                }
            )
            out_rows.append(
                {
                    "ordering_key": ordering_key,
                    "race_ordering_key": race_ordering_key,
                    "race_id": race_id,
                    "athlete_id": athlete_id,
                    "rank": rank,
                    "status": status,
                    "race_date": race_date,
                    "season_year": season_year,
                    "meet_id": meet_id,
                    "race_seq": int(race_seq),
                    "event": _norm(row.get("event")),
                    "round": _norm(row.get("round")),
                    "round_kind": _norm(row.get("round_kind")),
                    "round_class": _norm(row.get("round_class")),
                    "grade_text": _norm(row.get("grade_text")),
                    "gender": _norm(row.get("gender")),
                    "place_num": _to_int(row.get("place_num")),
                    "time_sec": _to_float(row.get("time_sec")),
                    "weight": float(row.get("round_weight") or 1.0),
                    "policy": policy_name,
                }
            )

    if not out_rows:
        return pl.DataFrame()
    return pl.DataFrame(out_rows).sort(["ordering_key", "athlete_id"], nulls_last=True)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_parquet_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*.parquet")):
        rel = path.relative_to(root).as_posix()
        out[rel] = _digest(path)
    return out


def _write_partitioned(df: pl.DataFrame, target_root: Path, sort_cols: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    previous_hashes = _snapshot_parquet_hashes(target_root)
    tmp_root = target_root.with_name(f"{target_root.name}.tmp")
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)

    if not df.is_empty():
        seasons = sorted({int(value) for value in df["season_year"].to_list() if value is not None})
        for season in seasons:
            season_dir = tmp_root / f"season={season}"
            season_dir.mkdir(parents=True, exist_ok=True)
            part_path = season_dir / "part.parquet"
            season_frame = df.filter(pl.col("season_year") == int(season)).sort(sort_cols, nulls_last=True)
            season_frame.write_parquet(part_path)

    new_hashes = _snapshot_parquet_hashes(tmp_root)
    if target_root.exists():
        shutil.rmtree(target_root)
    tmp_root.rename(target_root)
    return previous_hashes, new_hashes


def _warn_hash_drift(label: str, previous_hashes: dict[str, str], new_hashes: dict[str, str]) -> None:
    if not previous_hashes:
        return
    if previous_hashes == new_hashes:
        print(f"[ok] {label} hash unchanged")
        return
    changed = 0
    keys = set(previous_hashes).union(new_hashes)
    for key in keys:
        if previous_hashes.get(key) != new_hashes.get(key):
            changed += 1
    print(f"[warn] {label} hash drift detected: {changed} files changed")


def _assert_pairwise_equivalence(reference: pl.DataFrame, derived: pl.DataFrame) -> None:
    ref_keyed = reference.select(["race_id", "winner_id", "loser_id", "source_status"]).sort(
        ["race_id", "winner_id", "loser_id", "source_status"], nulls_last=True
    )
    derived_keyed = derived.select(["race_id", "winner_id", "loser_id", "source_status"]).sort(
        ["race_id", "winner_id", "loser_id", "source_status"], nulls_last=True
    )
    if ref_keyed.to_dicts() != derived_keyed.to_dicts():
        raise ValueError("[error] race_ledger에서 파생한 pairwise_view가 R-02 pairwise 결과와 다릅니다.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-03 race_ledger와 파생 뷰를 생성합니다.")
    parser.add_argument("--results", required=True, help="입력 CSV 경로")
    parser.add_argument("--policy", default="conservative", choices=sorted(POLICIES.keys()), help="정책 프리셋")
    parser.add_argument("--out", default="out/ledger", help="출력 디렉터리")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    policy = get_policy(args.policy)
    results_path = Path(args.results).expanduser()
    out_root = Path(args.out).expanduser()

    results = load_results_csv(results_path)
    _, prepared_rows, _ = _prepare_rows_for_policy(results, policy)
    race_ledger = _build_race_ledger(prepared_rows, args.policy, policy)
    if race_ledger.is_empty():
        raise ValueError("[error] race_ledger가 비어 있습니다.")

    validate_ledger(race_ledger)
    pairwise_view = build_pairwise_view(race_ledger)
    ranking_view = build_ranking_view(race_ledger)

    if not prepared_rows.is_empty():
        # Rebuild once from source to verify race_ledger derived pairwise is lossless.
        from .extract import _build_comparisons

        reference_pairwise = _build_comparisons(prepared_rows, policy)
        _assert_pairwise_equivalence(reference_pairwise, pairwise_view)

    race_root = out_root / "race_ledger"
    pairwise_root = out_root / "pairwise_view"
    ranking_root = out_root / "ranking_view"

    prev_race, next_race = _write_partitioned(race_ledger, race_root, ["ordering_key", "athlete_id"])
    prev_pair, next_pair = _write_partitioned(pairwise_view, pairwise_root, ["ordering_key", "winner_id", "loser_id"])
    prev_rank, next_rank = _write_partitioned(ranking_view, ranking_root, ["ordering_key", "athlete_id"])

    _warn_hash_drift("race_ledger", prev_race, next_race)
    _warn_hash_drift("pairwise_view", prev_pair, next_pair)
    _warn_hash_drift("ranking_view", prev_rank, next_rank)

    print(f"[ok] policy={args.policy}")
    print(f"[ok] prepared_rows={prepared_rows.height:,}")
    print(f"[ok] race_ledger_rows={race_ledger.height:,}")
    print(f"[ok] pairwise_rows={pairwise_view.height:,}")
    print(f"[ok] ranking_rows={ranking_view.height:,}")
    print(f"[ok] out={out_root}")


if __name__ == "__main__":
    main()
