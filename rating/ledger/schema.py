from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import polars as pl

from .ordering import make_ordering_key, make_pairwise_ordering_key
from .policies import ROUND_FINAL, ROUND_FINAL_B, ROUND_HEAT, ROUND_OTHER, ROUND_QUARTERFINAL, ROUND_SEMIFINAL

STATUS_FIN = "FIN"
STATUS_PEN = "PEN"
STATUS_DNF = "DNF"
STATUS_DNS = "DNS"
STATUS_ADV = "ADV"

KNOWN_ROUND_CLASSES = frozenset({ROUND_HEAT, ROUND_QUARTERFINAL, ROUND_SEMIFINAL, ROUND_FINAL, ROUND_FINAL_B, ROUND_OTHER})
KNOWN_STATUSES = frozenset({STATUS_FIN, STATUS_PEN, STATUS_DNF, STATUS_DNS, STATUS_ADV})

RACE_LEDGER_SCHEMA: dict[str, pl.DataType] = {
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
    "place_num": pl.Int64,
    "time_sec": pl.Float64,
    "weight": pl.Float64,
}

RACE_LEDGER_OPTIONAL_COLUMNS: dict[str, pl.Expr] = {
    "grade_text": pl.lit("").cast(pl.Utf8),
    "gender": pl.lit("").cast(pl.Utf8),
    "division_text": pl.lit("").cast(pl.Utf8),
    "birth_year": pl.lit(None).cast(pl.Int64),
}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def _ensure_required_columns(frame: pl.DataFrame, required: set[str]) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"[error] race_ledger 필수 컬럼이 없습니다: {', '.join(missing)}")


def _ensure_no_nulls(frame: pl.DataFrame, columns: list[str]) -> None:
    null_columns = [name for name in columns if int(frame[name].null_count()) > 0]
    if null_columns:
        joined = ", ".join(sorted(null_columns))
        raise ValueError(f"[error] race_ledger null 허용 불가 컬럼에 null 값이 있습니다: {joined}")


def _ensure_non_empty_strings(frame: pl.DataFrame, columns: list[str]) -> None:
    bad_columns = []
    for name in columns:
        if frame.filter(pl.col(name).cast(pl.Utf8, strict=False).str.strip_chars() == "").height > 0:
            bad_columns.append(name)
    if bad_columns:
        joined = ", ".join(sorted(bad_columns))
        raise ValueError(f"[error] race_ledger 빈 문자열 허용 불가 컬럼이 있습니다: {joined}")


def _ensure_unique(frame: pl.DataFrame, columns: list[str], label: str) -> None:
    duplicate = frame.group_by(columns).len().filter(pl.col("len") > 1)
    if duplicate.is_empty():
        return
    raise ValueError(f"[error] {label} 중복이 있습니다 (중복 그룹 {duplicate.height}개)")


def _ensure_known_values(frame: pl.DataFrame, column: str, allowed: frozenset[str], label: str) -> None:
    invalid = (
        frame.select(pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars().alias(column))
        .filter(~pl.col(column).is_in(sorted(allowed)))
        .select(column)
        .unique()
        .sort(column)
    )
    if invalid.is_empty():
        return
    values = ", ".join(_norm(value) for value in invalid[column].to_list())
    raise ValueError(f"[error] {label} 허용값 외 항목이 있습니다: {values}")


def _with_optional_columns(frame: pl.DataFrame) -> pl.DataFrame:
    missing_exprs: list[pl.Expr] = []
    for name, expr in RACE_LEDGER_OPTIONAL_COLUMNS.items():
        if name not in frame.columns:
            missing_exprs.append(expr.alias(name))
    if not missing_exprs:
        return frame
    return frame.with_columns(missing_exprs)


def build_ranking_view(race_ledger: pl.DataFrame) -> pl.DataFrame:
    _ensure_required_columns(race_ledger, set(RACE_LEDGER_SCHEMA.keys()))
    normalized = _with_optional_columns(race_ledger)
    return normalized.sort(["ordering_key", "athlete_id"], nulls_last=True).select(
        [
            "ordering_key",
            "race_ordering_key",
            "race_id",
            "athlete_id",
            "rank",
            "status",
            "race_date",
            "season_year",
            "meet_id",
            "race_seq",
            "event",
            "round",
            "round_kind",
            "round_class",
            "grade_text",
            "gender",
            "division_text",
            "birth_year",
            "weight",
        ]
    )


