from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Callable, Sequence

from .glicko2 import Rating
from .types import Predictor, RaceEntry, RaceResult, RatingLike, RatingPeriod, elapsed_periods

try:
    import trueskill as _trueskill
except ImportError:
    _trueskill = None


@dataclass(frozen=True)
class TrueSkillParams:
    initial_mu: float = 25.0
    initial_sigma: float = 25.0 / 3.0
    beta: float = 25.0 / 6.0
    tau: float = 25.0 / 300.0
    draw_probability: float = 0.0
    rating_period: RatingPeriod = "meet"


class TrueSkillEngine(Predictor):
    def __init__(
        self,
        params: TrueSkillParams | None = None,
        *,
        prior_provider: Callable[[str], tuple[float, float] | None] | None = None,
    ) -> None:
        if _trueskill is None:
            raise RuntimeError("[error] trueskill 패키지가 필요합니다. `pip install -r requirements.txt`를 먼저 실행하세요.")
        self.params = params or TrueSkillParams()
        self._prior_provider = prior_provider
        self._env = _trueskill.TrueSkill(
            mu=self.params.initial_mu,
            sigma=self.params.initial_sigma,
            beta=self.params.beta,
            tau=self.params.tau,
            draw_probability=self.params.draw_probability,
        )
        self._state: dict[str, Rating] = {}

    def predict_prob(self, a: str, b: str, as_of: date) -> float:
        left = self._to_trueskill_rating(self.effective_rating(a, as_of))
        right = self._to_trueskill_rating(self.effective_rating(b, as_of))
        denominator = math.sqrt((2.0 * self.params.beta * self.params.beta) + (left.sigma * left.sigma) + (right.sigma * right.sigma))
        if denominator <= 0.0:
            return 0.5
        return float(self._env.cdf((left.mu - right.mu) / denominator))

    def effective_rating(self, athlete_id: str, as_of: date) -> Rating:
        current = self._state.get(athlete_id, self._initial_rating(athlete_id))
        return self._effective_with_inactivity(current, as_of)

    def update(self, state: dict[str, RatingLike], race_results: Sequence[RaceResult]) -> dict[str, Rating]:
        updated: dict[str, Rating] = {athlete_id: self._coerce_rating(rating) for athlete_id, rating in state.items()}
        for race in race_results:
            if len(race.entries) < 2:
                continue
            grouped_entries, ranks = self._group_by_rank(race.entries)
            # 전원이 동착이면 순위 그룹이 하나뿐이라 승패 정보가 없습니다.
            # Glicko-2도 동순위 쌍에서는 비교를 만들지 않으므로 동일하게 건너뜁니다.
            if len(grouped_entries) < 2:
                continue
            rating_groups: list[tuple[object, ...]] = []
            for group in grouped_entries:
                rating_groups.append(
                    tuple(
                        self._to_trueskill_rating(
                            self._effective_with_inactivity(
                                updated.get(entry.athlete_id, self._initial_rating(entry.athlete_id)),
                                race.race_date,
                            )
                        )
                        for entry in group
                    )
                )
            rated_groups = self._env.rate(rating_groups=rating_groups, ranks=ranks)
            for group_entries, group_ratings in zip(grouped_entries, rated_groups):
                for entry, rated in zip(group_entries, group_ratings):
                    current = updated.get(entry.athlete_id, self._initial_rating(entry.athlete_id))
                    updated[entry.athlete_id] = Rating(
                        mu=float(rated.mu),
                        phi=float(rated.sigma),
                        sigma=0.0,
                        last_active=race.race_date,
                        n_games=int(current.n_games + 1),
                    )
        self._state = updated
        return updated

    def _group_by_rank(self, entries: tuple[RaceEntry, ...]) -> tuple[list[list[RaceEntry]], list[int]]:
        ordered = sorted(entries, key=lambda item: (int(item.rank), item.athlete_id))
        groups: list[list[RaceEntry]] = []
        ranks: list[int] = []
        for entry in ordered:
            if entry.rank <= 0:
                continue
            if not groups or ranks[-1] != entry.rank:
                groups.append([entry])
                ranks.append(entry.rank)
                continue
            groups[-1].append(entry)
        return groups, ranks

    def _coerce_rating(self, rating: RatingLike) -> Rating:
        if isinstance(rating, Rating):
            return rating
        return Rating(
            mu=float(rating.mu),
            phi=float(rating.phi),
            sigma=float(rating.sigma),
            last_active=rating.last_active,
            n_games=int(rating.n_games),
        )

    def _to_trueskill_rating(self, rating: Rating):
        sigma = float(rating.phi if rating.phi > 0 else self.params.initial_sigma)
        return self._env.create_rating(mu=float(rating.mu), sigma=sigma)

    def _effective_with_inactivity(self, rating: Rating, as_of: date) -> Rating:
        periods = elapsed_periods(rating.last_active, as_of, self.params.rating_period)
        if periods <= 0:
            return rating
        inflated_sigma = self._inflate_sigma(rating.phi, periods)
        return Rating(
            mu=float(rating.mu),
            phi=float(inflated_sigma),
            sigma=float(rating.sigma),
            last_active=rating.last_active,
            n_games=int(rating.n_games),
        )

    def _inflate_sigma(self, sigma: float, periods: int) -> float:
        if periods <= 0:
            return float(sigma)
        inflated = math.sqrt((float(sigma) * float(sigma)) + (float(self.params.tau) * float(self.params.tau) * float(periods)))
        return float(min(inflated, self.params.initial_sigma))

    def _initial_rating(self, athlete_id: str | None = None) -> Rating:
        initial_mu = float(self.params.initial_mu)
        initial_sigma = float(self.params.initial_sigma)
        if athlete_id and self._prior_provider is not None:
            prior = self._prior_provider(athlete_id)
            if prior is not None:
                prior_mu, prior_sigma = prior
                if math.isfinite(prior_mu):
                    initial_mu = float(prior_mu)
                if math.isfinite(prior_sigma) and prior_sigma > 0:
                    initial_sigma = float(prior_sigma)
        return Rating(
            mu=initial_mu,
            phi=initial_sigma,
            sigma=0.0,
            last_active=None,
            n_games=0,
        )
