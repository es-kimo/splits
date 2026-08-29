from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


def clamp_probability(value: float, *, eps: float = 1e-6) -> float:
    return min(max(float(value), eps), 1.0 - eps)


def _wilson_interval(successes: int, total: int, *, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 1.0)
    p_hat = float(successes) / float(total)
    z2 = z * z
    denom = 1.0 + (z2 / float(total))
    center = (p_hat + (z2 / (2.0 * float(total)))) / denom
    margin = (z / denom) * math.sqrt((p_hat * (1.0 - p_hat) / float(total)) + (z2 / (4.0 * float(total) * float(total))))
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass(frozen=True)
class CalibrationBin:
    index: int
    start: float
    end: float
    count: int
    mean_pred: float
    win_rate: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class CalibrationSummary:
    bins: tuple[CalibrationBin, ...]
    ece: float
    overconfidence_70: bool
    overconfidence_70_count: int
    overconfidence_70_win_rate: float
    overconfidence_70_ci_low: float
    overconfidence_70_ci_high: float


@dataclass(frozen=True)
class MetricSummary:
    sample_size: int
    accuracy: float
    log_loss: float
    brier: float
    coverage: float
    calibration: CalibrationSummary


def compute_calibration(
    actuals: Sequence[int],
    probabilities: Sequence[float],
    *,
    n_bins: int = 10,
) -> CalibrationSummary:
    if len(actuals) != len(probabilities):
        raise ValueError("[error] actuals/probabilities 길이가 일치하지 않습니다.")
    if n_bins <= 0:
        raise ValueError("[error] n_bins는 1 이상이어야 합니다.")

    bins: list[list[tuple[int, float]]] = [[] for _ in range(n_bins)]
    for actual, prob in zip(actuals, probabilities):
        p = clamp_probability(prob)
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((int(actual), p))

    bin_rows: list[CalibrationBin] = []
    total = len(actuals)
    weighted_error = 0.0
    for idx, values in enumerate(bins):
        start = idx / float(n_bins)
        end = (idx + 1) / float(n_bins)
        if not values:
            bin_rows.append(
                CalibrationBin(
                    index=idx,
                    start=start,
                    end=end,
                    count=0,
                    mean_pred=(start + end) / 2.0,
                    win_rate=0.0,
                    ci_low=0.0,
                    ci_high=1.0,
                )
            )
            continue
        count = len(values)
        wins = sum(actual for actual, _ in values)
        mean_pred = sum(prob for _, prob in values) / float(count)
        win_rate = wins / float(count)
        ci_low, ci_high = _wilson_interval(wins, count)
        weighted_error += abs(win_rate - mean_pred) * (count / float(total))
        bin_rows.append(
            CalibrationBin(
                index=idx,
                start=start,
                end=end,
                count=count,
                mean_pred=mean_pred,
                win_rate=win_rate,
                ci_low=ci_low,
                ci_high=ci_high,
            )
        )

    over_rows = [(int(actual), clamp_probability(prob)) for actual, prob in zip(actuals, probabilities) if prob >= 0.70 and prob < 0.80]
    if over_rows:
        over_count = len(over_rows)
        over_wins = sum(actual for actual, _ in over_rows)
        over_rate = over_wins / float(over_count)
        over_low, over_high = _wilson_interval(over_wins, over_count)
        overconfident = over_high < 0.70
    else:
        over_count = 0
        over_rate = 0.0
        over_low = 0.0
        over_high = 1.0
        overconfident = False

    return CalibrationSummary(
        bins=tuple(bin_rows),
        ece=weighted_error if total > 0 else 0.0,
        overconfidence_70=overconfident,
        overconfidence_70_count=over_count,
        overconfidence_70_win_rate=over_rate,
        overconfidence_70_ci_low=over_low,
        overconfidence_70_ci_high=over_high,
    )


