from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

STATUS_FIN = "FIN"
STATUS_PEN = "PEN"
STATUS_DNF = "DNF"
STATUS_ADV = "ADV"


@dataclass(frozen=True)
class RaceParticipant:
    athlete_id: str
    rank: int
    status: str
    time_sec: float | None
    weight: float = 1.0


@dataclass(frozen=True)
class RaceObservation:
    race_id: str
    race_date: date
    meet_id: str
    season_year: int
    event: str
    round_class: str
    grade_text: str
    gender: str
    participants: tuple[RaceParticipant, ...]


@dataclass(frozen=True)
class ComparisonOutcome:
    race: RaceObservation
    winner: RaceParticipant
    loser: RaceParticipant
    source_status: str


@dataclass(frozen=True)
class PairwiseExample:
    comparison_id: int
    race_id: str
    race_date: date
    meet_id: str
    season_year: int
    event: str
    round_class: str
    grade_text: str
    gender: str
    winner_id: str
    loser_id: str
    winner_rank: int
    loser_rank: int
    winner_status: str
    loser_status: str
    winner_time_sec: float | None
    loser_time_sec: float | None
    source_status: str

    @property
    def _flipped(self) -> bool:
        """비교의 방향을 결정하는 결과 무관 난수 비트.

        선수 ID 사전순으로 방향을 잡으면 ID가 출생연도를 담고 있어 라벨이
        0.627로 쏠립니다(나이가 많을수록 대체로 강함). 결과와 무관하되 실력과도
        무관한 기준이 필요하므로, 정렬된 쌍과 race_id의 해시로 방향을 정합니다.
        결정적이라 재실행해도 같은 방향이 나옵니다.
        """
        low, high = sorted((self.winner_id, self.loser_id))
        seed = f"{self.race_id}|{low}|{high}".encode("utf-8")
        return hashlib.blake2b(seed, digest_size=8).digest()[0] & 1 == 1

    @property
    def left_id(self) -> str:
        """승패와 무관한 기준으로 고정한 비교의 왼쪽 선수."""
        low, high = sorted((self.winner_id, self.loser_id))
        return high if self._flipped else low

    @property
    def right_id(self) -> str:
        low, high = sorted((self.winner_id, self.loser_id))
        return low if self._flipped else high

    @property
    def label(self) -> int:
        """left가 실제로 이겼으면 1, 아니면 0.

        (승자, 패자) 순서로만 예제를 만들면 라벨이 전부 1이 되어 캘리브레이션을
        잴 수 없습니다. 방향을 결과와 무관하게 고정하면 라벨이 0/1로 갈리고,
        log loss / accuracy / Brier는 변환에 대해 불변인 채 ECE만 실제 값이 됩니다.
        """
        return 1 if self.left_id == self.winner_id else 0

    def orient(self, winner_probability: float) -> float:
        """P(winner > loser)를 P(left > right)로 돌려놓습니다."""
        return float(winner_probability) if self.label == 1 else 1.0 - float(winner_probability)

    def orient_delta(self, winner_delta: float) -> float:
        """승자 기준 격차를 left 기준으로 돌려놓습니다.

        `sigmoid(-x) == 1 - sigmoid(x)`이므로 부호만 뒤집으면 `orient`와 같은
        방향 변환이 됩니다. 로그 손실은 이 변환에 대해 불변이므로 적합 결과
        자체는 어느 좌표계에서 재든 같습니다. 그럼에도 이 좌표계를 쓰는 이유는
        적합에 쓰는 (delta, label) 쌍이 실제로 채점되는 (probability, actual)
        쌍과 같은 프레임에 있어야 하기 때문입니다.
        """
        return float(winner_delta) if self.label == 1 else -float(winner_delta)


@dataclass(frozen=True)
class BaselinePrediction:
    probability: float
    covered: bool


class BaselinePredictor(Protocol):
    name: str

    def predict(self, example: PairwiseExample) -> BaselinePrediction: ...

    def update(self, races: Sequence[RaceObservation]) -> None: ...


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp_term = math.exp(-value)
        return 1.0 / (1.0 + exp_term)
    exp_term = math.exp(value)
    return exp_term / (1.0 + exp_term)


def _clamp_probability(value: float) -> float:
    return min(max(float(value), 1e-6), 1.0 - 1e-6)


