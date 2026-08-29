import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.backtest import BaselineScales, ConfigResult, Metrics, decide
from rating.eval.invariants import ENTROPY_SLACK, LN2, assert_harness_invariants, binary_entropy
from rating.eval.metrics import IDENTITY_SCALER, CalibrationNull


def _metrics(
    *,
    log_loss: float,
    accuracy: float = 0.69,
    ece: float = 0.03,
    probabilities: list[float] | None = None,
    labels: list[int] | None = None,
    overconfident: bool = False,
) -> Metrics:
    probs = probabilities if probabilities is not None else [0.6, 0.4] * 50
    actual = labels if labels is not None else [1, 0] * 50
    return Metrics(
        sample_size=len(probs),
        accuracy=accuracy,
        log_loss=log_loss,
        brier=0.2,
        coverage=1.0,
        ece=ece,
        overconfidence_70=overconfident,
        overconfidence_70_count=0,
        overconfidence_70_win_rate=0.0,
        overconfidence_70_ci_low=0.0,
        overconfidence_70_ci_high=1.0,
        predictions=pl.DataFrame({"probability": probs, "actual": actual}),
    )


def _result(**overrides) -> ConfigResult:
    metrics = {
        "B0": _metrics(log_loss=LN2),
        "B1": _metrics(log_loss=0.635),
        "B2": _metrics(log_loss=0.648),
        "B3": _metrics(log_loss=0.624),
        "glicko2": _metrics(log_loss=0.583),
    }
    metrics.update(overrides.pop("metrics", {}))
    base = {
        "policy": "conservative",
        "rating_period": "meet",
        "engine": "glicko2",
        "holdout_seasons": (2025, 2026),
        "baseline_scales": BaselineScales(b2=0.07, b3=0.64, b2_sample=100, b3_sample=100),
        "holdout_comparison_count": 18_425,
        "total_comparison_count": 165_399,
        "engine_tau": 0.5,
        "engine_tau_scores": {0.5: 0.58},
        "scaler": IDENTITY_SCALER,
        "raw_metrics": metrics["glicko2"],
        "calibration_null": CalibrationNull(p50=0.008, p95=0.011, p99=0.013, resamples=500),
        "metrics_by_predictor": metrics,
        "common_subset_metrics": metrics,
        "calibration_path": Path("/tmp/cal.svg"),
        "comparison_count": 10_000,
    }
    base.update(overrides)
    return ConfigResult(**base)


class TestHarnessInvariants:
    def test_healthy_result_passes(self):
        assert_harness_invariants(_result())

    def test_coin_flip_must_equal_ln2(self):
        """하네스의 라벨/확률 경로가 살아 있는지 확인하는 검산입니다."""
        result = _result(metrics={"B0": _metrics(log_loss=0.55)})
        with pytest.raises(ValueError, match="동전 던지기"):
            assert_harness_invariants(result)

    @pytest.mark.parametrize("name", ["B1", "B2", "B3"])
    def test_baseline_worse_than_random_is_a_defect(self, name):
        """B3가 동전보다 나쁘면 그건 발견이 아니라 구현 결함입니다."""
        result = _result(metrics={name: _metrics(log_loss=1.31)})
        with pytest.raises(ValueError, match=f"{name} log loss"):
            assert_harness_invariants(result)

    def test_oversized_holdout_is_rejected(self):
        """2시즌 홀드아웃이 전체의 69%를 차지할 수는 없습니다."""
        result = _result(holdout_comparison_count=119_892, total_comparison_count=173_856)
        with pytest.raises(ValueError, match="홀드아웃 비교"):
            assert_harness_invariants(result)

    def test_log_loss_below_the_accuracy_entropy_floor_is_rejected(self):
        result = _result(metrics={"glicko2": _metrics(log_loss=0.10, accuracy=0.69)})
        with pytest.raises(ValueError, match="엔트로피 하한"):
            assert_harness_invariants(result)

    def test_ece_identity_is_rejected(self):
        """D2 회귀 방지: log loss가 멀쩡해 엔트로피 검사로는 잡히지 않습니다."""
        probs = [0.6, 0.4] * 50
        mean_p = sum(probs) / len(probs)
        result = _result(metrics={"glicko2": _metrics(log_loss=0.583, ece=1.0 - mean_p, probabilities=probs)})
        with pytest.raises(ValueError, match="1-mean\\(p\\)"):
            assert_harness_invariants(result)

    def test_entropy_check_alone_cannot_catch_the_ece_identity(self):
        """ECE 항등식 검사가 따로 필요한 이유입니다.

        라벨이 전부 1이어도 log loss 자체는 멀쩡하므로 엔트로피 하한 검사(4번)는
        통과합니다. 리뷰가 제안한 네 줄로는 D2가 잡히지 않습니다.
        """
        probs = [0.6, 0.4] * 50
        degenerate = _metrics(log_loss=0.583, ece=1.0 - sum(probs) / len(probs), probabilities=probs)
        assert degenerate.log_loss >= binary_entropy(degenerate.accuracy) - ENTROPY_SLACK

    def test_skewed_labels_are_rejected(self):
        result = _result(metrics={"glicko2": _metrics(log_loss=0.583, labels=[1] * 100)})
        with pytest.raises(ValueError, match="라벨 평균"):
            assert_harness_invariants(result)


class TestVerdict:
    def test_go_requires_every_gate(self):
        verdict = decide(_metrics(log_loss=0.58, ece=0.02), improvement=0.08)
        assert verdict.label == "GO"
        assert verdict.blocking == ()
        assert verdict.adr_status == "Accepted"

    def test_calibration_gate_blocks_go_and_is_recorded(self):
        """개선율이 충분해도 ECE가 막으면, 무엇이 막았는지 남아야 합니다.

        1차 실행이 14.98% 개선율에도 GO가 아니었던 이유가 이것인데, ADR 본문에는
        그 사실이 적히지 않았습니다.
        """
        verdict = decide(_metrics(log_loss=0.58, ece=0.034), improvement=0.065)
        assert verdict.label == "조건부"
        assert verdict.blocking == ("ECE <= 0.03 (관측 0.03400)",)
        assert verdict.adr_status == "Proposed"

    def test_overconfidence_blocks_go(self):
        verdict = decide(_metrics(log_loss=0.58, ece=0.02, overconfident=True), improvement=0.09)
        assert verdict.label == "조건부"
        assert "70% 과신 없음 (관측 Y)" in verdict.blocking

    def test_stop_below_one_percent(self):
        assert decide(_metrics(log_loss=0.69, ece=0.02), improvement=0.004).label == "STOP"

    def test_non_go_verdicts_never_write_an_accepted_adr(self):
        for improvement, ece in ((0.065, 0.034), (0.02, 0.02), (0.001, 0.02)):
            verdict = decide(_metrics(log_loss=0.58, ece=ece), improvement=improvement)
            assert verdict.adr_status == "Proposed"
