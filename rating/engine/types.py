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

    def effective_rating(self, athlete_id: str, as_of: date) -> RatingLike:
        """`as_of` 시점 예측에 실제로 쓰이는 레이팅.

        저장된 레이팅과 다를 수 있습니다. 비활동 기간만큼 불확실성을 되돌리는
        엔진은 그 보정을 반영한 값을 돌려줍니다. 진단 지표가 예측과 다른 값을
        보고 있으면 진단 자체를 믿을 수 없으므로 이 경로를 통해 읽습니다.
        """
        ...


def elapsed_periods(last_active: date | None, current_date: date, rating_period: RatingPeriod) -> int:
    """마지막 출전 이후 흐른 rating period 수.

    두 엔진이 같은 규약을 쓰지 않으면 비활동 보정 크기를 비교할 수 없어서
    한 곳에 둡니다. `meet`은 같은 달 안이라도 최소 1주기가 지난 것으로 봅니다.
    """
    if last_active is None:
        return 0
    if current_date <= last_active:
        return 0
    month_diff = (current_date.year - last_active.year) * 12 + (current_date.month - last_active.month)
    if rating_period == "month":
        return max(0, month_diff)
    if month_diff <= 0:
        return 1
    return max(1, month_diff)


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

