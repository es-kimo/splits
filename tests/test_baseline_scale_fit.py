import math
import random
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.baselines import (
    LastMeetPercentileBaseline,
    PairwiseExample,
    RaceObservation,
    RaceParticipant,
    _sigmoid,
    fit_logistic_scale,
)

LN2 = math.log(2.0)


def _example(winner_id: str = "a1", loser_id: str = "a2", event: str = "500M") -> PairwiseExample:
    return PairwiseExample(
        comparison_id=0,
        race_id="r1",
        race_date=date(2025, 1, 1),
        meet_id="m1",
        season_year=2025,
        event=event,
        round_class="final",
        grade_text="5",
        gender="남",
        winner_id=winner_id,
        loser_id=loser_id,
        winner_rank=1,
        loser_rank=2,
        winner_status="FIN",
        loser_status="FIN",
        winner_time_sec=43.0,
        loser_time_sec=44.0,
        source_status="FIN-FIN",
    )


def _mean_log_loss(deltas, labels, scale):
    total = 0.0
    for delta, label in zip(deltas, labels):
        p = min(max(_sigmoid(delta / scale), 1e-6), 1.0 - 1e-6)
        total -= math.log(p) if label == 1 else math.log(1.0 - p)
    return total / len(labels)


class TestFitLogisticScale:
    def test_recovers_the_generating_scale(self):
        rng = random.Random(7)
        true_scale = 0.4
        deltas = [rng.uniform(-1.0, 1.0) for _ in range(20000)]
        labels = [1 if rng.random() < _sigmoid(d / true_scale) else 0 for d in deltas]
        assert fit_logistic_scale(deltas, labels) == pytest.approx(true_scale, rel=0.15)

    def test_result_never_loses_to_a_coin_flip(self):
        """scale이 커지면 예측이 0.5로 수렴하므로 적합값은 ln2 이하여야 합니다."""
        rng = random.Random(11)
        deltas = [rng.uniform(-1.0, 1.0) for _ in range(5000)]
        labels = [1 if rng.random() < _sigmoid(d / 0.3) else 0 for d in deltas]
        assert _mean_log_loss(deltas, labels, fit_logistic_scale(deltas, labels)) <= LN2

    def test_uninformative_deltas_collapse_to_a_coin_flip(self):
        """신호가 없으면 큰 scale을 골라 0.5 근처로 물러서야 합니다."""
        rng = random.Random(13)
        deltas = [rng.uniform(-1.0, 1.0) for _ in range(5000)]
        labels = [rng.randint(0, 1) for _ in range(5000)]
        loss = _mean_log_loss(deltas, labels, fit_logistic_scale(deltas, labels))
        assert loss == pytest.approx(LN2, abs=0.01)

    def test_beats_the_saturating_hardcoded_scale(self):
        """회귀 방지: 상수 0.15는 확률을 포화시켜 동전보다 나빴습니다."""
        rng = random.Random(17)
        deltas = [rng.uniform(-1.0, 1.0) for _ in range(5000)]
        labels = [1 if rng.random() < _sigmoid(d / 0.8) else 0 for d in deltas]
        assert _mean_log_loss(deltas, labels, 0.15) > LN2
        assert _mean_log_loss(deltas, labels, fit_logistic_scale(deltas, labels)) < LN2

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError, match="길이가 일치하지 않습니다"):
            fit_logistic_scale([0.1, 0.2], [1])


class TestOrientDelta:
    def test_flips_sign_with_the_label(self):
        example = _example("a1", "a2")
        expected = 1.0 if example.label == 1 else -1.0
        assert example.orient_delta(1.0) == expected

    def test_fit_is_invariant_to_the_frame(self):
        """로그 손실은 방향 변환에 불변이라 적합값도 같습니다.

        orient_delta를 쓰는 이유는 최적값을 바꾸기 위해서가 아니라, 적합에 쓰는
        (delta, label)이 채점되는 (probability, actual)과 같은 프레임에 있도록
        맞추기 위해서입니다.
        """
        rng = random.Random(19)
        winner_deltas = [rng.gauss(0.25, 0.5) for _ in range(4000)]

        oriented_deltas: list[float] = []
        oriented_labels: list[int] = []
        for delta in winner_deltas:
            if rng.random() < 0.5:
                oriented_deltas.append(delta)
                oriented_labels.append(1)
            else:
                oriented_deltas.append(-delta)
                oriented_labels.append(0)

        winner_frame = fit_logistic_scale(winner_deltas, [1] * len(winner_deltas))
        oriented_frame = fit_logistic_scale(oriented_deltas, oriented_labels)
        assert winner_frame == pytest.approx(oriented_frame, rel=1e-6)


class TestCrossEventFallback:
    def _meet(self, event: str, ranks: dict[str, int]) -> RaceObservation:
        return RaceObservation(
            race_id=f"r-{event}",
            race_date=date(2024, 12, 1),
            meet_id="m1",
            season_year=2024,
            event=event,
            round_class="final",
            grade_text="5",
            gender="남",
            participants=tuple(
                RaceParticipant(athlete_id=a, rank=r, status="FIN", time_sec=40.0 + r) for a, r in ranks.items()
            ),
        )

    def test_declines_to_predict_across_events_by_default(self):
        """500M 백분위로 3000M 승부를 예측하지 않습니다."""
        baseline = LastMeetPercentileBaseline()
        baseline.update([self._meet("500M", {"a1": 1, "a2": 2})])
        prediction = baseline.predict(_example("a1", "a2", event="3000M"))
        assert not prediction.covered
        assert prediction.probability == 0.5

    def test_cross_event_fallback_is_opt_in(self):
        baseline = LastMeetPercentileBaseline(allow_cross_event=True)
        baseline.update([self._meet("500M", {"a1": 1, "a2": 2})])
        assert baseline.predict(_example("a1", "a2", event="3000M")).covered

    def test_same_event_still_predicts(self):
        baseline = LastMeetPercentileBaseline()
        baseline.update([self._meet("500M", {"a1": 1, "a2": 2})])
        prediction = baseline.predict(_example("a1", "a2", event="500M"))
        assert prediction.covered
        assert prediction.probability > 0.5
