from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, Sequence

RatingPeriod = Literal["meet", "month"]
EngineName = Literal["glicko2", "trueskill"]


@dataclass(frozen=True)
class RaceEntry:
    athlete_id: str
    rank: int
    status: str
    weight: float = 1.0


@dataclass(frozen=True)
class RaceResult:
    race_id: str
    race_date: date
    meet_id: str
    entries: tuple[RaceEntry, ...]


@dataclass(frozen=True)
class Comparison:
    winner_id: str
    loser_id: str
    race_date: date
    outcome: float = 1.0
    weight: float = 1.0


class RatingLike(Protocol):
    mu: float
    phi: float
    sigma: float
    last_active: date | None
    n_games: int


class Predictor(Protocol):
    def predict_prob(self, a: str, b: str, as_of: date) -> float: ...

    def update(self, state: dict[str, RatingLike], race_results: Sequence[RaceResult]) -> dict[str, RatingLike]: ...


def build_pairwise_comparisons(
    race_results: Sequence[RaceResult],
    *,
    apply_size_weight: bool = True,
) -> list[Comparison]:
    comparisons: list[Comparison] = []
    for race in race_results:
        entries = sorted(race.entries, key=lambda item: (int(item.rank), item.athlete_id))
        if len(entries) < 2:
            continue
        size_weight = 1.0 / float(len(entries) - 1) if apply_size_weight else 1.0
        for left_index in range(len(entries)):
            winner = entries[left_index]
            if winner.rank <= 0:
                continue
            for right_index in range(left_index + 1, len(entries)):
                loser = entries[right_index]
                if loser.rank <= 0 or winner.rank == loser.rank:
                    continue
                base_weight = max(float(winner.weight), 0.0)
                if loser.weight > 0:
                    base_weight = (base_weight + float(loser.weight)) / 2.0
                if base_weight <= 0:
                    base_weight = 1.0
                comparisons.append(
                    Comparison(
                        winner_id=winner.athlete_id,
                        loser_id=loser.athlete_id,
                        race_date=race.race_date,
                        outcome=1.0,
                        weight=float(base_weight * size_weight),
                    )
                )
    comparisons.sort(key=lambda item: (item.race_date.isoformat(), item.winner_id, item.loser_id))
    return comparisons

