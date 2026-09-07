from __future__ import annotations

import argparse
import csv
import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

import polars as pl

from rating.engine.runner import to_race_results
from rating.ledger.schema import load_race_ledger, validate_ledger

from .merge import IdentityMerge, replay_after_identity_merge
from .orchestrator import ReplayParams, replay


@dataclass(frozen=True)
class RaceHypergraph:
    races: dict[str, frozenset[str]]
    race_dates: dict[str, date]
    athlete_races: dict[str, tuple[str, ...]]

    @classmethod
    def from_ledger(cls, race_ledger: pl.DataFrame) -> RaceHypergraph:
        validate_ledger(race_ledger)
        races: dict[str, frozenset[str]] = {}
        race_dates: dict[str, date] = {}
        athlete_races: dict[str, list[str]] = defaultdict(list)
        for race in to_race_results(race_ledger):
            athlete_ids = frozenset(entry.athlete_id for entry in race.entries)
            if len(athlete_ids) < 2:
                continue
            races[race.race_id] = athlete_ids
            race_dates[race.race_id] = race.race_date
            for athlete_id in athlete_ids:
                athlete_races[athlete_id].append(race.race_id)
        return cls(
            races=races,
            race_dates=race_dates,
            athlete_races={athlete_id: tuple(sorted(race_ids)) for athlete_id, race_ids in athlete_races.items()},
        )

    def athletes_on_or_after(self, merge_at: date) -> set[str]:
        return {
            athlete_id
            for race_id, athlete_ids in self.races.items()
            if self.race_dates[race_id] >= merge_at
            for athlete_id in athlete_ids
        }


@dataclass(frozen=True)
class BlastRadiusSample:
    merge: IdentityMerge
    merge_at: date
    hops: tuple[frozenset[str], ...]
    population_size: int
    seed_count: int

    @property
    def cumulative_sizes(self) -> tuple[int, ...]:
        total = self.seed_count
        sizes = []
        for hop in self.hops:
            total += len(hop)
            sizes.append(total)
        return tuple(sizes)

    @property
    def hop_to_ninety_percent(self) -> int | None:
        threshold = self.population_size * 0.90
        for hop, size in enumerate(self.cumulative_sizes, start=1):
            if size >= threshold:
                return hop
        return None


def affected_athletes(merge_at: date, ids: tuple[str, str], graph: RaceHypergraph) -> Iterator[set[str]]:
    """Yield newly affected athletes by hop over race hyperedges after a merge event."""
    if ids[0] == ids[1] or not all(ids):
        raise ValueError("[error] 병합 ID는 서로 다른 비어 있지 않은 값이어야 합니다.")
    seen = set(ids)
    frontier = set(ids)
    while frontier:
        next_frontier: set[str] = set()
        for athlete_id in sorted(frontier):
            for race_id in graph.athlete_races.get(athlete_id, ()):
                if graph.race_dates[race_id] >= merge_at:
                    next_frontier.update(graph.races[race_id])
        next_frontier.difference_update(seen)
        if not next_frontier:
            return
        yield next_frontier
        seen.update(next_frontier)
        frontier = next_frontier


def sample_merges(graph: RaceHypergraph, sample_count: int) -> tuple[IdentityMerge, ...]:
    if sample_count < 1:
        raise ValueError("[error] 표본 수는 1 이상이어야 합니다.")
    first_seen: dict[str, date] = {}
    for race_id, athlete_ids in graph.races.items():
        race_date = graph.race_dates[race_id]
        for athlete_id in athlete_ids:
            first_seen[athlete_id] = min(first_seen.get(athlete_id, race_date), race_date)
    ordered = sorted(first_seen.items(), key=lambda item: (item[1], item[0]))
    if len(ordered) < 2:
        raise ValueError("[error] 병합 표본을 만들 선수 수가 부족합니다.")

    selected: list[IdentityMerge] = []

    def can_merge(primary_id: str, secondary_id: str) -> bool:
        return not set(graph.athlete_races[primary_id]).intersection(graph.athlete_races[secondary_id])

    for index in range(sample_count):
        position = round(index * (len(ordered) - 1) / max(1, sample_count - 1))
        secondary_id, merge_at = ordered[position]
        primary_candidates = [athlete_id for athlete_id, _ in ordered if athlete_id != secondary_id and can_merge(athlete_id, secondary_id)]
        if not primary_candidates:
            continue
        primary_id = min(
            primary_candidates,
            key=lambda athlete_id: (
                abs((first_seen[athlete_id] - merge_at).days),
                hashlib.sha256(f"{secondary_id}|{athlete_id}".encode("utf-8")).hexdigest(),
            ),
        )
        merge = IdentityMerge(primary_id=primary_id, secondary_id=secondary_id)
        if merge not in selected:
            selected.append(merge)
    if len(selected) < sample_count:
        for secondary_id, merge_at in ordered:
            for primary_id, first_at in ordered:
                if primary_id == secondary_id or not can_merge(primary_id, secondary_id):
                    continue
                merge = IdentityMerge(primary_id=primary_id, secondary_id=secondary_id)
                if merge not in selected:
                    selected.append(merge)
                if len(selected) == sample_count:
                    break
            if len(selected) == sample_count:
                break
    if len(selected) < sample_count:
        raise ValueError("[error] 요청한 수만큼 서로 다른 병합 표본을 만들 수 없습니다.")
    return tuple(selected)


