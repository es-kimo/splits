"""R-19 — sigma 역전이 `|mu 차이|` 교락인지 sigma 갱신 버그인지 판정합니다.

R-05(ADR 0006) 세그먼트 분해에서 sigma가 큰 쌍이 오히려 더 잘 맞았습니다.
불확실성이 큰 쪽이 더 정확하다는 건 상식에 반하므로 둘 중 하나입니다.

- 교락: sigma가 큰 쌍은 실력 차이도 커서 애초에 쉬운 문제였다.
- 버그: sigma가 작은 쌍이 실제보다 확신에 차 있어서 손해를 봤다.

`|mu_A - mu_B|`를 5분위로 통제한 뒤 각 분위 안에서 sigma-오차 관계를 다시 재는
방식으로 둘을 가릅니다. 판정 규칙은 측정 전에 상수로 고정합니다.
"""

from __future__ import annotations

import argparse
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import polars as pl

from rating.engine.types import RatingPeriod
from rating.ledger.policies import POLICIES

from .backtest import (
    EngineChoice,
    _discover_policy_ledgers,
    _evaluate_config,
    EVALUATION_POLICY,
)
from .metrics import compute_metrics

# 판정 규칙은 표를 보기 전에 고정합니다. 결과를 본 뒤 기준을 고르면 어떤 결론이든
# 만들어낼 수 있기 때문입니다.
MU_QUANTILE_COUNT = 5
# 셀이 이보다 작으면 log loss가 표본 노이즈에 휘둘려 방향을 읽을 수 없습니다.
MIN_CELL_SIZE = 200
# 이 폭보다 작은 차이는 역전으로 세지 않습니다. R-05 홀드아웃의 부트스트랩 CI
# 반폭과 같은 자릿수라, 이보다 좁은 차이는 노이즈와 구분되지 않습니다.
INVERSION_MARGIN = 0.01
# 5분위 중 몇 개에서 역전이 남아야 버그로 볼지.
BUG_VERDICT_MIN_QUANTILES = 3


# 5분위는 한 칸이 넓어서 칸 안에 실력 차이가 여전히 섞입니다. 더 촘촘하게 통제할수록
# 역전이 줄어드는지 보면, 남은 역전이 통제 부족 탓인지 실제 효과인지 갈립니다.
SENSITIVITY_BIN_COUNTS: tuple[int, ...] = (5, 10, 20)


@dataclass(frozen=True)
class Cell:
    mu_bucket: str
    sigma_bucket: str
    n: int
    log_loss: float
    accuracy: float
    brier: float
    mu_gap_p50: float
    reliable: bool


@dataclass(frozen=True)
class QuantileRow:
    label: str
    mu_low: float
    mu_high: float
    n: int
    low_sigma_log_loss: float | None
    high_sigma_log_loss: float | None
    reliable: bool

    @property
    def gap(self) -> float | None:
        """high sigma − low sigma. 음수면 역전(큰 불확실성이 더 정확)."""
        if self.low_sigma_log_loss is None or self.high_sigma_log_loss is None:
            return None
        return self.high_sigma_log_loss - self.low_sigma_log_loss

    @property
    def inverted(self) -> bool:
        gap = self.gap
        if gap is None or not self.reliable:
            return False
        return gap < -INVERSION_MARGIN


@dataclass(frozen=True)
class Verdict:
    label: str
    inverted_quantiles: int
    comparable_quantiles: int
    uncontrolled_gap: float
    reason: str


@dataclass(frozen=True)
class MonotonicityRow:
    bucket: str
    n: int
    sigma_p10: float
    sigma_p50: float
    sigma_p90: float


@dataclass(frozen=True)
class SensitivityRow:
    bins: int
    inverted: int
    comparable: int


