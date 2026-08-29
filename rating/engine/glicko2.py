from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Callable, Literal, Sequence

from .types import Comparison, Predictor, RaceResult, RatingLike, build_pairwise_comparisons, elapsed_periods

_GLICKO2_SCALE = 400.0 / math.log(10.0)


@dataclass(frozen=True)
class Rating:
    mu: float
    phi: float
    sigma: float
    last_active: date | None
    n_games: int


@dataclass(frozen=True)
class Glicko2Params:
    tau: float = 0.5
    initial_mu: float = 1500.0
    initial_phi: float = 350.0
    initial_sigma: float = 0.06
    rating_period: Literal["meet", "month"] = "meet"


class Glicko2Engine(Predictor):
    def __init__(
        self,
        params: Glicko2Params | None = None,
        *,
        epsilon: float = 1e-6,
        max_iterations: int = 100,
        pairwise_size_weight: bool = True,
        prior_provider: Callable[[str], tuple[float, float] | None] | None = None,
    ) -> None:
        self.params = params or Glicko2Params()
        self.epsilon = float(epsilon)
        self.max_iterations = int(max_iterations)
        self.pairwise_size_weight = bool(pairwise_size_weight)
        self._prior_provider = prior_provider
        self._state: dict[str, Rating] = {}

    def predict_prob(self, a: str, b: str, as_of: date) -> float:
        left = self.effective_rating(a, as_of)
        right = self.effective_rating(b, as_of)
        left_mu, _ = self._to_internal(left.mu, left.phi)
        right_mu, right_phi = self._to_internal(right.mu, right.phi)
        g = self._g(right_phi)
        expected = 1.0 / (1.0 + math.exp(-g * (left_mu - right_mu)))
        return min(max(expected, 0.0), 1.0)

    def effective_rating(self, athlete_id: str, as_of: date) -> Rating:
        return self._decay_without_games(self._state.get(athlete_id, self._initial_rating(athlete_id)), as_of)

    def update(self, state: dict[str, RatingLike], race_results: Sequence[RaceResult]) -> dict[str, Rating]:
        typed_state = {athlete_id: self._coerce_rating(rating) for athlete_id, rating in state.items()}
        if not race_results:
            self._state = typed_state
            return typed_state
        comparisons = build_pairwise_comparisons(race_results, apply_size_weight=self.pairwise_size_weight)
        if not comparisons:
            self._state = typed_state
            return typed_state
        updated = self.process_period(typed_state, comparisons)
        self._state = updated
        return updated

    def process_period(self, state: dict[str, Rating], comps: list[Comparison]) -> dict[str, Rating]:
        if not comps:
            return dict(state)
        period_date = max(comp.race_date for comp in comps)
        opponent_map: dict[str, list[tuple[str, float, float]]] = {}
        for comp in comps:
            if comp.winner_id == comp.loser_id:
                continue
            weight = float(comp.weight)
            if weight <= 0:
                continue
            opponent_map.setdefault(comp.winner_id, []).append((comp.loser_id, float(comp.outcome), weight))
            opponent_map.setdefault(comp.loser_id, []).append((comp.winner_id, 1.0 - float(comp.outcome), weight))
        if not opponent_map:
            return dict(state)

        previous_state = dict(state)
        period_state: dict[str, Rating] = {
            athlete_id: self._period_rating(previous_state.get(athlete_id, self._initial_rating(athlete_id)), period_date)
            for athlete_id in opponent_map
        }

        updated_state = dict(previous_state)
        for athlete_id in sorted(opponent_map.keys()):
            current = period_state[athlete_id]
            outcomes = opponent_map[athlete_id]
            if not outcomes:
                continue
            mu, phi = self._to_internal(current.mu, current.phi)
            variance_inv = 0.0
            delta_sum = 0.0
            for opponent_id, score, weight in outcomes:
                opponent = period_state.get(
                    opponent_id,
                    self._period_rating(previous_state.get(opponent_id, self._initial_rating(opponent_id)), period_date),
                )
                opp_mu, opp_phi = self._to_internal(opponent.mu, opponent.phi)
                g = self._g(opp_phi)
                expected = 1.0 / (1.0 + math.exp(-g * (mu - opp_mu)))
                variance_inv += weight * (g * g) * expected * (1.0 - expected)
                delta_sum += weight * g * (score - expected)
            if variance_inv <= 0.0:
                raise ValueError(f"[error] variance 계산이 0 이하입니다: athlete_id={athlete_id}")
            variance = 1.0 / variance_inv
            delta = variance * delta_sum
            sigma_prime = self._solve_volatility(phi, current.sigma, delta, variance)
            phi_star = math.sqrt((phi * phi) + (sigma_prime * sigma_prime))
            phi_prime = 1.0 / math.sqrt((1.0 / (phi_star * phi_star)) + (1.0 / variance))
            mu_prime = mu + (phi_prime * phi_prime) * delta_sum
            next_mu, next_phi = self._to_external(mu_prime, phi_prime)
            updated_state[athlete_id] = Rating(
                mu=float(next_mu),
                phi=float(min(next_phi, self.params.initial_phi)),
                sigma=float(sigma_prime),
                last_active=period_date,
                n_games=int(current.n_games + len(outcomes)),
            )
        return updated_state

    def _period_rating(self, rating: Rating, period_date: date) -> Rating:
        elapsed_periods = self._elapsed_periods(rating.last_active, period_date)
        inactive_periods = max(0, elapsed_periods - 1)
        if inactive_periods <= 0:
            return rating
        inflated_phi = self._inflate_phi(rating.phi, rating.sigma, inactive_periods)
        return Rating(
            mu=float(rating.mu),
            phi=float(inflated_phi),
            sigma=float(rating.sigma),
            last_active=rating.last_active,
            n_games=int(rating.n_games),
        )

    def _decay_without_games(self, rating: Rating, as_of: date) -> Rating:
        elapsed_periods = self._elapsed_periods(rating.last_active, as_of)
        if elapsed_periods <= 0:
            return rating
        inflated_phi = self._inflate_phi(rating.phi, rating.sigma, elapsed_periods)
        return Rating(
            mu=float(rating.mu),
            phi=float(inflated_phi),
            sigma=float(rating.sigma),
            last_active=rating.last_active,
            n_games=int(rating.n_games),
        )

    def _elapsed_periods(self, last_active: date | None, current_date: date) -> int:
        return elapsed_periods(last_active, current_date, self.params.rating_period)

    def _inflate_phi(self, phi: float, sigma: float, periods: int) -> float:
        if periods <= 0:
            return float(phi)
        inflated = math.sqrt((float(phi) * float(phi)) + (float(sigma) * float(sigma) * float(periods)))
        return float(min(inflated, self.params.initial_phi))

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

    def _initial_rating(self, athlete_id: str | None = None) -> Rating:
        initial_mu = float(self.params.initial_mu)
        initial_phi = float(self.params.initial_phi)
        if athlete_id and self._prior_provider is not None:
            prior = self._prior_provider(athlete_id)
            if prior is not None:
                prior_mu, prior_phi = prior
                if math.isfinite(prior_mu):
                    initial_mu = float(prior_mu)
                if math.isfinite(prior_phi) and prior_phi > 0:
                    initial_phi = float(prior_phi)
        return Rating(
            mu=initial_mu,
            phi=initial_phi,
            sigma=float(self.params.initial_sigma),
            last_active=None,
            n_games=0,
        )

    def _to_internal(self, rating: float, deviation: float) -> tuple[float, float]:
        return ((float(rating) - self.params.initial_mu) / _GLICKO2_SCALE, float(deviation) / _GLICKO2_SCALE)

    def _to_external(self, mu: float, phi: float) -> tuple[float, float]:
        return (self.params.initial_mu + (_GLICKO2_SCALE * float(mu)), _GLICKO2_SCALE * float(phi))

    def _g(self, phi: float) -> float:
        return 1.0 / math.sqrt(1.0 + (3.0 * phi * phi) / (math.pi * math.pi))

    def _volatility_f(self, x: float, *, delta: float, phi: float, variance: float, a: float) -> float:
        exp_x = math.exp(x)
        num = exp_x * ((delta * delta) - (phi * phi) - variance - exp_x)
        den = 2.0 * ((phi * phi) + variance + exp_x) * ((phi * phi) + variance + exp_x)
        return (num / den) - ((x - a) / (self.params.tau * self.params.tau))

    def _solve_volatility(self, phi: float, sigma: float, delta: float, variance: float) -> float:
        if sigma <= 0:
            raise ValueError("[error] sigma는 양수여야 합니다.")
        a = math.log(sigma * sigma)
        if (delta * delta) > (phi * phi + variance):
            b = math.log((delta * delta) - (phi * phi) - variance)
        else:
            k = 1
            b = a - (k * self.params.tau)
            while self._volatility_f(b, delta=delta, phi=phi, variance=variance, a=a) < 0.0:
                k += 1
                b = a - (k * self.params.tau)
                if k > self.max_iterations:
                    raise RuntimeError("[error] volatility 반복 초기화가 수렴하지 않았습니다.")
        a_curr = a
        b_curr = b
        f_a = self._volatility_f(a_curr, delta=delta, phi=phi, variance=variance, a=a)
        f_b = self._volatility_f(b_curr, delta=delta, phi=phi, variance=variance, a=a)
        iterations = 0
        while abs(b_curr - a_curr) > self.epsilon:
            iterations += 1
            if iterations > self.max_iterations:
                raise RuntimeError("[error] volatility 반복이 최대 횟수를 초과했습니다.")
            denom = f_b - f_a
            if denom == 0:
                raise RuntimeError("[error] volatility 반복에서 분모가 0입니다.")
            c = a_curr + ((a_curr - b_curr) * f_a / denom)
            f_c = self._volatility_f(c, delta=delta, phi=phi, variance=variance, a=a)
            if f_c * f_b <= 0:
                a_curr = b_curr
                f_a = f_b
            else:
                f_a = f_a / 2.0
            previous_b = b_curr
            b_curr = c
            f_b = f_c
            # Illinois는 B가 해에 도달한 뒤에도 부호가 바뀌지 않으면 A가 따라오지
            # 못해, 괄호 폭이 epsilon 바로 위에서 멈춘 채 무한 반복합니다. 반복점이
            # 더 이상 움직이지 않으면 수렴한 것이므로 B를 답으로 씁니다.
            if abs(b_curr - previous_b) <= self.epsilon:
                return math.exp(b_curr / 2.0)
        return math.exp(a_curr / 2.0)