def load_confirmed_merges(path: Path, graph: RaceHypergraph) -> tuple[IdentityMerge, ...]:
    if not path.exists():
        return ()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return ()
    merges = []
    for row in rows:
        primary_id = (row.get("주idNo") or row.get("primary_id") or "").strip()
        secondary_id = (row.get("부idNo") or row.get("secondary_id") or "").strip()
        if not primary_id or not secondary_id or primary_id == secondary_id:
            continue
        if primary_id not in graph.athlete_races or secondary_id not in graph.athlete_races:
            continue
        merge = IdentityMerge(primary_id=primary_id, secondary_id=secondary_id)
        if merge not in merges:
            merges.append(merge)
    if not merges:
        raise ValueError(f"[error] 확정 병합 이력의 ID를 race ledger에서 찾을 수 없습니다: {path}")
    return tuple(merges)


def measure(graph: RaceHypergraph, merges: tuple[IdentityMerge, ...]) -> tuple[BlastRadiusSample, ...]:
    samples = []
    for merge in merges:
        first_dates = [
            graph.race_dates[race_id]
            for athlete_id in (merge.primary_id, merge.secondary_id)
            for race_id in graph.athlete_races.get(athlete_id, ())
        ]
        if not first_dates:
            raise ValueError(f"[error] 병합 대상 선수를 그래프에서 찾을 수 없습니다: {merge.secondary_id}")
        merge_at = min(first_dates)
        hops = tuple(frozenset(hop) for hop in affected_athletes(merge_at, (merge.primary_id, merge.secondary_id), graph))
        samples.append(
            BlastRadiusSample(
                merge=merge,
                merge_at=merge_at,
                hops=hops,
                population_size=len(graph.athletes_on_or_after(merge_at)),
                seed_count=len({merge.primary_id, merge.secondary_id}.intersection(graph.athletes_on_or_after(merge_at))),
            )
        )
    return tuple(samples)