@dataclass(frozen=True)
class DiagnosisResult:
    config: str
    holdout_seasons: tuple[int, ...]
    sample_size: int
    mu_edges: tuple[float, ...]
    sigma_edges: tuple[float, float]
    cells: tuple[Cell, ...]
    quantile_rows: tuple[QuantileRow, ...]
    uncontrolled: tuple[Cell, ...]
    verdict: Verdict
    sensitivity: tuple[SensitivityRow, ...]
    n_games_rows: tuple[MonotonicityRow, ...]
    idle_rows: tuple[MonotonicityRow, ...]
    n_games_spearman: float
    idle_spearman: float
    scatter_path: Path


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * fraction))
    return float(ordered[min(max(index, 0), len(ordered) - 1)])


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """동순위를 평균 순위로 처리하는 Spearman 상관."""
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    x_ranks = _average_ranks(xs)
    y_ranks = _average_ranks(ys)
    n = float(len(xs))
    mean_x = sum(x_ranks) / n
    mean_y = sum(y_ranks) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x_ranks, y_ranks))
    var_x = sum((a - mean_x) ** 2 for a in x_ranks)
    var_y = sum((b - mean_y) ** 2 for b in y_ranks)
    if var_x <= 0.0 or var_y <= 0.0:
        return 0.0
    return float(cov / math.sqrt(var_x * var_y))


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = average
        position = end + 1
    return ranks


def _metrics_for(frame: pl.DataFrame) -> tuple[int, float, float, float]:
    if frame.height == 0:
        return (0, 0.0, 0.0, 0.0)
    summary = compute_metrics(
        actuals=frame["actual"].to_list(),
        probabilities=frame["probability"].to_list(),
    )
    return (summary.sample_size, summary.log_loss, summary.accuracy, summary.brier)


def _make_cell(frame: pl.DataFrame, mu_bucket: str, sigma_bucket: str) -> Cell:
    n, log_loss, accuracy, brier = _metrics_for(frame)
    gaps = [float(value) for value in frame["pair_mu_abs_diff"].to_list() if value is not None]
    return Cell(
        mu_bucket=mu_bucket,
        sigma_bucket=sigma_bucket,
        n=n,
        log_loss=log_loss,
        accuracy=accuracy,
        brier=brier,
        mu_gap_p50=_percentile(gaps, 0.50),
        reliable=n >= MIN_CELL_SIZE,
    )


def _sigma_bucket_expr(q1: float, q2: float) -> pl.Expr:
    return (
        pl.when(pl.col("pair_sigma_max") <= q1)
        .then(pl.lit("low"))
        .when(pl.col("pair_sigma_max") <= q2)
        .then(pl.lit("mid"))
        .otherwise(pl.lit("high"))
        .alias("sigma_bucket")
    )


def _mu_edges(values: Sequence[float]) -> tuple[float, ...]:
    """5분위 경계. 경계값은 리포트에 남겨 재현 가능하게 합니다."""
    return tuple(_percentile(values, index / MU_QUANTILE_COUNT) for index in range(1, MU_QUANTILE_COUNT))


def _mu_bucket_expr(edges: Sequence[float]) -> pl.Expr:
    expr = pl.when(pl.col("pair_mu_abs_diff") <= edges[0]).then(pl.lit("Q1"))
    for index in range(1, len(edges)):
        expr = expr.when(pl.col("pair_mu_abs_diff") <= edges[index]).then(pl.lit(f"Q{index + 1}"))
    return expr.otherwise(pl.lit(f"Q{len(edges) + 1}")).alias("mu_bucket")


def _decide(quantile_rows: Sequence[QuantileRow], uncontrolled_gap: float) -> Verdict:
    comparable = [row for row in quantile_rows if row.reliable and row.gap is not None]
    inverted = [row for row in comparable if row.inverted]
    if uncontrolled_gap >= -INVERSION_MARGIN:
        return Verdict(
            label="역전 없음",
            inverted_quantiles=len(inverted),
            comparable_quantiles=len(comparable),
            uncontrolled_gap=uncontrolled_gap,
            reason="통제 이전 단계에서 이미 역전이 관측되지 않습니다.",
        )
    if len(inverted) >= BUG_VERDICT_MIN_QUANTILES:
        return Verdict(
            label="버그",
            inverted_quantiles=len(inverted),
            comparable_quantiles=len(comparable),
            uncontrolled_gap=uncontrolled_gap,
            reason=(
                f"실력 차이를 통제한 뒤에도 비교 가능한 {len(comparable)}개 분위 중 "
                f"{len(inverted)}개에서 역전이 남았습니다. 실력 차이로 설명되지 않는 "
                "손실이 낮은 sigma 쪽에 있습니다."
            ),
        )
    return Verdict(
        label="교락",
        inverted_quantiles=len(inverted),
        comparable_quantiles=len(comparable),
        uncontrolled_gap=uncontrolled_gap,
        reason=(
            f"실력 차이를 통제하자 비교 가능한 {len(comparable)}개 분위 중 "
            f"{len(inverted)}개에만 역전이 남았습니다. 역전의 대부분은 sigma가 큰 쌍이 "
            "실력 차이도 컸다는 사실로 설명됩니다."
        ),
    )


