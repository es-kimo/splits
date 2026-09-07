from __future__ import annotations

import argparse
import csv
import hashlib
import os
from datetime import date
from pathlib import Path
from typing import NamedTuple, Sequence

import polars as pl

from rating.replay.registry import DEFAULT_REGISTRY_ROOT, RatingRegistry


class FilteredRating(NamedTuple):
    mu: float
    sigma: float
    run_id: str
    as_of: date


class SmoothedRating(NamedTuple):
    mu: float
    sigma: float
    run_id: str
    valid_date: date


def _number(row: dict[str, object], key: str) -> float:
    value = row[key]
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"[error] 레이팅 스냅샷 {key} 값이 숫자가 아닙니다.")


def rating_as_of(
    athlete_id: str,
    t: date,
    run_id: str,
    *,
    registry: RatingRegistry | None = None,
) -> FilteredRating:
    source = registry or RatingRegistry(DEFAULT_REGISTRY_ROOT)
    row = source.filtered_snapshot_as_of(athlete_id, t, run_id)
    if row is None:
        raise LookupError(f"[error] 해당 기준일 이전의 필터 레이팅이 없습니다: athlete_id={athlete_id}, as_of={t}")
    return FilteredRating(
        mu=_number(row, "mu"),
        sigma=_number(row, "sigma"),
        run_id=run_id,
        as_of=t,
    )


def rating_retrospective(
    athlete_id: str,
    t: date,
    run_id: str,
    *,
    registry: RatingRegistry | None = None,
) -> SmoothedRating:
    source = registry or RatingRegistry(DEFAULT_REGISTRY_ROOT)
    row = source.smoothed_snapshot_as_of(athlete_id, t, run_id)
    if row is None:
        raise LookupError(f"[error] 해당 기준일 이전의 스무딩 레이팅이 없습니다: athlete_id={athlete_id}, valid_date={t}")
    return SmoothedRating(
        mu=_number(row, "mu"),
        sigma=_number(row, "sigma"),
        run_id=run_id,
        valid_date=date.fromisoformat(str(row["valid_date"])),
    )


def compare_filter_smoother(
    *,
    athlete_ids: Sequence[str],
    run_id: str,
    registry: RatingRegistry,
    at: date | None = None,
) -> str:
    selected = set(athlete_ids)
    filtered = registry.load_snapshots(run_id).snapshots.select(
        ["athlete_id", "valid_date", pl.col("mu").alias("filtered_mu"), pl.col("sigma").alias("filtered_sigma")]
    )
    smoothed = registry.load_smoothed_snapshots(run_id).snapshots.select(
        ["athlete_id", "valid_date", pl.col("mu").alias("smoothed_mu"), pl.col("sigma").alias("smoothed_sigma")]
    )
    if at is not None:
        filtered = filtered.filter(pl.col("valid_date") <= at)
        smoothed = smoothed.filter(pl.col("valid_date") <= at)
        filtered = filtered.sort("valid_date").group_by("athlete_id").last()
        smoothed = smoothed.sort("valid_date").group_by("athlete_id").last()
        joined = filtered.join(smoothed, on="athlete_id", how="inner")
    else:
        joined = filtered.join(smoothed, on=["athlete_id", "valid_date"], how="inner")
    if selected:
        joined = joined.filter(pl.col("athlete_id").is_in(selected))
    rows = sorted(
        joined.to_dicts(),
        key=lambda row: abs(float(row["smoothed_mu"]) - float(row["filtered_mu"])),
        reverse=True,
    )
    if not rows:
        raise LookupError("[error] 선택한 선수와 기준일에 모두 존재하는 필터·스무딩 레이팅이 없습니다.")
    lines = [
        "# Filter vs smoother report",
        "",
        f"- run_id: `{run_id}`",
        f"- 기준일: `{at.isoformat()}`" if at is not None else "- 기준일: 모든 공통 rating period",
        "- 스무딩 값은 회고 분석 전용이며 예측·백테스트에 사용하지 않습니다.",
        "",
        "| athlete_id | valid date | filtered mu | smoothed mu | difference | filtered sigma | smoothed sigma |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        (
            f"| {row['athlete_id']} | {row['valid_date']} | {float(row['filtered_mu']):.4f} | "
            f"{float(row['smoothed_mu']):.4f} | {float(row['smoothed_mu']) - float(row['filtered_mu']):+.4f} | "
            f"{float(row['filtered_sigma']):.4f} | {float(row['smoothed_sigma']):.4f} |"
        )
        for row in rows
    )
    lines.append("")
    return "\n".join(lines)


def _national_team_athlete_ids() -> list[str]:
    salt = os.environ.get("SPLITS_ANON_SALT", "").strip()
    if not salt:
        raise ValueError("[error] 국가대표 선택에는 SPLITS_ANON_SALT가 필요합니다.")
    public_path = Path("data/public_figures.csv")
    if not public_path.exists():
        raise FileNotFoundError(f"[error] 국가대표 목록 파일이 없습니다: {public_path}")
    athlete_ids: list[str] = []
    with public_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("상태", "").strip() != "active" or "국가대표" not in row.get("지정근거", ""):
                continue
            id_no = row.get("idNo", "").strip()
            if id_no:
                athlete_ids.append(hashlib.sha256(f"{id_no}{salt}".encode("utf-8")).hexdigest()[:12])
    if not athlete_ids:
        raise LookupError("[error] 비교할 공개 국가대표 선수가 없습니다.")
    return sorted(set(athlete_ids))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="필터 레이팅과 회고 스무딩 레이팅을 비교합니다")
    parser.add_argument("--registry-root", default=str(DEFAULT_REGISTRY_ROOT), help="레이팅 실행 레지스트리 루트")
    parser.add_argument("--run-id", help="완료된 실행 ID; 생략하면 current 실행을 사용합니다")
    parser.add_argument("--at", help="기준일 (YYYY-MM-DD); 생략하면 모든 공통 period를 비교합니다")
    parser.add_argument("--compare-filter-smoother", action="store_true", help="필터와 스무딩 차이 보고서를 생성합니다")
    parser.add_argument("--athletes", choices=["national_team"], help="비교 대상 선수 집합")
    parser.add_argument("--athlete-id", action="append", help="비교할 선수 ID; 여러 번 지정할 수 있습니다")
    parser.add_argument("--out", required=True, help="Markdown 보고서 경로")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.compare_filter_smoother:
        raise ValueError("[error] --compare-filter-smoother를 지정하세요.")
    athlete_ids = list(args.athlete_id or [])
    if args.athletes == "national_team":
        athlete_ids.extend(_national_team_athlete_ids())
    if not athlete_ids:
        raise ValueError("[error] --athletes 또는 --athlete-id를 하나 이상 지정하세요.")
    registry = RatingRegistry(Path(args.registry_root).expanduser())
    run_id = args.run_id or registry.current_run_id()
    report = compare_filter_smoother(
        athlete_ids=athlete_ids,
        at=date.fromisoformat(args.at) if args.at else None,
        run_id=run_id,
        registry=registry,
    )
    output = Path(args.out).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[ok] report={output}")


if __name__ == "__main__":
    main()