def compute_metrics(
    actuals: Sequence[int],
    probabilities: Sequence[float],
    *,
    covered: Sequence[bool] | None = None,
) -> MetricSummary:
    if len(actuals) != len(probabilities):
        raise ValueError("[error] actuals/probabilities 길이가 일치하지 않습니다.")
    size = len(actuals)
    if size == 0:
        calibration = compute_calibration([], [], n_bins=10)
        return MetricSummary(sample_size=0, accuracy=0.0, log_loss=0.0, brier=0.0, coverage=0.0, calibration=calibration)

    probs = [clamp_probability(value) for value in probabilities]
    labels = [int(value) for value in actuals]

    correct = 0
    loss_sum = 0.0
    brier_sum = 0.0
    for label, prob in zip(labels, probs):
        predicted = 1 if prob >= 0.5 else 0
        if predicted == label:
            correct += 1
        loss_sum += -(label * math.log(prob) + (1 - label) * math.log(1.0 - prob))
        brier_sum += (prob - float(label)) ** 2

    if covered is None:
        coverage = 1.0
    else:
        if len(covered) != size:
            raise ValueError("[error] covered 길이가 예측 건수와 일치하지 않습니다.")
        coverage = sum(1 for value in covered if value) / float(size)

    calibration = compute_calibration(labels, probs, n_bins=10)
    return MetricSummary(
        sample_size=size,
        accuracy=correct / float(size),
        log_loss=loss_sum / float(size),
        brier=brier_sum / float(size),
        coverage=coverage,
        calibration=calibration,
    )


def calibration_to_svg(calibration: CalibrationSummary, title: str) -> str:
    width = 720
    height = 420
    margin_left = 70
    margin_right = 30
    margin_top = 50
    margin_bottom = 60
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    def sx(value: float) -> float:
        return margin_left + (plot_w * value)

    def sy(value: float) -> float:
        return margin_top + plot_h - (plot_h * value)

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2:.1f}" y="28" text-anchor="middle" font-size="16" font-family="sans-serif">{title}</text>',
        f'<line x1="{margin_left}" y1="{sy(0):.2f}" x2="{width - margin_right}" y2="{sy(0):.2f}" stroke="#374151" stroke-width="1"/>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#374151" stroke-width="1"/>',
        f'<line x1="{sx(0):.2f}" y1="{sy(0):.2f}" x2="{sx(1):.2f}" y2="{sy(1):.2f}" stroke="#9CA3AF" stroke-width="1.5" stroke-dasharray="5 4"/>',
        f'<text x="{width/2:.1f}" y="{height - 20}" text-anchor="middle" font-size="12" font-family="sans-serif">예측 확률</text>',
        f'<text x="18" y="{height/2:.1f}" text-anchor="middle" font-size="12" font-family="sans-serif" transform="rotate(-90,18,{height/2:.1f})">실제 승률</text>',
    ]

    for tick in range(0, 11, 2):
        value = tick / 10.0
        x = sx(value)
        y = sy(value)
        lines.append(f'<line x1="{x:.2f}" y1="{sy(0):.2f}" x2="{x:.2f}" y2="{sy(0)+5:.2f}" stroke="#374151" stroke-width="1"/>')
        lines.append(f'<text x="{x:.2f}" y="{sy(0)+20:.2f}" text-anchor="middle" font-size="10" font-family="sans-serif">{value:.1f}</text>')
        lines.append(f'<line x1="{margin_left-5}" y1="{y:.2f}" x2="{margin_left:.2f}" y2="{y:.2f}" stroke="#374151" stroke-width="1"/>')
        lines.append(f'<text x="{margin_left-10:.2f}" y="{y+3:.2f}" text-anchor="end" font-size="10" font-family="sans-serif">{value:.1f}</text>')

    for row in calibration.bins:
        if row.count <= 0:
            continue
        x = sx(row.mean_pred)
        y = sy(row.win_rate)
        low_y = sy(row.ci_low)
        high_y = sy(row.ci_high)
        lines.append(f'<line x1="{x:.2f}" y1="{low_y:.2f}" x2="{x:.2f}" y2="{high_y:.2f}" stroke="#0EA5E9" stroke-width="1.5"/>')
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#0284C7"/>')

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def write_calibration_svg(path: Path, calibration: CalibrationSummary, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(calibration_to_svg(calibration, title), encoding="utf-8")

