from __future__ import annotations

import argparse
import csv
import hashlib
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from rating.ledger.schema import load_race_ledger, validate_ledger
from rating.ledger.season import parse_kst_date

from .glicko2 import Glicko2Engine, Glicko2Params, Rating
from .types import EngineName, RaceEntry, RaceResult, RatingPeriod


@dataclass(frozen=True)
class ReplayResult:
    snapshots: pl.DataFrame
    final_state: dict[str, Rating]
    race_count: int
    period_count: int
    elapsed_seconds: float


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def _parse_date(value: Any) -> date:
    text = _norm(value)
    if not text:
        raise ValueError("[error] race_date가 비어 있습니다.")
    if len(text) == 8 and text.isdigit():
        parsed = parse_kst_date(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
        if parsed is not None:
            return parsed
    parsed = parse_kst_date(text)
    if parsed is None:
        raise ValueError(f"[error] race_date 파싱 실패: {text}")
    return parsed


def _coerce_weight(value: Any) -> float:
    if value is None:
        return 1.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1.0
    if parsed <= 0:
        return 1.0
    return parsed


def _to_race_results(race_ledger: pl.DataFrame) -> list[RaceResult]:
    rows = race_ledger.sort(["race_ordering_key", "rank", "athlete_id"], nulls_last=True).to_dicts()
    if not rows:
        return []
    races: list[RaceResult] = []
    cursor = 0
    while cursor < len(rows):
        race_key = _norm(rows[cursor].get("race_ordering_key"))
        chunk: list[dict[str, Any]] = []
        while cursor < len(rows) and _norm(rows[cursor].get("race_ordering_key")) == race_key:
            chunk.append(rows[cursor])
            cursor += 1
        if not chunk:
            continue
        first = chunk[0]
        race_id = _norm(first.get("race_id"))
        if not race_id:
            raise ValueError("[error] race_id가 비어 있습니다.")
        race_date = _parse_date(first.get("race_date"))
        meet_id = _norm(first.get("meet_id")) or "-"
        entries = tuple(
            RaceEntry(
                athlete_id=_norm(row.get("athlete_id")),
                rank=int(row.get("rank") or 0),
                status=_norm(row.get("status")),
                weight=_coerce_weight(row.get("weight")),
            )
            for row in chunk
            if _norm(row.get("athlete_id"))
        )
        if len(entries) < 2:
            continue
        races.append(RaceResult(race_id=race_id, race_date=race_date, meet_id=meet_id, entries=entries))
    return races


def _period_key(race: RaceResult, period: RatingPeriod) -> str:
    if period == "month":
        return f"{race.race_date.year:04d}-{race.race_date.month:02d}"
    return f"{race.race_date.isoformat()}|{race.meet_id}"


def _group_periods(races: list[RaceResult], period: RatingPeriod) -> list[tuple[date, list[RaceResult]]]:
    if not races:
        return []
    grouped: dict[str, list[RaceResult]] = {}
    valid_dates: dict[str, date] = {}
    for race in races:
        key = _period_key(race, period)
        if key not in grouped:
            grouped[key] = []
            valid_dates[key] = race.race_date
        grouped[key].append(race)
        if race.race_date > valid_dates[key]:
            valid_dates[key] = race.race_date
    return [(valid_dates[key], grouped[key]) for key in grouped.keys()]


def _snapshot_rows(state: dict[str, Rating], athlete_ids: set[str], valid_date: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for athlete_id in sorted(athlete_ids):
        rating = state.get(athlete_id)
        if rating is None:
            continue
        out.append(
            {
                "athlete_id": athlete_id,
                "valid_date": valid_date,
                "mu": float(rating.mu),
                "phi": float(rating.phi),
                "sigma": float(rating.sigma),
                "n_games": int(rating.n_games),
            }
        )
    return out


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])
    weight = pos - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _fmt_float(value: float) -> str:
    return f"{value:.4f}"