def _sensitivity(frame: pl.DataFrame, mu_values: Sequence[float]) -> list[SensitivityRow]:
    rows: list[SensitivityRow] = []
    for bins in SENSITIVITY_BIN_COUNTS:
        edges = [_percentile(mu_values, index / bins) for index in range(1, bins)]
        binned = frame.with_columns(
            pl.col("pair_mu_abs_diff")
            .cut(edges, labels=[str(index) for index in range(bins)])
            .cast(pl.Utf8)
            .alias("sensitivity_bin")
        )
        inverted = 0
        comparable = 0
        for index in range(bins):
            sub = binned.filter(pl.col("sensitivity_bin") == str(index))
            low = sub.filter(pl.col("sigma_bucket") == "low")
            high = sub.filter(pl.col("sigma_bucket") == "high")
            if low.height < MIN_CELL_SIZE or high.height < MIN_CELL_SIZE:
                continue
            comparable += 1
            if (_metrics_for(high)[1] - _metrics_for(low)[1]) < -INVERSION_MARGIN:
                inverted += 1
        rows.append(SensitivityRow(bins=bins, inverted=inverted, comparable=comparable))
    return rows


def _monotonicity_rows(frame: pl.DataFrame, column: str, buckets: Sequence[tuple[str, int, int]]) -> list[MonotonicityRow]:
    rows: list[MonotonicityRow] = []
    for label, low, high in buckets:
        sub = frame.filter((pl.col(column) >= low) & (pl.col(column) <= high))
        if sub.height == 0:
            continue
        sigmas = [float(value) for value in sub["pair_sigma_max"].to_list() if value is not None]
        rows.append(
            MonotonicityRow(
                bucket=label,
                n=len(sigmas),
                sigma_p10=_percentile(sigmas, 0.10),
                sigma_p50=_percentile(sigmas, 0.50),
                sigma_p90=_percentile(sigmas, 0.90),
            )
        )
    return rows


_N_GAMES_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0", 0, 0),
    ("1-2", 1, 2),
    ("3-5", 3, 5),
    ("6-10", 6, 10),
    ("11-20", 11, 20),
    ("21-40", 21, 40),
    ("41-80", 41, 80),
    ("81+", 81, 10**9),
)

_IDLE_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0 (같은 달)", 0, 0),
    ("1-3개월", 1, 3),
    ("4-6개월", 4, 6),
    ("7-12개월", 7, 12),
    ("13-24개월", 13, 24),
    ("25개월+", 25, 10**9),
)