def build_pairwise_view(race_ledger: pl.DataFrame) -> pl.DataFrame:
    _ensure_required_columns(race_ledger, set(RACE_LEDGER_SCHEMA.keys()))
    normalized = _with_optional_columns(race_ledger)

    out_rows: list[dict[str, Any]] = []
    for race in normalized.sort(["race_ordering_key", "rank", "athlete_id"], nulls_last=True).partition_by(
        "race_id", maintain_order=True
    ):
        race_rows = race.to_dicts()
        if len(race_rows) < 2:
            continue

        ranked_rows = [row for row in race_rows if _norm(row.get("status")) in {STATUS_FIN, STATUS_ADV, STATUS_PEN}]
        ranked_rows.sort(key=lambda row: (int(row.get("rank") or 0), _norm(row.get("athlete_id"))))
        finishers = [row for row in race_rows if _norm(row.get("status")) in {STATUS_FIN, STATUS_ADV}]
        finishers.sort(key=lambda row: (int(row.get("rank") or 0), _norm(row.get("athlete_id"))))
        dnf_rows = [row for row in race_rows if _norm(row.get("status")) == STATUS_DNF]
        dnf_rows.sort(key=lambda row: (int(row.get("rank") or 0), _norm(row.get("athlete_id"))))

        for left_idx in range(len(ranked_rows)):
            winner = ranked_rows[left_idx]
            for right_idx in range(left_idx + 1, len(ranked_rows)):
                loser = ranked_rows[right_idx]
                winner_rank = int(winner.get("rank") or 0)
                loser_rank = int(loser.get("rank") or 0)
                if winner_rank <= 0 or loser_rank <= 0 or winner_rank == loser_rank:
                    continue
                out_rows.append(
                    {
                        "race_id": _norm(winner.get("race_id")),
                        "winner_id": _norm(winner.get("athlete_id")),
                        "loser_id": _norm(loser.get("athlete_id")),
                        "winner_rank": winner_rank,
                        "loser_rank": loser_rank,
                        "winner_status": _norm(winner.get("status")),
                        "loser_status": _norm(loser.get("status")),
                        "source_status": f"{_norm(winner.get('status'))}-{_norm(loser.get('status'))}",
                        "round": _norm(winner.get("round")),
                        "round_kind": _norm(winner.get("round_kind")),
                        "round_class": _norm(winner.get("round_class")),
                        "event": _norm(winner.get("event")),
                        "grade_text": _norm(winner.get("grade_text")),
                        "gender": _norm(winner.get("gender")),
                        "division_text": _norm(winner.get("division_text")),
                        "birth_year": int(winner.get("birth_year")) if winner.get("birth_year") is not None else None,
                        "race_date": _norm(winner.get("race_date")),
                        "season_year": int(winner.get("season_year") or 0),
                        "meet_id": _norm(winner.get("meet_id")),
                        "race_seq": int(winner.get("race_seq") or 0),
                        "weight": float(winner.get("weight") or 1.0),
                    }
                )

        for loser in dnf_rows:
            for winner in finishers:
                out_rows.append(
                    {
                        "race_id": _norm(winner.get("race_id")),
                        "winner_id": _norm(winner.get("athlete_id")),
                        "loser_id": _norm(loser.get("athlete_id")),
                        "winner_rank": int(winner.get("rank") or 0),
                        "loser_rank": int(loser.get("rank") or 0),
                        "winner_status": _norm(winner.get("status")),
                        "loser_status": _norm(loser.get("status")),
                        "source_status": f"{_norm(winner.get('status'))}-{_norm(loser.get('status'))}",
                        "round": _norm(winner.get("round")),
                        "round_kind": _norm(winner.get("round_kind")),
                        "round_class": _norm(winner.get("round_class")),
                        "event": _norm(winner.get("event")),
                        "grade_text": _norm(winner.get("grade_text")),
                        "gender": _norm(winner.get("gender")),
                        "division_text": _norm(winner.get("division_text")),
                        "birth_year": int(winner.get("birth_year")) if winner.get("birth_year") is not None else None,
                        "race_date": _norm(winner.get("race_date")),
                        "season_year": int(winner.get("season_year") or 0),
                        "meet_id": _norm(winner.get("meet_id")),
                        "race_seq": int(winner.get("race_seq") or 0),
                        "weight": float(winner.get("weight") or 1.0),
                    }
                )

    if not out_rows:
        return pl.DataFrame(
            schema={
                "ordering_key": pl.Utf8,
                "race_id": pl.Utf8,
                "winner_id": pl.Utf8,
                "loser_id": pl.Utf8,
                "winner_rank": pl.Int64,
                "loser_rank": pl.Int64,
                "winner_status": pl.Utf8,
                "loser_status": pl.Utf8,
                "source_status": pl.Utf8,
                "round": pl.Utf8,
                "round_kind": pl.Utf8,
                "round_class": pl.Utf8,
                "event": pl.Utf8,
                "grade_text": pl.Utf8,
                "gender": pl.Utf8,
                "division_text": pl.Utf8,
                "birth_year": pl.Int64,
                "race_date": pl.Utf8,
                "season_year": pl.Int64,
                "meet_id": pl.Utf8,
                "race_seq": pl.Int64,
                "weight": pl.Float64,
            }
        )

    out = pl.DataFrame(out_rows).with_columns(
        pl.struct(["race_date", "meet_id", "race_seq", "race_id", "winner_id", "loser_id"])
        .map_elements(make_pairwise_ordering_key, return_dtype=pl.Utf8)
        .alias("ordering_key")
    )
    return out.sort(["ordering_key", "winner_id", "loser_id"], nulls_last=True).select(
        [
            "ordering_key",
            "race_id",
            "winner_id",
            "loser_id",
            "winner_rank",
            "loser_rank",
            "winner_status",
            "loser_status",
            "source_status",
            "round",
            "round_kind",
            "round_class",
            "event",
            "grade_text",
            "gender",
            "division_text",
            "birth_year",
            "race_date",
            "season_year",
            "meet_id",
            "race_seq",
            "weight",
        ]
    )