def fit_logistic_scale(
    deltas: Sequence[float],
    labels: Sequence[int],
    *,
    lo: float = 0.01,
    hi: float = 20.0,
    grid_points: int = 60,
) -> float:
    """`P = sigmoid(delta / scale)`의 scale을 log loss 최소화로 적합합니다.

    베이스라인은 이기고 싶은 대상이 아니라 넘어야 하는 기준이므로, 스케일을
    임의의 상수로 두면 안 됩니다. 상수가 너무 작으면 확률이 0/1로 포화해
    동전 던지기보다 나쁜 기준선이 만들어집니다.

    scale이 커질수록 예측은 0.5로 수렴하므로, 적합이 정상 동작하면 결과는
    구조적으로 `ln 2` 이하입니다.

    반드시 홀드아웃 **이전** 구간의 (delta, label)로만 호출해야 합니다.
    """
    if len(deltas) != len(labels):
        raise ValueError("[error] deltas/labels 길이가 일치하지 않습니다.")
    if not deltas:
        return float(hi)

    def loss(scale: float) -> float:
        total = 0.0
        for delta, label in zip(deltas, labels):
            probability = _clamp_probability(_sigmoid(float(delta) / scale))
            total -= math.log(probability) if label == 1 else math.log(1.0 - probability)
        return total / float(len(labels))

    ratio = (hi / lo) ** (1.0 / float(grid_points - 1))
    grid = [lo * (ratio**index) for index in range(grid_points)]
    best = min(grid, key=loss)

    # 최적 격자 칸 안쪽을 한 번 더 조입니다(1차원, 사실상 볼록).
    low = max(best / ratio, lo)
    high = min(best * ratio, hi)
    for _ in range(40):
        if high - low < 1e-6:
            break
        left = low + (high - low) / 3.0
        right = high - (high - low) / 3.0
        if loss(left) <= loss(right):
            high = right
        else:
            low = left
    return float((low + high) / 2.0)


def build_pairwise_outcomes(race: RaceObservation) -> list[ComparisonOutcome]:
    ranked = sorted(
        (
            participant
            for participant in race.participants
            if participant.rank > 0 and participant.status in {STATUS_FIN, STATUS_ADV, STATUS_PEN}
        ),
        key=lambda item: (item.rank, item.athlete_id),
    )
    finishers = [participant for participant in ranked if participant.status in {STATUS_FIN, STATUS_ADV}]
    dnfs = sorted(
        (participant for participant in race.participants if participant.status == STATUS_DNF),
        key=lambda item: (item.rank, item.athlete_id),
    )

    outcomes: list[ComparisonOutcome] = []
    for left in range(len(ranked)):
        winner = ranked[left]
        for right in range(left + 1, len(ranked)):
            loser = ranked[right]
            if winner.rank == loser.rank:
                continue
            outcomes.append(
                ComparisonOutcome(
                    race=race,
                    winner=winner,
                    loser=loser,
                    source_status=f"{winner.status}-{loser.status}",
                )
            )

    for loser in dnfs:
        for winner in finishers:
            outcomes.append(
                ComparisonOutcome(
                    race=race,
                    winner=winner,
                    loser=loser,
                    source_status=f"{winner.status}-{loser.status}",
                )
            )
    return outcomes


def build_pairwise_examples(races: Sequence[RaceObservation], *, start_id: int = 0) -> list[PairwiseExample]:
    rows: list[PairwiseExample] = []
    cursor = int(start_id)
    for race in races:
        for outcome in build_pairwise_outcomes(race):
            rows.append(
                PairwiseExample(
                    comparison_id=cursor,
                    race_id=race.race_id,
                    race_date=race.race_date,
                    meet_id=race.meet_id,
                    season_year=race.season_year,
                    event=race.event,
                    round_class=race.round_class,
                    grade_text=race.grade_text,
                    gender=race.gender,
                    winner_id=outcome.winner.athlete_id,
                    loser_id=outcome.loser.athlete_id,
                    winner_rank=outcome.winner.rank,
                    loser_rank=outcome.loser.rank,
                    winner_status=outcome.winner.status,
                    loser_status=outcome.loser.status,
                    winner_time_sec=outcome.winner.time_sec,
                    loser_time_sec=outcome.loser.time_sec,
                    source_status=outcome.source_status,
                )
            )
            cursor += 1
    return rows


class ConstantBaseline:
    name = "B0"

    def predict(self, example: PairwiseExample) -> BaselinePrediction:
        del example
        return BaselinePrediction(probability=0.5, covered=True)

    def update(self, races: Sequence[RaceObservation]) -> None:
        del races


class HeadToHeadBaseline:
    name = "B1"

    def __init__(self, fixed_probability: float = 0.65) -> None:
        if fixed_probability <= 0.5 or fixed_probability >= 1.0:
            raise ValueError("[error] B1 fixed_probability는 (0.5, 1.0) 범위여야 합니다.")
        self.fixed_probability = float(fixed_probability)
        self._latest_winner: dict[tuple[str, str], tuple[str, date]] = {}

    def predict(self, example: PairwiseExample) -> BaselinePrediction:
        key = tuple(sorted((example.winner_id, example.loser_id)))
        latest = self._latest_winner.get(key)
        if latest is None:
            return BaselinePrediction(probability=0.5, covered=False)
        winner_id, _observed_date = latest
        if winner_id == example.winner_id:
            return BaselinePrediction(probability=self.fixed_probability, covered=True)
        return BaselinePrediction(probability=1.0 - self.fixed_probability, covered=True)

    def update(self, races: Sequence[RaceObservation]) -> None:
        for race in races:
            for outcome in build_pairwise_outcomes(race):
                key = tuple(sorted((outcome.winner.athlete_id, outcome.loser.athlete_id)))
                self._latest_winner[key] = (outcome.winner.athlete_id, race.race_date)