def render_report(
    samples: tuple[BlastRadiusSample, ...],
    replay_seconds: tuple[float, ...] | None = None,
    *,
    used_confirmed_history: bool = False,
) -> str:
    reaches_quickly = all(sample.hop_to_ninety_percent is not None and sample.hop_to_ninety_percent <= 3 for sample in samples)
    lines = [
        "# 동일인 병합 무효화 반경 측정",
        "",
        "## 결론",
        "",
        (
            "모든 표본이 3 hop 안에 기준 시점 이후 선수의 90%에 도달했습니다. "
            "그래프 기반 부분 리플레이는 만들지 않고 시간 기반 절단만 사용합니다."
            if reaches_quickly
            else "3 hop 안에 기준 시점 이후 선수의 90%에 도달하지 못한 표본이 확인됐습니다. 영향 race만 재생하는 부분 리플레이를 사용합니다."
        ),
        "",
        "## 측정 방법과 한계",
        "",
        "- hop은 pairwise edge가 아니라 같은 race의 모든 공동 참가자를 한 번에 잇는 하이퍼엣지 단위입니다. 누적 영향 수에는 병합 대상도 포함합니다.",
        (
            "- 확정 병합 이력을 우선 사용했고, 부족한 표본은 ID 최초 등장 시점을 층화한 결정적 합성 쌍으로 보완했습니다."
            if used_confirmed_history
            else "- 확정 병합 이력이 비어 있어, ID 최초 등장 시점을 과거·시즌 초·중·말·최근으로 층화한 결정적 합성 쌍을 사용했습니다."
        ),
        "- 실제 확정 병합이 생기면 그 쌍으로 같은 측정을 다시 실행해야 합니다.",
        (
            "- 모든 표본의 부분 리플레이가 2초 이내여서 대화형 미리보기를 동기로 제공합니다."
            if replay_seconds is not None and all(value <= 2.0 for value in replay_seconds)
            else "- 일부 부분 리플레이가 2초를 초과해, 병합 미리보기는 비동기 작업으로 제공합니다."
            if replay_seconds is not None
            else "- 시간 측정을 생략했으므로 병합 미리보기의 동기 제공 여부를 판단할 수 없습니다."
        ),
        "",
        "## 표본별 90% 도달",
        "",
        "| 표본 | 병합 기준일 | 기준 선수 수 | 90% 도달 hop | 부분 리플레이 시간 |",
        "| ---: | --- | ---: | ---: | ---: |",
    ]
    for index, sample in enumerate(samples, start=1):
        reach_hop = str(sample.hop_to_ninety_percent) if sample.hop_to_ninety_percent is not None else "미도달"
        elapsed = f"{replay_seconds[index - 1]:.3f}초" if replay_seconds is not None else "미측정"
        lines.append(f"| {index} | {sample.merge_at.isoformat()} | {sample.population_size:,} | {reach_hop} | {elapsed} |")
    lines.extend(["", "## Hop별 영향 비율 곡선", "", "| 표본 | hop | 새 영향 선수 | 누적 영향 선수 | 누적 비율 |", "| ---: | ---: | ---: | ---: | ---: |"])
    for index, sample in enumerate(samples, start=1):
        for hop_number, (newly_affected, cumulative) in enumerate(zip(sample.hops, sample.cumulative_sizes), start=1):
            ratio = cumulative / sample.population_size if sample.population_size else 0.0
            lines.append(f"| {index} | {hop_number} | {len(newly_affected):,} | {cumulative:,} | {ratio:.1%} |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="동일인 병합의 race 단위 영향 반경을 측정합니다")
    parser.add_argument("--ledger", default="out/ledger", help="race_ledger를 포함한 입력 경로")
    parser.add_argument("--sample-merges", type=int, default=5, help="측정할 결정적 합성 병합 표본 수")
    parser.add_argument("--merge-history", default="data/id_merges.csv", help="확정 병합 이력 CSV 경로")
    parser.add_argument("--out", default="out/blast_radius.md", help="Markdown 측정 보고서 경로")
    parser.add_argument("--skip-replay-timing", action="store_true", help="시간 절단 리플레이 시간을 측정하지 않습니다")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ledger_path = Path(args.ledger).expanduser()
    race_ledger = load_race_ledger(ledger_path)
    graph = RaceHypergraph.from_ledger(race_ledger)
    confirmed = load_confirmed_merges(Path(args.merge_history).expanduser(), graph)
    selected_merges = list(confirmed[: args.sample_merges])
    if len(selected_merges) < args.sample_merges:
        for merge in sample_merges(graph, args.sample_merges + len(selected_merges)):
            if merge not in selected_merges:
                selected_merges.append(merge)
            if len(selected_merges) == args.sample_merges:
                break
    if len(selected_merges) < args.sample_merges:
        raise ValueError("[error] 요청한 수만큼 병합 표본을 만들 수 없습니다.")
    merges = tuple(selected_merges)
    samples = measure(graph, merges)
    replay_seconds: tuple[float, ...] | None = None
    if not args.skip_replay_timing:
        params = ReplayParams()
        checkpoint_root = Path(args.out).expanduser().parent / "blast_radius_checkpoints"
        baseline = replay(ledger_path, params, checkpoint_root=checkpoint_root)
        elapsed = []
        for merge in merges:
            started = time.perf_counter()
            replay_after_identity_merge(
                ledger_path,
                merge,
                params,
                checkpoint_root=checkpoint_root,
                baseline_final_state=baseline.final_state,
            )
            elapsed.append(time.perf_counter() - started)
        replay_seconds = tuple(elapsed)
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(samples, replay_seconds, used_confirmed_history=bool(confirmed)), encoding="utf-8")
    print(f"[ok] report={out_path}")


if __name__ == "__main__":
    main()