MAX_RANK_TIE_MULTIPLICITY = 3

_RACE_KEY_HINT = (
    "race_id가 서로 다른 부문을 하나의 레이스로 병합하고 있을 가능성이 높습니다. "
    "extract._build_reconstructed_race_id의 부문(division) 성분을 확인하세요."
)


def assert_rank_ties_are_consistent(frame: pl.DataFrame) -> None:
    """같은 순위를 공유하는 참가자는 진짜 동착이어야 합니다.

    동착(같은 기록으로 공동 순위)은 원천에 실제로 존재하므로 허용합니다. 다만
    기록이 서로 다른데 순위만 같고 인원도 과도하게 몰리면 동착이 아니라 레이스
    키가 너무 성겨서 서로 다른 부문이 병합된 신호로 봅니다.
    """
    ranked = frame.filter(pl.col("rank") > 0)
    if ranked.is_empty():
        return

    grouped = ranked.group_by(["race_ordering_key", "rank"]).agg(
        pl.len().alias("n"),
        pl.col("time_sec").drop_nulls().n_unique().alias("distinct_non_null_times"),
    )

    crowded = grouped.filter((pl.col("n") > MAX_RANK_TIE_MULTIPLICITY) & (pl.col("distinct_non_null_times") > 1))
    if not crowded.is_empty():
        worst = crowded.sort(["n", "race_ordering_key", "rank"], descending=[True, False, False]).row(0, named=True)
        raise ValueError(
            f"[error] 한 순위에 {MAX_RANK_TIE_MULTIPLICITY}명을 넘는 참가자가 있습니다. "
            f"위반 {crowded.height:,}건, 최다 {worst['n']}명 "
            f"(race_ordering_key={worst['race_ordering_key']}, rank={worst['rank']}). " + _RACE_KEY_HINT
        )

    inconsistent = grouped.filter((pl.col("n") > 1) & (pl.col("distinct_non_null_times") > 1))
    if not inconsistent.is_empty():
        worst = inconsistent.sort(["race_ordering_key", "rank"]).row(0, named=True)
        raise ValueError(
            "[error] 같은 순위인데 기록이 서로 다릅니다. 동착이 아닙니다. "
            f"위반 {inconsistent.height:,}건 "
            f"(race_ordering_key={worst['race_ordering_key']}, rank={worst['rank']}, "
            f"서로 다른 기록 {worst['distinct_non_null_times']}종). " + _RACE_KEY_HINT
        )


