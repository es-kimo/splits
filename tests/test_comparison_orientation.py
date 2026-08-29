import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.baselines import PairwiseExample
from rating.eval.metrics import compute_calibration, compute_metrics


def _example(winner_id: str, loser_id: str, race_id: str = "r1") -> PairwiseExample:
    return PairwiseExample(
        comparison_id=0,
        race_id=race_id,
        race_date=date(2025, 1, 1),
        meet_id="m1",
        season_year=2025,
        event="500M",
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


class TestOrientationIsOutcomeIndependent:
    def test_swapping_winner_and_loser_keeps_the_same_pair_orientation(self):
        """같은 두 선수의 대결이면 누가 이겼든 left/right가 같아야 합니다."""
        won = _example("a1", "a2")
        lost = _example("a2", "a1")
        assert (won.left_id, won.right_id) == (lost.left_id, lost.right_id)

    def test_label_flips_with_the_outcome(self):
        won = _example("a1", "a2")
        lost = _example("a2", "a1")
        assert won.label != lost.label

    def test_label_marks_whether_left_won(self):
        example = _example("a1", "a2")
        expected = 1 if example.left_id == "a1" else 0
        assert example.label == expected

    def test_orientation_is_deterministic_across_instances(self):
        first = _example("a1", "a2")
        second = _example("a1", "a2")
        assert first.left_id == second.left_id

    def test_orient_maps_winner_probability_into_left_frame(self):
        example = _example("a1", "a2")
        oriented = example.orient(0.8)
        assert oriented == (0.8 if example.label == 1 else 0.2)

    def test_orientation_is_balanced_across_many_pairs(self):
        """ID 사전순으로 방향을 잡으면 ID에 담긴 출생연도 때문에 라벨이 쏠립니다."""
        examples = [_example(f"a{i:04d}", f"b{i:04d}", race_id=f"r{i}") for i in range(2000)]
        rate = sum(e.label for e in examples) / len(examples)
        assert 0.45 <= rate <= 0.55


class TestMetricsUnderOrientation:
    def test_log_loss_is_invariant_to_orientation(self):
        """방향 정규화는 log loss를 바꾸지 않아야 합니다."""
        winner_probs = [0.9, 0.7, 0.3, 0.55, 0.62]
        examples = [_example("a1", "a2", race_id=f"r{i}") for i in range(len(winner_probs))]

        one_sided = compute_metrics([1] * len(winner_probs), winner_probs)
        oriented = compute_metrics(
            [e.label for e in examples],
            [e.orient(p) for e, p in zip(examples, winner_probs)],
        )
        assert oriented.log_loss == round(one_sided.log_loss, 12) or math.isclose(
            oriented.log_loss, one_sided.log_loss, rel_tol=1e-12
        )
        assert math.isclose(oriented.brier, one_sided.brier, rel_tol=1e-12)
        assert math.isclose(oriented.accuracy, one_sided.accuracy, rel_tol=1e-12)

    def test_ece_is_degenerate_when_every_label_is_one(self):
        """회귀 방지: 라벨이 전부 1이면 ECE는 1 - mean(p) 항등식이 됩니다."""
        probs = [i / 500.0 for i in range(1, 500)]
        ece = compute_calibration([1] * len(probs), probs).ece
        assert math.isclose(ece, 1.0 - sum(probs) / len(probs), abs_tol=1e-9)

    def test_ece_is_informative_when_labels_are_mixed(self):
        """완벽히 캘리브레이션된 예측은 ECE가 0에 가까워야 합니다."""
        actuals: list[int] = []
        probs: list[float] = []
        for bucket in range(1, 10):
            p = bucket / 10.0
            for i in range(1000):
                probs.append(p)
                actuals.append(1 if i < int(round(p * 1000)) else 0)
        summary = compute_calibration(actuals, probs)
        assert summary.ece < 0.01
        assert not math.isclose(summary.ece, 1.0 - sum(probs) / len(probs), abs_tol=1e-6)

    def test_overconfidence_at_70_can_now_fire(self):
        """라벨이 전부 1이면 Wilson 상한이 0.70 아래로 갈 수 없어 항상 N이었습니다."""
        probs = [0.75] * 2000
        actuals = [1 if i < 800 else 0 for i in range(2000)]  # 실제 승률 0.40
        assert compute_calibration(actuals, probs).overconfidence_70
