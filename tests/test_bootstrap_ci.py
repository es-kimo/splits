import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.metrics import bootstrap_log_loss_ci, compute_metrics


class TestBootstrapLogLossCI:
    def test_point_estimate_matches_compute_metrics(self):
        rng = random.Random(3)
        probs = [rng.uniform(0.05, 0.95) for _ in range(500)]
        labels = [1 if rng.random() < p else 0 for p in probs]
        groups = [f"race{i // 5}" for i in range(500)]

        interval = bootstrap_log_loss_ci(labels, probs, groups, resamples=200)
        assert interval.point == pytest.approx(compute_metrics(labels, probs).log_loss, rel=1e-12)

    def test_interval_brackets_the_point_estimate(self):
        rng = random.Random(5)
        probs = [rng.uniform(0.05, 0.95) for _ in range(800)]
        labels = [1 if rng.random() < p else 0 for p in probs]
        groups = [f"race{i // 4}" for i in range(800)]

        interval = bootstrap_log_loss_ci(labels, probs, groups, resamples=400)
        assert interval.low <= interval.point <= interval.high

    def test_is_deterministic_for_a_fixed_seed(self):
        rng = random.Random(7)
        probs = [rng.uniform(0.05, 0.95) for _ in range(300)]
        labels = [1 if rng.random() < p else 0 for p in probs]
        groups = [f"race{i // 3}" for i in range(300)]

        first = bootstrap_log_loss_ci(labels, probs, groups, resamples=200)
        second = bootstrap_log_loss_ci(labels, probs, groups, resamples=200)
        assert (first.low, first.high) == (second.low, second.high)

    def test_block_resampling_is_wider_than_ignoring_correlation(self):
        """같은 레이스의 비교는 함께 움직이므로 블록을 무시하면 구간이 좁아집니다.

        레이스마다 공통 충격을 넣어 상관을 만들고, 레이스 단위 블록 구간이
        비교 단위(블록 크기 1) 구간보다 넓은지 확인합니다.
        """
        rng = random.Random(11)
        probs: list[float] = []
        labels: list[int] = []
        blocked_groups: list[str] = []
        for race in range(200):
            # 그 날 그 레이스의 예측이 통째로 맞거나 통째로 빗나갑니다.
            # 예측 확률을 0.5에서 떨어뜨려야 충격이 손실 항에 실제로 반영됩니다.
            shock = rng.choice([0.15, 0.85])
            for _ in range(10):
                probs.append(0.7)
                labels.append(1 if rng.random() < shock else 0)
                blocked_groups.append(f"race{race}")

        blocked = bootstrap_log_loss_ci(labels, probs, blocked_groups, resamples=400)
        per_comparison = bootstrap_log_loss_ci(
            labels, probs, [str(i) for i in range(len(probs))], resamples=400
        )
        assert (blocked.high - blocked.low) > (per_comparison.high - per_comparison.low)

    def test_overlaps_detects_indistinguishable_configs(self):
        rng = random.Random(13)
        probs = [rng.uniform(0.05, 0.95) for _ in range(600)]
        labels = [1 if rng.random() < p else 0 for p in probs]
        groups = [f"race{i // 5}" for i in range(600)]

        left = bootstrap_log_loss_ci(labels, probs, groups, resamples=300)
        # 0.003 차이는 1차 실행에서 conservative/meet vs month 간격입니다.
        nudged = [min(max(p + 0.001, 1e-6), 1 - 1e-6) for p in probs]
        right = bootstrap_log_loss_ci(labels, nudged, groups, resamples=300)
        assert left.overlaps(right)

    def test_empty_input_returns_a_degenerate_interval(self):
        interval = bootstrap_log_loss_ci([], [], [])
        assert (interval.point, interval.low, interval.high, interval.resamples) == (0.0, 0.0, 0.0, 0)

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError, match="길이가 일치하지 않습니다"):
            bootstrap_log_loss_ci([1, 0], [0.5, 0.5], ["r1"])

    def test_single_block_has_zero_width(self):
        """레이스가 하나면 리샘플링해도 같은 블록만 나옵니다."""
        interval = bootstrap_log_loss_ci([1, 0, 1], [0.6, 0.4, 0.7], ["r1"] * 3, resamples=50)
        assert interval.low == interval.high == pytest.approx(interval.point)

    def test_perfect_predictions_have_a_tight_interval_near_zero(self):
        labels = [1, 0] * 100
        probs = [0.999999 if label == 1 else 0.000001 for label in labels]
        groups = [f"race{i // 2}" for i in range(200)]
        interval = bootstrap_log_loss_ci(labels, probs, groups, resamples=200)
        assert interval.high < 1e-5
        assert interval.point == pytest.approx(-math.log(0.999999), rel=1e-6)