def _render_scatter(frame: pl.DataFrame, path: Path, title: str) -> None:
    """n_games 대 sigma 산점도. 외부 플로팅 의존성 없이 SVG를 직접 씁니다."""
    points = [
        (int(games), float(sigma))
        for games, sigma in zip(frame["pair_n_games_max"].to_list(), frame["pair_sigma_max"].to_list())
        if games is not None and sigma is not None
    ]
    width, height = 720, 420
    left, right, top, bottom = 70, 24, 48, 56
    plot_w = width - left - right
    plot_h = height - top - bottom

    max_games = max((point[0] for point in points), default=1) or 1
    max_sigma = max((point[1] for point in points), default=1.0) or 1.0

    def to_x(games: int) -> float:
        return left + (plot_w * (math.log1p(games) / math.log1p(max_games)))

    def to_y(sigma: float) -> float:
        return top + plot_h - (plot_h * (sigma / max_sigma))

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{left}" y="28" font-family="sans-serif" font-size="15" fill="#111827">{title}</text>',
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#d1d5db"/>',
    ]

    # 표본이 많아 점을 다 찍으면 형태가 안 보입니다. 고유 좌표만 남깁니다.
    # 공통 속성은 그룹으로 올려 파일 크기를 줄입니다.
    seen: set[tuple[int, int]] = set()
    for games, sigma in points:
        key = (int(to_x(games)), int(to_y(sigma)))
        seen.add(key)
    lines.append('<g fill="#2563eb" fill-opacity="0.35">')
    for x, y in sorted(seen):
        lines.append(f'<circle cx="{x}" cy="{y}" r="1.6"/>')
    lines.append("</g>")

    # 버킷 중앙값 추세선을 겹쳐 단조성을 눈으로 확인할 수 있게 합니다.
    trend: list[str] = []
    for label, low, high in _N_GAMES_BUCKETS:
        del label
        sub = [sigma for games, sigma in points if low <= games <= high]
        if len(sub) < MIN_CELL_SIZE:
            continue
        center = [games for games, _ in points if low <= games <= high]
        trend.append(f"{to_x(int(sum(center) / len(center))):.1f},{to_y(_percentile(sub, 0.50)):.1f}")
    if len(trend) >= 2:
        lines.append(f'<polyline points="{" ".join(trend)}" fill="none" stroke="#dc2626" stroke-width="2"/>')

    lines.append(
        f'<text x="{left + plot_w / 2:.0f}" y="{height - 18}" font-family="sans-serif" font-size="12" '
        f'fill="#374151" text-anchor="middle">출전 수 n_games (로그 간격)</text>'
    )
    lines.append(
        f'<text x="18" y="{top + plot_h / 2:.0f}" font-family="sans-serif" font-size="12" fill="#374151" '
        f'transform="rotate(-90 18 {top + plot_h / 2:.0f})" text-anchor="middle">sigma (불확실성)</text>'
    )
    lines.append(
        f'<text x="{width - right:.0f}" y="{top - 8}" font-family="sans-serif" font-size="11" fill="#6b7280" '
        f'text-anchor="end">빨간 선 = 구간별 sigma 중앙값</text>'
    )
    lines.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def diagnose(
    *,
    policy: str,
    ledger_root: Path,
    engine: EngineChoice,
    rating_period: RatingPeriod,
    holdout_season_count: int,
    head2head_prob: float,
    scatter_path: Path,
    calibration_dir: Path,
    dump_predictions: Path | None = None,
) -> DiagnosisResult:
    discovered = _discover_policy_ledgers(ledger_root)
    if not discovered:
        raise FileNotFoundError(f"[error] race_ledger를 찾을 수 없습니다: {ledger_root}")
    if policy not in discovered and len(discovered) == 1:
        discovered[policy] = next(iter(discovered.values()))
    if policy not in discovered:
        raise FileNotFoundError(f"[error] 정책 레저를 찾을 수 없습니다: {policy}")
    eval_ledger_path = discovered.get(EVALUATION_POLICY, discovered[policy])

    result = _evaluate_config(
        policy=policy,
        ledger_path=discovered[policy],
        eval_ledger_path=eval_ledger_path,
        engine=engine,
        rating_period=rating_period,
        holdout_season_count=holdout_season_count,
        head2head_prob=head2head_prob,
        calibration_dir=calibration_dir,
    )
    frame = result.metrics_by_predictor[engine].predictions.filter(pl.col("pair_sigma_max").is_not_null())
    if frame.height == 0:
        raise ValueError("[error] 진단할 모델 예측 행이 없습니다.")

    sigma_values = [float(value) for value in frame["pair_sigma_max"].to_list()]
    # R-05 리포트와 같은 터사일 정의를 써야 같은 현상을 보고 있다고 말할 수 있습니다.
    q1 = _percentile(sigma_values, 0.33)
    q2 = _percentile(sigma_values, 0.66)
    mu_values = [float(value) for value in frame["pair_mu_abs_diff"].to_list()]
    edges = _mu_edges(mu_values)

    tagged = frame.with_columns([_sigma_bucket_expr(q1, q2), _mu_bucket_expr(edges)])

    if dump_predictions is not None:
        dump_predictions.parent.mkdir(parents=True, exist_ok=True)
        tagged.write_parquet(dump_predictions)

    uncontrolled: list[Cell] = []
    for sigma_bucket in ("low", "mid", "high"):
        sub = tagged.filter(pl.col("sigma_bucket") == sigma_bucket)
        uncontrolled.append(_make_cell(sub, "전체", sigma_bucket))
    uncontrolled_by_bucket = {cell.sigma_bucket: cell for cell in uncontrolled}
    uncontrolled_gap = uncontrolled_by_bucket["high"].log_loss - uncontrolled_by_bucket["low"].log_loss

    cells: list[Cell] = []
    quantile_rows: list[QuantileRow] = []
    bounds = (min(mu_values), *edges, max(mu_values))
    for index in range(MU_QUANTILE_COUNT):
        label = f"Q{index + 1}"
        quantile_frame = tagged.filter(pl.col("mu_bucket") == label)
        by_bucket: dict[str, Cell] = {}
        for sigma_bucket in ("low", "mid", "high"):
            sub = quantile_frame.filter(pl.col("sigma_bucket") == sigma_bucket)
            cell = _make_cell(sub, label, sigma_bucket)
            cells.append(cell)
            by_bucket[sigma_bucket] = cell
        low_cell = by_bucket["low"]
        high_cell = by_bucket["high"]
        reliable = low_cell.reliable and high_cell.reliable
        quantile_rows.append(
            QuantileRow(
                label=label,
                mu_low=float(bounds[index]),
                mu_high=float(bounds[index + 1]),
                n=quantile_frame.height,
                low_sigma_log_loss=low_cell.log_loss if low_cell.n > 0 else None,
                high_sigma_log_loss=high_cell.log_loss if high_cell.n > 0 else None,
                reliable=reliable,
            )
        )

    verdict = _decide(quantile_rows, uncontrolled_gap)
    sensitivity = _sensitivity(tagged, mu_values)

    n_games_rows = _monotonicity_rows(frame, "pair_n_games_max", _N_GAMES_BUCKETS)
    idle_rows = _monotonicity_rows(frame, "pair_idle_periods_max", _IDLE_BUCKETS)
    n_games_spearman = _spearman(
        [float(value) for value in frame["pair_n_games_max"].to_list()],
        sigma_values,
    )
    idle_spearman = _spearman(
        [float(value) for value in frame["pair_idle_periods_max"].to_list()],
        sigma_values,
    )

    _render_scatter(frame, scatter_path, f"n_games vs sigma — {policy}/{rating_period}/{engine}")

    return DiagnosisResult(
        config=f"{policy}/{rating_period}/{engine}",
        holdout_seasons=result.holdout_seasons,
        sample_size=frame.height,
        mu_edges=edges,
        sigma_edges=(q1, q2),
        cells=tuple(cells),
        quantile_rows=tuple(quantile_rows),
        uncontrolled=tuple(uncontrolled),
        verdict=verdict,
        sensitivity=tuple(sensitivity),
        n_games_rows=tuple(n_games_rows),
        idle_rows=tuple(idle_rows),
        n_games_spearman=n_games_spearman,
        idle_spearman=idle_spearman,
        scatter_path=scatter_path,
    )