def _national_team_integrity_lines(final_state: dict[str, Rating], *, top_k: int) -> list[str]:
    salt = _norm(os.environ.get("SPLITS_ANON_SALT"))
    public_path = Path("data/public_figures.csv")
    if not salt:
        return ["- 국가대표 온전성 검사: `SPLITS_ANON_SALT` 미설정으로 생략"]
    if not public_path.exists():
        return ["- 국가대표 온전성 검사: `data/public_figures.csv`가 없어 생략"]

    rep_keys: list[str] = []
    with public_path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            status = _norm(row.get("상태"))
            reason = _norm(row.get("지정근거"))
            if status != "active":
                continue
            if "국가대표" not in reason:
                continue
            id_no = _norm(row.get("idNo"))
            if not id_no:
                continue
            rep_keys.append(hashlib.sha256(f"{id_no}{salt}".encode("utf-8")).hexdigest()[:12])
    if not rep_keys:
        return ["- 국가대표 온전성 검사: 조건에 맞는 공개 선수가 없어 생략"]

    ranked = sorted(final_state.items(), key=lambda item: float(item[1].mu), reverse=True)
    rank_index = {athlete_id: index + 1 for index, (athlete_id, _rating) in enumerate(ranked)}
    found = sorted(rank_index[key] for key in rep_keys if key in rank_index)
    if not found:
        return ["- 국가대표 온전성 검사: 공개 국가대표 키와 레이팅 키 매칭 0건"]
    inside = sum(1 for rank in found if rank <= top_k)
    head = ", ".join(str(rank) for rank in found[:10])
    return [
        f"- 국가대표 온전성 검사: 매칭 {len(found)}/{len(rep_keys)}명, 상위 {top_k}위 내 {inside}명",
        f"- 국가대표 매칭 순위(상위 10개): {head}",
    ]


def _build_report(
    *,
    engine_name: EngineName,
    rating_period: RatingPeriod,
    result: ReplayResult,
    top_k: int,
) -> str:
    final_ratings = list(result.final_state.values())
    mu_values = [float(item.mu) for item in final_ratings]
    phi_values = [float(item.phi) for item in final_ratings]
    game_values = [float(item.n_games) for item in final_ratings]
    phi_over_300 = sum(1 for value in phi_values if value > 300.0)
    phi_ratio = (phi_over_300 * 100.0 / float(len(phi_values))) if phi_values else 0.0

    lines = [
        "# R-04 Baseline Rating Report",
        "",
        f"- engine: `{engine_name}`",
        f"- rating_period: `{rating_period}`",
        f"- race_count: **{result.race_count:,}**",
        f"- period_count: **{result.period_count:,}**",
        f"- athlete_count: **{len(result.final_state):,}**",
        f"- snapshot_rows: **{result.snapshots.height:,}**",
        f"- elapsed_seconds: **{result.elapsed_seconds:.3f}**",
        "",
        "## 최종 상태 분포 요약",
        "",
        "| metric | min | p10 | p50 | p90 | max |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| mu | {_fmt_float(min(mu_values) if mu_values else 0.0)} | {_fmt_float(_percentile(mu_values, 0.10))} | {_fmt_float(_percentile(mu_values, 0.50))} | {_fmt_float(_percentile(mu_values, 0.90))} | {_fmt_float(max(mu_values) if mu_values else 0.0)} |",
        f"| phi | {_fmt_float(min(phi_values) if phi_values else 0.0)} | {_fmt_float(_percentile(phi_values, 0.10))} | {_fmt_float(_percentile(phi_values, 0.50))} | {_fmt_float(_percentile(phi_values, 0.90))} | {_fmt_float(max(phi_values) if phi_values else 0.0)} |",
        f"| n_games | {_fmt_float(min(game_values) if game_values else 0.0)} | {_fmt_float(_percentile(game_values, 0.10))} | {_fmt_float(_percentile(game_values, 0.50))} | {_fmt_float(_percentile(game_values, 0.90))} | {_fmt_float(max(game_values) if game_values else 0.0)} |",
        "",
        f"- phi > 300 선수 비율: **{phi_ratio:.2f}%** ({phi_over_300:,}/{len(phi_values):,})",
        "",
        "## 온전성 검사",
        "",
    ]
    lines.extend(_national_team_integrity_lines(result.final_state, top_k=top_k))
    lines.append("")
    return "\n".join(lines)