class PreviousSeasonBestTimeBaseline:
    name = "B2"
    default_scale = 0.02

    def __init__(self, *, season_year: int, races: Sequence[RaceObservation], scale: float | None = None) -> None:
        self.scale = float(scale) if scale is not None else float(self.default_scale)
        self._season_year = int(season_year)
        self._best_times: dict[tuple[str, str], float] = {}
        for race in races:
            if race.season_year != self._season_year:
                continue
            event_key = race.event or "(unknown-event)"
            for participant in race.participants:
                if participant.time_sec is None or participant.time_sec <= 0:
                    continue
                key = (participant.athlete_id, event_key)
                current = self._best_times.get(key)
                if current is None or participant.time_sec < current:
                    self._best_times[key] = float(participant.time_sec)

    def delta(self, example: PairwiseExample) -> float | None:
        """승자 기준 상대 기록차. 커버 불가면 None."""
        event_key = example.event or "(unknown-event)"
        winner_time = self._best_times.get((example.winner_id, event_key))
        loser_time = self._best_times.get((example.loser_id, event_key))
        if winner_time is None or loser_time is None:
            return None
        return (loser_time - winner_time) / max(winner_time, loser_time, 1e-6)

    def predict(self, example: PairwiseExample) -> BaselinePrediction:
        gap = self.delta(example)
        if gap is None:
            return BaselinePrediction(probability=0.5, covered=False)
        if abs(gap) < 1e-9:
            return BaselinePrediction(probability=0.5, covered=True)
        probability = _sigmoid(gap / self.scale)
        return BaselinePrediction(probability=_clamp_probability(probability), covered=True)

    def update(self, races: Sequence[RaceObservation]) -> None:
        del races


class LastMeetPercentileBaseline:
    name = "B3"
    default_scale = 0.15

    def __init__(self, *, scale: float | None = None, allow_cross_event: bool = False) -> None:
        self.scale = float(scale) if scale is not None else float(self.default_scale)
        # 500M 백분위로 3000M 승부를 예측하지 않습니다. 종목이 다르면 기권합니다.
        self.allow_cross_event = bool(allow_cross_event)
        self._scores_by_event: dict[tuple[str, str], tuple[date, float]] = {}
        self._scores_any_event: dict[str, tuple[date, float]] = {}

    def delta(self, example: PairwiseExample) -> float | None:
        """승자 기준 직전 대회 백분위 차. 커버 불가면 None."""
        event_key = example.event or "(unknown-event)"
        winner = self._lookup_score(example.winner_id, event_key)
        loser = self._lookup_score(example.loser_id, event_key)
        if winner is None or loser is None:
            return None
        return winner - loser

    def predict(self, example: PairwiseExample) -> BaselinePrediction:
        gap = self.delta(example)
        if gap is None:
            return BaselinePrediction(probability=0.5, covered=False)
        probability = _sigmoid(gap / self.scale)
        return BaselinePrediction(probability=_clamp_probability(probability), covered=True)

    def _lookup_score(self, athlete_id: str, event_key: str) -> float | None:
        event_row = self._scores_by_event.get((athlete_id, event_key))
        if event_row is not None:
            return event_row[1]
        if not self.allow_cross_event:
            return None
        any_row = self._scores_any_event.get(athlete_id)
        if any_row is not None:
            return any_row[1]
        return None

    def update(self, races: Sequence[RaceObservation]) -> None:
        by_meet: dict[str, list[RaceObservation]] = {}
        for race in races:
            by_meet.setdefault(race.meet_id, []).append(race)
        for meet_id in sorted(by_meet.keys()):
            meet_races = sorted(by_meet[meet_id], key=lambda item: (item.race_date, item.race_id))
            if not meet_races:
                continue
            meet_date = meet_races[-1].race_date
            athlete_scores: dict[tuple[str, str], float] = {}
            athlete_scores_any: dict[str, float] = {}
            for race in meet_races:
                ranked = [participant for participant in race.participants if participant.rank > 0]
                ranked.sort(key=lambda item: (item.rank, item.athlete_id))
                total = len(ranked)
                if total <= 0:
                    continue
                event_key = race.event or "(unknown-event)"
                for participant in ranked:
                    if total == 1:
                        percentile = 0.5
                    else:
                        percentile = 1.0 - ((participant.rank - 1) / float(total - 1))
                    event_key_id = (participant.athlete_id, event_key)
                    previous = athlete_scores.get(event_key_id)
                    if previous is None or percentile > previous:
                        athlete_scores[event_key_id] = percentile
                    any_previous = athlete_scores_any.get(participant.athlete_id)
                    if any_previous is None or percentile > any_previous:
                        athlete_scores_any[participant.athlete_id] = percentile

            for key, score in athlete_scores.items():
                current = self._scores_by_event.get(key)
                if current is None or meet_date >= current[0]:
                    self._scores_by_event[key] = (meet_date, float(score))
            for athlete_id, score in athlete_scores_any.items():
                current = self._scores_any_event.get(athlete_id)
                if current is None or meet_date >= current[0]:
                    self._scores_any_event[athlete_id] = (meet_date, float(score))
