from __future__ import annotations

import argparse
import hashlib
import math
import shutil
from collections import Counter
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
                "division_text": pl.Utf8,
                "birth_year": pl.Int64,
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
                    "division_text": _norm(row.get("division_text")),
                    "birth_year": _to_int(row.get("birth_year")),
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


def _dominant_value(counter: Counter[str]) -> str:
    if not counter:
        return ""
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _norm_sex(value: Any) -> str:
    text = _norm(value)
    if not text:
        return ""
    return text[0]


def _build_athlete_meta(prepared_rows: pl.DataFrame) -> pl.DataFrame:
    schema = {
        "athlete_id": pl.Utf8,
        "birth_year": pl.Int64,
        "sex": pl.Utf8,
        "debut_season": pl.Int64,
        "debut_division": pl.Utf8,
        "last_season": pl.Int64,
        "n_seasons": pl.Int64,
    }
    if prepared_rows.is_empty():
        return pl.DataFrame(schema=schema)

    stats: dict[str, dict[str, Any]] = {}
    for row in prepared_rows.to_dicts():
        athlete_id = _norm(row.get("athlete_id"))
        if not athlete_id:
            continue
        season_year = _to_int(row.get("season_year"))
        birth_year = _to_int(row.get("birth_year"))
        if birth_year is not None and (birth_year < 1900 or birth_year > 2099):
            birth_year = None

        division_text = _norm(row.get("division_text"))
        sex = _norm(row.get("gender"))

        node = stats.setdefault(
            athlete_id,
            {
                "birth_years": set(),
                "sex_counts": Counter(),
                "season_divisions": {},
                "seasons": set(),
            },
        )
        if birth_year is not None:
            node["birth_years"].add(int(birth_year))
        if sex:
            node["sex_counts"][sex] += 1
        if season_year is not None:
            node["seasons"].add(int(season_year))
            if division_text:
                season_divisions: dict[int, Counter[str]] = node["season_divisions"]
                season_counter = season_divisions.setdefault(int(season_year), Counter())
                season_counter[division_text] += 1

    rows: list[dict[str, Any]] = []
    for athlete_id in sorted(stats.keys()):
        node = stats[athlete_id]
        birth_years = sorted(node["birth_years"])
        if len(birth_years) > 1:
            raise ValueError(f"[error] athlete_meta 출생연도 충돌: athlete_id={athlete_id}, years={birth_years}")
        seasons = sorted(node["seasons"])
        if not seasons:
            continue
        debut_season = int(seasons[0])
        last_season = int(seasons[-1])
        sex = _dominant_value(node["sex_counts"])
        debut_counter = node["season_divisions"].get(debut_season, Counter())
        debut_division = _dominant_value(debut_counter)
        rows.append(
            {
                "athlete_id": athlete_id,
                "birth_year": birth_years[0] if birth_years else None,
                "sex": sex,
                "debut_season": debut_season,
                "debut_division": debut_division,
                "last_season": last_season,
                "n_seasons": int(len(seasons)),
            }
        )
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema).sort("athlete_id")


def _load_external_athlete_meta(path: Path) -> pl.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"[error] athlete meta 파일이 없습니다: {path}")
    if path.suffix.lower() == ".parquet":
        raw = pl.read_parquet(path)
    else:
        raw = pl.read_csv(path, encoding="utf8-lossy")

    id_aliases = ["athlete_id", "익명키", "idNo"]
    birth_aliases = ["birth_year", "출생연도", "출생년도"]
    sex_aliases = ["sex", "성별", "gender"]

    def _pick(aliases: list[str]) -> str | None:
        for alias in aliases:
            if alias in raw.columns:
                return alias
        return None

    id_col = _pick(id_aliases)
    if id_col is None:
        raise ValueError(f"[error] athlete meta에 선수 키 컬럼이 없습니다: {', '.join(id_aliases)}")
    birth_col = _pick(birth_aliases)
    sex_col = _pick(sex_aliases)

    stats: dict[str, dict[str, Any]] = {}
    for row in raw.to_dicts():
        athlete_id = _norm(row.get(id_col))
        if not athlete_id:
            continue
        birth_year = _to_int(row.get(birth_col)) if birth_col is not None else None
        if birth_year is not None and (birth_year < 1900 or birth_year > 2099):
            birth_year = None
        sex = _norm_sex(row.get(sex_col)) if sex_col is not None else ""

        node = stats.setdefault(athlete_id, {"birth_years": set(), "sexes": set()})
        if birth_year is not None:
            node["birth_years"].add(int(birth_year))
        if sex:
            node["sexes"].add(sex)

    rows: list[dict[str, Any]] = []
    for athlete_id in sorted(stats.keys()):
        node = stats[athlete_id]
        birth_years = sorted(node["birth_years"])
        sexes = sorted(node["sexes"])
        if len(birth_years) > 1:
            raise ValueError(f"[error] 외부 athlete meta 출생연도 충돌: athlete_id={athlete_id}, years={birth_years}")
        if len(sexes) > 1:
            raise ValueError(f"[error] 외부 athlete meta 성별 충돌: athlete_id={athlete_id}, values={sexes}")
        rows.append(
            {
                "athlete_id": athlete_id,
                "birth_year": birth_years[0] if birth_years else None,
                "sex": sexes[0] if sexes else "",
            }
        )
    if not rows:
        return pl.DataFrame(schema={"athlete_id": pl.Utf8, "birth_year": pl.Int64, "sex": pl.Utf8})
    return pl.DataFrame(rows, schema={"athlete_id": pl.Utf8, "birth_year": pl.Int64, "sex": pl.Utf8}).sort("athlete_id")


