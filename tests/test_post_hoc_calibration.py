import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.metrics import (
    IDENTITY_SCALER,
    calibration_null,
    compute_calibration,
    compute_metrics,
    fit_platt_scaler,
)


def _overconfident_sample(n: int = 6000, seed: int = 3):
    """판별력은 있으나 확률이 과분산인 예측기.

    보정 전 R-05의 TrueSkill이 정확히 이 상태였습니다.
    """
    rng = random.Random(seed)
    probabilities: list[float] = []
    labels: list[int] = []
    for _ in range(n):
        true_p = rng.uniform(0.2, 0.8)
        labels.append(1 if rng.random() < true_p else 0)
        logit = math.log(true_p / (1.0 - true_p))
        probabilities.append(1.0 / (1.0 + math.exp(-2.2 * logit)))  # 로짓을 2.2배 부풀림
    return probabilities, labels


class TestPlattScaler:
    def test_identity_scaler_changes_nothing(self):
        for p in (0.05, 0.5, 0.93):
            assert IDENTITY_SCALER.apply(p) == pytest.approx(p, rel=1e-9)

    def test_fit_recovers_a_shrinking_slope_for_overconfidence(self):
        probabilities, labels = _overconfident_sample()
        scaler = fit_platt_scaler(probabilities, labels)
        assert scaler.slope < 1.0

    def test_calibration_improves_after_scaling(self):
        probabilities, labels = _overconfident_sample()
        scaler = fit_platt_scaler(probabilities, labels)
        scaled = [scaler.apply(p) for p in probabilities]
        assert compute_calibration(labels, scaled).ece < compute_calibration(labels, probabilities).ece

    def test_log_loss_improves_after_scaling(self):
        probabilities, labels = _overconfident_sample()
        scaler = fit_platt_scaler(probabilities, labels)
        scaled = [scaler.apply(p) for p in probabilities]
        assert compute_metrics(labels, scaled).log_loss < compute_metrics(labels, probabilities).log_loss

    def test_accuracy_is_unchanged_because_the_map_is_monotone(self):
        """보정은 캘리브레이션만 바꾸고 판별력은 건드리지 않습니다.

        이 성질 때문에 보정 전 엔진 비교가 불공정합니다 — 고칠 수 있는 약점과
        못 고치는 약점을 같은 무게로 재게 됩니다.
        """
        probabilities, labels = _overconfident_sample()
        scaler = fit_platt_scaler(probabilities, labels)
        scaled = [scaler.apply(p) for p in probabilities]
        assert compute_metrics(labels, scaled).accuracy == pytest.approx(
            compute_metrics(labels, probabilities).accuracy, abs=0.02
        )

    def test_preserves_ordering(self):
        scaler = fit_platt_scaler(*_overconfident_sample())
        values = [0.05, 0.2, 0.5, 0.8, 0.95]
        scaled = [scaler.apply(p) for p in values]
        assert scaled == sorted(scaled)

    def test_already_calibrated_input_stays_near_identity(self):
        rng = random.Random(9)
        probabilities = [rng.uniform(0.1, 0.9) for _ in range(6000)]
        labels = [1 if rng.random() < p else 0 for p in probabilities]
        scaler = fit_platt_scaler(probabilities, labels)
        assert scaler.slope == pytest.approx(1.0, abs=0.25)

    def test_empty_input_returns_identity(self):
        assert fit_platt_scaler([], []) == IDENTITY_SCALER

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError, match="길이가 일치하지 않습니다"):
            fit_platt_scaler([0.5, 0.5], [1])


class TestCalibrationNull:
    def test_perfectly_calibrated_predictions_still_show_nonzero_ece(self):
        """ECE의 유한표본 상향 편향. 게이트를 해석하려면 이 바닥을 알아야 합니다."""
        rng = random.Random(11)
        probabilities = [rng.uniform(0.05, 0.95) for _ in range(18_425)]
        null = calibration_null(probabilities, resamples=100)
        assert 0.0 < null.p50 < null.p95 < null.p99

    def test_noise_floor_shrinks_as_the_sample_grows(self):
        rng = random.Random(13)
        small = calibration_null([rng.uniform(0.05, 0.95) for _ in range(500)], resamples=100)
        large = calibration_null([rng.uniform(0.05, 0.95) for _ in range(20_000)], resamples=100)
        assert large.p95 < small.p95

    def test_observed_ece_of_0034_sits_far_above_the_floor_at_this_sample_size(self):
        """재실행 전 관측값 0.03384는 노이즈가 아니라 실제 미스캘리브레이션이었습니다."""
        rng = random.Random(17)
        probabilities = [rng.uniform(0.05, 0.95) for _ in range(18_425)]
        assert calibration_null(probabilities, resamples=100).p99 < 0.03384

    def test_empty_input_is_degenerate(self):
        null = calibration_null([])
        assert (null.p50, null.p95, null.p99, null.resamples) == (0.0, 0.0, 0.0, 0)