def run_replay(
    *,
    ledger_path: Path,
    output_path: Path,
    report_path: Path,
    engine_name: EngineName = "glicko2",
    rating_period: RatingPeriod = "meet",
    tau: float = 0.5,
    initial_mu: float = 1500.0,
    initial_phi: float = 350.0,
    initial_sigma: float = 0.06,
    max_iterations: int = 100,
    epsilon: float = 1e-6,
    pairwise_size_weight: bool = True,
    integrity_top_k: int = 200,
) -> ReplayResult:
    started = time.perf_counter()
    race_ledger = load_race_ledger(ledger_path)
    validate_ledger(race_ledger)
    races = _to_race_results(race_ledger)
    periods = _group_periods(races, rating_period)

    if engine_name == "glicko2":
        predictor = Glicko2Engine(
            params=Glicko2Params(
                tau=float(tau),
                initial_mu=float(initial_mu),
                initial_phi=float(initial_phi),
                initial_sigma=float(initial_sigma),
                rating_period=rating_period,
            ),
            epsilon=float(epsilon),
            max_iterations=int(max_iterations),
            pairwise_size_weight=pairwise_size_weight,
        )
    elif engine_name == "trueskill":
        from .trueskill_wrapper import TrueSkillEngine

        predictor = TrueSkillEngine()
    else:
        raise ValueError(f"[error] 지원하지 않는 엔진입니다: {engine_name}")

    state: dict[str, Rating] = {}
    snapshot_rows: list[dict[str, Any]] = []
    for period_date, period_races in periods:
        state = predictor.update(state, period_races)  # type: ignore[assignment]
        active_ids: set[str] = set()
        for race in period_races:
            for entry in race.entries:
                active_ids.add(entry.athlete_id)
        snapshot_rows.extend(_snapshot_rows(state, active_ids, period_date))

    snapshot_schema = {
        "athlete_id": pl.Utf8,
        "valid_date": pl.Date,
        "mu": pl.Float64,
        "phi": pl.Float64,
        "sigma": pl.Float64,
        "n_games": pl.Int64,
    }
    snapshots = pl.DataFrame(snapshot_rows, schema=snapshot_schema) if snapshot_rows else pl.DataFrame(schema=snapshot_schema)
    snapshots = snapshots.sort(["valid_date", "athlete_id"], nulls_last=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots.write_parquet(output_path)

    elapsed = time.perf_counter() - started
    result = ReplayResult(
        snapshots=snapshots,
        final_state=state,
        race_count=len(races),
        period_count=len(periods),
        elapsed_seconds=float(elapsed),
    )

    report_text = _build_report(
        engine_name=engine_name,
        rating_period=rating_period,
        result=result,
        top_k=int(integrity_top_k),
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-04 베이스라인 레이팅 리플레이 실행기")
    parser.add_argument("--ledger", default="out/ledger", help="race_ledger를 포함한 입력 경로")
    parser.add_argument("--out", default="out/ratings_baseline.parquet", help="스냅샷 parquet 출력 경로")
    parser.add_argument("--report", default="out/baseline_report.md", help="요약 리포트 출력 경로")
    parser.add_argument("--engine", default="glicko2", choices=["glicko2", "trueskill"], help="레이팅 엔진")
    parser.add_argument("--rating-period", default="meet", choices=["meet", "month"], help="period 단위")
    parser.add_argument("--tau", type=float, default=0.5, help="Glicko-2 tau")
    parser.add_argument("--initial-mu", type=float, default=1500.0, help="Glicko-2 초기 mu")
    parser.add_argument("--initial-phi", type=float, default=350.0, help="Glicko-2 초기 phi")
    parser.add_argument("--initial-sigma", type=float, default=0.06, help="Glicko-2 초기 sigma")
    parser.add_argument("--epsilon", type=float, default=1e-6, help="Glicko-2 volatility 수렴 임계값")
    parser.add_argument("--max-iterations", type=int, default=100, help="Glicko-2 volatility 최대 반복 횟수")
    parser.add_argument("--disable-size-weight", action="store_true", help="pairwise 1/(N-1) 보정을 비활성화")
    parser.add_argument("--integrity-top-k", type=int, default=200, help="국가대표 온전성 검사 상위권 기준")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = run_replay(
        ledger_path=Path(args.ledger).expanduser(),
        output_path=Path(args.out).expanduser(),
        report_path=Path(args.report).expanduser(),
        engine_name=args.engine,
        rating_period=args.rating_period,
        tau=float(args.tau),
        initial_mu=float(args.initial_mu),
        initial_phi=float(args.initial_phi),
        initial_sigma=float(args.initial_sigma),
        max_iterations=int(args.max_iterations),
        epsilon=float(args.epsilon),
        pairwise_size_weight=not bool(args.disable_size_weight),
        integrity_top_k=int(args.integrity_top_k),
    )
    print(f"[ok] engine={args.engine}")
    print(f"[ok] rating_period={args.rating_period}")
    print(f"[ok] races={result.race_count:,}")
    print(f"[ok] periods={result.period_count:,}")
    print(f"[ok] athletes={len(result.final_state):,}")
    print(f"[ok] snapshot_rows={result.snapshots.height:,}")
    print(f"[ok] out={args.out}")
    print(f"[ok] report={args.report}")


if __name__ == "__main__":
    main()