def _merge_external_athlete_meta(base: pl.DataFrame, external: pl.DataFrame) -> pl.DataFrame:
    if external.is_empty():
        return base
    merged = base.join(
        external.rename({"birth_year": "birth_year_ext", "sex": "sex_ext"}),
        on="athlete_id",
        how="left",
    )

    birth_conflict = merged.filter(
        pl.col("birth_year").is_not_null()
        & pl.col("birth_year_ext").is_not_null()
        & (pl.col("birth_year") != pl.col("birth_year_ext"))
    )
    if birth_conflict.height > 0:
        row = birth_conflict.select(["athlete_id", "birth_year", "birth_year_ext"]).row(0, named=True)
        raise ValueError(
            "[error] athlete meta 출생연도 충돌: "
            f"athlete_id={row['athlete_id']}, base={row['birth_year']}, external={row['birth_year_ext']}"
        )

    sex_conflict = merged.filter(
        (pl.col("sex").cast(pl.Utf8, strict=False).str.strip_chars() != "")
        & (pl.col("sex_ext").cast(pl.Utf8, strict=False).str.strip_chars() != "")
        & (pl.col("sex") != pl.col("sex_ext"))
    )
    if sex_conflict.height > 0:
        row = sex_conflict.select(["athlete_id", "sex", "sex_ext"]).row(0, named=True)
        raise ValueError(
            "[error] athlete meta 성별 충돌: "
            f"athlete_id={row['athlete_id']}, base={row['sex']}, external={row['sex_ext']}"
        )

    return (
        merged.with_columns(
            [
                pl.coalesce([pl.col("birth_year"), pl.col("birth_year_ext")]).cast(pl.Int64).alias("birth_year"),
                pl.when(pl.col("sex").cast(pl.Utf8, strict=False).str.strip_chars() != "")
                .then(pl.col("sex"))
                .otherwise(pl.col("sex_ext"))
                .cast(pl.Utf8)
                .fill_null("")
                .alias("sex"),
            ]
        )
        .drop(["birth_year_ext", "sex_ext"])
        .sort("athlete_id")
    )


def _write_athlete_meta(meta: pl.DataFrame, out_path: Path) -> tuple[str | None, str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    previous = _digest(out_path) if out_path.exists() else None
    tmp_path = out_path.with_name(f"{out_path.name}.tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    meta.sort("athlete_id").write_parquet(tmp_path)
    current = _digest(tmp_path)
    tmp_path.replace(out_path)
    return previous, current


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-03 race_ledger와 파생 뷰를 생성합니다.")
    parser.add_argument("--results", required=True, help="입력 CSV 경로")
    parser.add_argument("--policy", default="conservative", choices=sorted(POLICIES.keys()), help="정책 프리셋")
    parser.add_argument("--out", default="out/ledger", help="출력 디렉터리")
    parser.add_argument("--athlete-meta", default="", help="외부 선수 메타(CSV/Parquet) 경로")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    policy = get_policy(args.policy)
    results_path = Path(args.results).expanduser()
    out_root = Path(args.out).expanduser()

    results = load_results_csv(results_path)
    prepared_all, prepared_rows, _ = _prepare_rows_for_policy(results, policy)
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
    athlete_meta_path = out_root / "athlete_meta.parquet"

    prev_race, next_race = _write_partitioned(race_ledger, race_root, ["ordering_key", "athlete_id"])
    prev_pair, next_pair = _write_partitioned(pairwise_view, pairwise_root, ["ordering_key", "winner_id", "loser_id"])
    prev_rank, next_rank = _write_partitioned(ranking_view, ranking_root, ["ordering_key", "athlete_id"])
    athlete_meta = _build_athlete_meta(prepared_all)
    if args.athlete_meta:
        external_meta = _load_external_athlete_meta(Path(args.athlete_meta).expanduser())
        athlete_meta = _merge_external_athlete_meta(athlete_meta, external_meta)
    prev_meta, next_meta = _write_athlete_meta(athlete_meta, athlete_meta_path)

    _warn_hash_drift("race_ledger", prev_race, next_race)
    _warn_hash_drift("pairwise_view", prev_pair, next_pair)
    _warn_hash_drift("ranking_view", prev_rank, next_rank)
    if prev_meta is not None:
        if prev_meta == next_meta:
            print("[ok] athlete_meta hash unchanged")
        else:
            print("[warn] athlete_meta hash drift detected")

    print(f"[ok] policy={args.policy}")
    print(f"[ok] prepared_rows={prepared_rows.height:,}")
    print(f"[ok] race_ledger_rows={race_ledger.height:,}")
    print(f"[ok] pairwise_rows={pairwise_view.height:,}")
    print(f"[ok] ranking_rows={ranking_view.height:,}")
    print(f"[ok] athlete_meta_rows={athlete_meta.height:,}")
    print(f"[ok] athlete_meta={athlete_meta_path}")
    print(f"[ok] out={out_root}")


if __name__ == "__main__":
    main()