def validate_ledger(df: pl.DataFrame) -> None:
    required = set(RACE_LEDGER_SCHEMA.keys())
    _ensure_required_columns(df, required)
    _ensure_no_nulls(
        df,
        [
            "ordering_key",
            "race_ordering_key",
            "race_id",
            "athlete_id",
            "rank",
            "status",
            "race_date",
            "season_year",
            "meet_id",
            "race_seq",
            "round_class",
            "weight",
        ],
    )
    _ensure_non_empty_strings(
        df,
        [
            "ordering_key",
            "race_ordering_key",
            "race_id",
            "athlete_id",
            "status",
            "race_date",
            "meet_id",
            "round_class",
        ],
    )

    if df.filter(pl.col("rank") <= 0).height > 0:
        raise ValueError("[error] race_ledger rank는 1 이상의 정수여야 합니다.")
    if df.filter(pl.col("race_seq") <= 0).height > 0:
        raise ValueError("[error] race_ledger race_seq는 1 이상의 정수여야 합니다.")

    _ensure_unique(df, ["ordering_key"], "race_ledger ordering_key")
    _ensure_unique(df, ["race_id", "athlete_id"], "race_ledger race_id+athlete_id")
    assert_rank_ties_are_consistent(df)
    _ensure_known_values(df, "round_class", KNOWN_ROUND_CLASSES, "round_class")
    _ensure_known_values(df, "status", KNOWN_STATUSES, "status")

    recomputed = df.with_columns(
        pl.struct(["race_date", "meet_id", "race_seq", "race_id", "rank", "athlete_id"])
        .map_elements(make_ordering_key, return_dtype=pl.Utf8)
        .alias("_computed_ordering_key")
    )
    mismatch = recomputed.filter(pl.col("ordering_key") != pl.col("_computed_ordering_key"))
    if not mismatch.is_empty():
        raise ValueError("[error] race_ledger ordering_key가 규약(make_ordering_key)과 일치하지 않습니다.")

    pairwise = build_pairwise_view(df)
    if pairwise.filter(pl.col("winner_id") == pl.col("loser_id")).height > 0:
        raise ValueError("[error] pairwise_view에서 winner_id == loser_id 행이 발견되었습니다.")


def load_race_ledger(path: Path) -> pl.DataFrame:
    target = path
    if path.is_dir() and (path / "race_ledger").exists():
        target = path / "race_ledger"

    parquet_paths: list[Path] = []
    if target.is_file():
        parquet_paths = [target]
    elif target.is_dir():
        parquet_paths = sorted(target.rglob("*.parquet"))
    else:
        raise FileNotFoundError(f"[error] race_ledger 경로를 찾을 수 없습니다: {path}")

    if not parquet_paths:
        raise FileNotFoundError(f"[error] parquet 파일이 없습니다: {target}")

    frames = [pl.read_parquet(parquet_path) for parquet_path in parquet_paths]
    if len(frames) == 1:
        return frames[0]
    return pl.concat(frames, how="vertical_relaxed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-03 race_ledger 검증 도구")
    parser.add_argument("--validate", required=True, help="race_ledger 디렉터리 또는 parquet 파일 경로")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    frame = load_race_ledger(Path(args.validate).expanduser())
    validate_ledger(frame)
    print(f"[ok] validated_rows={frame.height:,}")
    print(f"[ok] path={args.validate}")


if __name__ == "__main__":
    main()