def _cell_text(cell: Cell) -> str:
    if cell.n == 0:
        return "표본 없음"
    if not cell.reliable:
        return f"n={cell.n} (표본 부족)"
    return f"{cell.log_loss:.5f}"


def render_report(result: DiagnosisResult, report_path: Path) -> str:
    seasons = ", ".join(str(year) for year in result.holdout_seasons)
    q1, q2 = result.sigma_edges
    lines = [
        "# R-19 — sigma 역전 원인 규명",
        "",
        f"- 대상 설정: `{result.config}`",
        f"- 홀드아웃 시즌: {seasons}",
        f"- 홀드아웃 비교 수: {result.sample_size:,}",
        f"- sigma 구간 경계(터사일): low <= {q1:.4f} < mid <= {q2:.4f} < high",
        "- `|mu 차이|` 5분위 경계: " + ", ".join(f"{edge:.4f}" for edge in result.mu_edges),
        "",
        "sigma는 레이팅의 불확실성입니다. 값이 클수록 그 선수의 실력을 아직 덜 안다는 뜻이고,",
        "쌍에서는 두 선수 중 큰 쪽을 씁니다. `|mu 차이|`는 두 선수 레이팅 평균의 절댓값 차이로,",
        "값이 클수록 애초에 승부를 맞히기 쉬운 쌍입니다.",
        "",
        "## 1. 통제 이전 (R-05 재현)",
        "",
        "| sigma 구간 | n | log_loss | accuracy | brier |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for cell in result.uncontrolled:
        lines.append(
            f"| {cell.sigma_bucket} | {cell.n:,} | {cell.log_loss:.5f} | {cell.accuracy:.4f} | {cell.brier:.5f} |"
        )
    lines.extend(
        [
            "",
            f"high − low log loss 차이: **{result.verdict.uncontrolled_gap:+.5f}** "
            "(음수면 불확실성이 큰 쪽이 더 정확한 역전)",
            "",
            "## 2. `|mu 차이|` 통제 후 sigma-오차 관계",
            "",
            "각 행은 실력 차이가 비슷한 쌍끼리 묶은 구간입니다. 같은 행 안에서 low와 high를",
            "비교하면 실력 차이 효과가 제거된 상태의 sigma 효과만 남습니다.",
            "",
            "| `|mu 차이|` 분위 | 범위 | n | low sigma | mid sigma | high sigma | high − low | 역전 | 칸 안 실제 실력차(low / high) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    cells_by_key = {(cell.mu_bucket, cell.sigma_bucket): cell for cell in result.cells}
    for row in result.quantile_rows:
        low = cells_by_key[(row.label, "low")]
        mid = cells_by_key[(row.label, "mid")]
        high = cells_by_key[(row.label, "high")]
        gap = row.gap
        gap_text = f"{gap:+.5f}" if gap is not None and row.reliable else "—"
        inverted_text = "Y" if row.inverted else ("판정 보류" if not row.reliable else "N")
        lines.append(
            f"| {row.label} | {row.mu_low:.3f}~{row.mu_high:.3f} | {row.n:,} | "
            f"{_cell_text(low)} | {_cell_text(mid)} | {_cell_text(high)} | {gap_text} | {inverted_text} | "
            f"{low.mu_gap_p50:.2f} / {high.mu_gap_p50:.2f} |"
        )
    lines.extend(
        [
            "",
            "마지막 열은 같은 분위 안에서 low/high 쌍이 실제로 마주한 실력 차이의 중앙값입니다.",
            "두 값이 벌어져 있으면 그 칸은 아직 실력 차이가 덜 통제된 상태이므로, 거기서 나온",
            "역전은 sigma 효과로 읽으면 안 됩니다.",
            "",
            f"표본이 {MIN_CELL_SIZE}건 미만인 칸은 log loss가 노이즈에 휘둘리므로 수치를 숨기고",
            "표본 수만 적었습니다. 값이 없는 것은 그 구간의 예측이 나쁘다는 뜻이 아니라,",
            "판정에 쓸 만큼 사례가 모이지 않았다는 뜻입니다.",
            "",
            "## 3. 판정",
            "",
            "판정 규칙은 표를 보기 전에 고정했습니다.",
            "",
            "| 규칙 | 값 |",
            "| --- | --- |",
            f"| 역전으로 인정하는 최소 log loss 차이 | {INVERSION_MARGIN} |",
            f"| 신뢰할 수 있는 칸의 최소 표본 | {MIN_CELL_SIZE} |",
            f"| 버그로 판정하는 최소 역전 분위 수 | {BUG_VERDICT_MIN_QUANTILES} |",
            "",
            f"- 비교 가능한 분위: **{result.verdict.comparable_quantiles}** / {MU_QUANTILE_COUNT}",
            f"- 역전이 남은 분위: **{result.verdict.inverted_quantiles}**",
            "",
            f"최종 판정: **{result.verdict.label}**",
            "",
            result.verdict.reason,
            "",
            "### 통제 촘촘함에 따른 민감도",
            "",
            "5분위는 한 칸이 넓어 칸 안에 실력 차이가 여전히 섞입니다. 구간을 더 잘게 나눌수록",
            "역전이 줄어들면, 남은 역전은 실제 효과가 아니라 통제가 덜 된 흔적입니다.",
            "",
            "| `|mu 차이|` 구간 수 | 비교 가능한 구간 | 역전이 남은 구간 |",
            "| ---: | ---: | ---: |",
        ]
    )
    for row in result.sensitivity:
        lines.append(f"| {row.bins} | {row.comparable} | {row.inverted} |")
    lines.extend(
        [
            "",
            "## 4. 보조 확인 — `n_games`에 따른 sigma 단조 감소",
            "",
            f"![]({_relative(result.scatter_path, report_path)})",
            "",
            "| 출전 수 | n | sigma p10 | sigma p50 | sigma p90 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result.n_games_rows:
        lines.append(
            f"| {row.bucket} | {row.n:,} | {row.sigma_p10:.4f} | {row.sigma_p50:.4f} | {row.sigma_p90:.4f} |"
        )
    lines.extend(
        [
            "",
            f"출전 수와 sigma의 순위 상관: **{result.n_games_spearman:+.4f}** "
            "(음수면 출전이 늘수록 불확실성이 줄어드는 정상 방향)",
            "",
            "## 5. 보조 확인 — 휴지기에 따른 sigma 회복",
            "",
            "마지막 출전 이후 오래 쉰 선수는 실력을 다시 모르게 되므로 sigma가 커져야 합니다.",
            "커지지 않으면 오래 쉰 선수에게 과신한 확률을 매기게 됩니다.",
            "",
            "| 휴지기 | n | sigma p10 | sigma p50 | sigma p90 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in result.idle_rows:
        lines.append(
            f"| {row.bucket} | {row.n:,} | {row.sigma_p10:.4f} | {row.sigma_p50:.4f} | {row.sigma_p90:.4f} |"
        )
    lines.extend(
        [
            "",
            f"휴지기와 sigma의 순위 상관: **{result.idle_spearman:+.4f}** "
            "(0에 가까우면 쉬어도 불확실성이 되돌아오지 않는다는 뜻)",
            "",
        ]
    )
    text = "\n".join(lines)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return text


def _relative(target: Path, report_path: Path) -> str:
    base = report_path.parent
    if target.is_relative_to(base):
        return target.relative_to(base).as_posix()
    return target.as_posix()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-19 sigma 역전 원인을 진단합니다.")
    parser.add_argument("--ledger", default="out/ledger", help="레이스 레저 루트 디렉터리")
    parser.add_argument("--policy", default="conservative", choices=sorted(POLICIES.keys()), help="학습 정책")
    parser.add_argument("--rating-period", default="meet", choices=["meet", "month"], help="rating period")
    parser.add_argument("--engine", default="trueskill", choices=["glicko2", "trueskill"], help="엔진")
    parser.add_argument("--holdout-seasons", type=int, default=2, help="홀드아웃 시즌 수")
    parser.add_argument("--head2head-prob", type=float, default=0.65, help="B1 고정 확률")
    parser.add_argument("--out", default="out/sigma_diagnosis_report.md", help="리포트 출력 경로")
    parser.add_argument("--scatter", default="out/sigma_diagnosis/n_games_vs_sigma.svg", help="산점도 SVG 경로")
    parser.add_argument("--calibration-dir", default=None, help="캘리브레이션 SVG 출력 디렉터리 (기본값: 임시 디렉터리)")
    parser.add_argument("--dump-predictions", default=None, help="진단에 쓴 홀드아웃 예측 프레임을 parquet으로 저장할 경로")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report_path = Path(args.out).expanduser()
    with tempfile.TemporaryDirectory(prefix="sigma-diagnosis-") as scratch:
        calibration_dir = Path(args.calibration_dir).expanduser() if args.calibration_dir else Path(scratch)
        result = diagnose(
            policy=args.policy,
            ledger_root=Path(args.ledger).expanduser(),
            engine=args.engine,
            rating_period=args.rating_period,
            holdout_season_count=int(args.holdout_seasons),
            head2head_prob=float(args.head2head_prob),
            scatter_path=Path(args.scatter).expanduser(),
            calibration_dir=calibration_dir,
            dump_predictions=Path(args.dump_predictions).expanduser() if args.dump_predictions else None,
        )
    render_report(result, report_path)
    print(f"[ok] config={result.config}")
    print(f"[ok] verdict={result.verdict.label}")
    print(f"[ok] inverted_quantiles={result.verdict.inverted_quantiles}/{result.verdict.comparable_quantiles}")
    print(f"[ok] out={report_path}")
    print(f"[ok] scatter={result.scatter_path}")


if __name__ == "__main__":
    main()
