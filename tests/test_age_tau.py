import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.age_tau import TauProfileResult, render_report
from rating.eval.metrics import BootstrapInterval


def _row(name: str, loss: float, low: float, high: float) -> TauProfileResult:
    return TauProfileResult(
        name=name,
        tau_by_age_band={"<=12": 0.5, "13-15": 0.5, "16+": 0.5},
        log_loss=loss,
        accuracy=0.70,
        interval=BootstrapInterval(point=loss, low=low, high=high, resamples=1000),
    )


def test_age_tau_report_rejects_overlapping_profile_intervals():
    report = render_report([_row("global", 0.556, 0.547, 0.565), _row("younger-high", 0.551, 0.541, 0.561)])
    assert "기각 (식별 불가)" in report
    assert "드리프트 항은" in report


def test_age_tau_report_accepts_separated_profile_interval():
    report = render_report([_row("global", 0.556, 0.547, 0.565), _row("younger-high", 0.530, 0.520, 0.540)])
    assert "최종 판정: **채택**" in report
