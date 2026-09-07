from __future__ import annotations

import argparse
import math
import multiprocessing
import random
import tempfile
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Mapping, Sequence, cast

import polars as pl

from rating.eval.backtest import EVALUATION_POLICY, _discover_policy_ledgers, _evaluate_config
from rating.eval.metrics import BootstrapInterval, bootstrap_log_loss_ci, clamp_probability
from rating.engine.types import RatingPeriod
from rating.ledger.schema import load_race_ledger
from rating.replay.registry import RatingRegistry
from rating.replay.snapshot import canonical_json, input_snapshot_id, run_id
from rating.replay.version import ALGORITHM_VERSION

Objective = Literal["log_loss"]
TrainingPolicy = Literal["conservative", "aggressive"]
SweepConfigName = Literal["baseline", "age_adjusted"]


@dataclass(frozen=True)
class SweepCandidate:
    axis: str
    tau: float
    sigma0: float
    beta_ratio: float
    rating_period: RatingPeriod
    policy: TrainingPolicy
    final_round_weight: float

    @property
    def beta(self) -> float:
        return self.sigma0 * self.beta_ratio

    def params(self) -> dict[str, object]:
        return {
            "beta": self.beta,
            "beta_ratio": self.beta_ratio,
            "final_round_weight": self.final_round_weight,
            "policy": self.policy,
            "rating_period": self.rating_period,
            "sigma0": self.sigma0,
            "tau": self.tau,
        }

    @property
    def key(self) -> str:
        return canonical_json(self.params())


@dataclass(frozen=True)
class ParamSpace:
    tau: tuple[float, ...]
    sigma0: tuple[float, ...]
    beta_ratio: tuple[float, ...]
    rating_period: tuple[RatingPeriod, ...]
    policy: tuple[TrainingPolicy, ...]
    final_round_weight: tuple[float, ...]
    defaults: SweepCandidate
    ledger_root: Path
    registry_root: Path
    holdout_seasons: int = 2
    bootstrap_resamples: int = 1000
    bootstrap_seed: int = 20260907
    config_name: SweepConfigName = "baseline"
    head2head_prob: float = 0.65

    @classmethod
    def from_toml(
        cls,
        path: Path,
        *,
        ledger_root: Path | None = None,
        registry_root: Path | None = None,
    ) -> "ParamSpace":
        with path.expanduser().open("rb") as handle:
            payload = tomllib.load(handle)
        sweep = _table(payload, "sweep")
        defaults = _table(payload, "defaults")
        axes = _table(payload, "axes")
        config_name = cast(SweepConfigName, _choice(sweep, "config", {"baseline", "age_adjusted"}, default="baseline"))
        candidate = SweepCandidate(
            axis="default",
            tau=_positive_float(defaults, "tau"),
            sigma0=_positive_float(defaults, "sigma0"),
            beta_ratio=_positive_float(defaults, "beta_ratio"),
            rating_period=cast(RatingPeriod, _choice(defaults, "rating_period", {"meet", "month"})),
            policy=cast(TrainingPolicy, _choice(defaults, "policy", {"conservative", "aggressive"})),
            final_round_weight=_positive_float(defaults, "final_round_weight"),
        )
        return cls(
            tau=_float_axis(axes, "tau"),
            sigma0=_float_axis(axes, "sigma0"),
            beta_ratio=_float_axis(axes, "beta_ratio"),
            rating_period=cast(tuple[RatingPeriod, ...], _string_axis(axes, "rating_period", {"meet", "month"})),
            policy=cast(tuple[TrainingPolicy, ...], _string_axis(axes, "policy", {"conservative", "aggressive"})),
            final_round_weight=_float_axis(axes, "final_round_weight"),
            defaults=candidate,
            ledger_root=ledger_root or Path(str(sweep.get("ledger_root", "out/ledger_sweep_policies"))),
            registry_root=registry_root or Path(str(sweep.get("registry_root", "out/rating_runs"))),
            holdout_seasons=_positive_int(sweep, "holdout_seasons", 2),
            bootstrap_resamples=_positive_int(sweep, "bootstrap_resamples", 1000),
            bootstrap_seed=_integer(sweep, "bootstrap_seed", 20260907),
            config_name=config_name,
            head2head_prob=_positive_float(sweep, "head2head_prob", default=0.65),
        )

    def candidates(self) -> tuple[SweepCandidate, ...]:
        values: dict[str, Sequence[float | str]] = {
            "tau": self.tau,
            "sigma0": self.sigma0,
            "beta_ratio": self.beta_ratio,
            "rating_period": self.rating_period,
            "policy": self.policy,
            "final_round_weight": self.final_round_weight,
        }
        candidates = [self.defaults]
        for axis in sorted(values):
            for value in values[axis]:
                if axis == "tau":
                    candidates.append(replace(self.defaults, axis=axis, tau=float(value)))
                elif axis == "sigma0":
                    candidates.append(replace(self.defaults, axis=axis, sigma0=float(value)))
                elif axis == "beta_ratio":
                    candidates.append(replace(self.defaults, axis=axis, beta_ratio=float(value)))
                elif axis == "rating_period":
                    candidates.append(replace(self.defaults, axis=axis, rating_period=cast(RatingPeriod, value)))
                elif axis == "policy":
                    candidates.append(replace(self.defaults, axis=axis, policy=cast(TrainingPolicy, value)))
                else:
                    candidates.append(replace(self.defaults, axis=axis, final_round_weight=float(value)))
        deduped: dict[str, SweepCandidate] = {}
        for candidate in candidates:
            deduped.setdefault(candidate.key, candidate)
        return tuple(sorted(deduped.values(), key=lambda candidate: (candidate.axis, candidate.key)))


@dataclass(frozen=True)
class CandidateResult:
    candidate: SweepCandidate
    sweep_id: str
    log_loss: float
    accuracy: float
    brier: float
    ece: float
    interval: BootstrapInterval
    actuals: tuple[int, ...]
    probabilities: tuple[float, ...]
    groups: tuple[str, ...]

    @property
    def complexity(self) -> int:
        return 0 if self.candidate.axis == "default" else 1


@dataclass(frozen=True)
class FailedCandidate:
    candidate: SweepCandidate
    sweep_id: str
    error: str


@dataclass(frozen=True)
class SweepResult:
    results: tuple[CandidateResult, ...]
    failures: tuple[FailedCandidate, ...]
    selected: CandidateResult
    identifiable_axes: Mapping[str, bool]


def _table(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"[error] sweep TOML에 [{name}] 테이블이 필요합니다.")
    return value


def _positive_float(table: Mapping[str, object], name: str, *, default: float | None = None) -> float:
    raw = table.get(name, default)
    try:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError
        value = float(raw)
    except TypeError as error:
        raise ValueError(f"[error] {name}은(는) 양의 숫자여야 합니다.") from error
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"[error] {name}은(는) 양의 유한값이어야 합니다.")
    return value


def _positive_int(table: Mapping[str, object], name: str, default: int) -> int:
    value = _integer(table, name, default)
    if value < 1:
        raise ValueError(f"[error] {name}은(는) 1 이상이어야 합니다.")
    return value


def _integer(table: Mapping[str, object], name: str, default: int) -> int:
    value = table.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"[error] {name}은(는) 정수여야 합니다.")
    return value


def _choice(table: Mapping[str, object], name: str, allowed: set[str], *, default: str = "") -> str:
    value = table.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"[error] {name}은(는) 문자열이어야 합니다.")
    if value not in allowed:
        raise ValueError(f"[error] {name}의 허용값: {', '.join(sorted(allowed))}")
    return value


def _float_axis(table: Mapping[str, object], name: str) -> tuple[float, ...]:
    value = table.get(name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"[error] axes.{name}은(는) 비어 있지 않은 배열이어야 합니다.")
    try:
        parsed = tuple(
            float(item)
            for item in value
            if not isinstance(item, bool) and isinstance(item, (int, float))
        )
    except TypeError as error:
        raise ValueError(f"[error] axes.{name}에는 양의 유한값만 허용됩니다.") from error
    if len(parsed) != len(value) or any(not math.isfinite(item) or item <= 0.0 for item in parsed):
        raise ValueError(f"[error] axes.{name}에는 양의 유한값만 허용됩니다.")
    return tuple(sorted(set(parsed)))


def _string_axis(table: Mapping[str, object], name: str, allowed: set[str]) -> tuple[str, ...]:
    value = table.get(name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"[error] axes.{name}은(는) 비어 있지 않은 배열이어야 합니다.")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"[error] axes.{name}에는 문자열만 허용됩니다.")
    parsed = tuple(cast(str, item) for item in value)
    invalid = sorted(set(parsed).difference(allowed))
    if invalid:
        raise ValueError(f"[error] axes.{name}의 허용값: {', '.join(sorted(allowed))}")
    return tuple(sorted(set(parsed)))


def _sweep_id(candidate: SweepCandidate, input_id: str, space: ParamSpace) -> str:
    return run_id(
        algo_version=ALGORITHM_VERSION,
        engine_params=candidate.params(),
        calibrator_spec={
            "bootstrap_resamples": space.bootstrap_resamples,
            "bootstrap_seed": space.bootstrap_seed,
            "config": space.config_name,
            "holdout_seasons": space.holdout_seasons,
            "method": "platt",
        },
        input_id=input_id,
    )


def _copy_with_final_weight(source: Path, target: Path, weight: float) -> Path:
    if weight == 1.0:
        return source
    frame = load_race_ledger(source)
    weighted = frame.with_columns(
        pl.when(pl.col("round_class").is_in(["final", "final_b"]))
        .then(pl.lit(float(weight)))
        .otherwise(pl.col("weight"))
        .alias("weight")
    )
    output = target / "race_ledger" / "part.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    weighted.write_parquet(output)
    source_meta = source.parent / "athlete_meta.parquet"
    if source_meta.exists():
        (target / "athlete_meta.parquet").write_bytes(source_meta.read_bytes())
    return output.parent


def _worker(item: tuple[SweepCandidate, ParamSpace, str]) -> CandidateResult | FailedCandidate:
    candidate, space, sweep_id = item
    try:
        discovered = _discover_policy_ledgers(space.ledger_root)
        if candidate.policy not in discovered:
            raise FileNotFoundError(f"[error] 학습 정책 레저를 찾을 수 없습니다: {candidate.policy}")
        if EVALUATION_POLICY not in discovered:
            raise FileNotFoundError(f"[error] 고정 평가셋 레저를 찾을 수 없습니다: {EVALUATION_POLICY}")
        with tempfile.TemporaryDirectory(prefix=f"sweep-{sweep_id}-") as directory:
            temporary = Path(directory)
            ledger_path = _copy_with_final_weight(
                discovered[candidate.policy],
                temporary / "training",
                candidate.final_round_weight,
            )
            eval_path = _copy_with_final_weight(
                discovered[EVALUATION_POLICY],
                temporary / "evaluation",
                candidate.final_round_weight,
            )
            evaluated = _evaluate_config(
                config_name=space.config_name,
                policy=candidate.policy,
                ledger_path=ledger_path,
                eval_ledger_path=eval_path,
                engine="trueskill",
                rating_period=candidate.rating_period,
                holdout_season_count=space.holdout_seasons,
                head2head_prob=space.head2head_prob,
                calibration_dir=temporary / "calibration",
                tau=candidate.tau,
                trueskill_initial_sigma=candidate.sigma0,
                beta=candidate.beta,
            )
            metrics = evaluated.metrics_by_predictor["trueskill"]
            actuals = tuple(int(value) for value in metrics.predictions["actual"].to_list())
            probabilities = tuple(float(value) for value in metrics.predictions["probability"].to_list())
            groups = tuple(str(value) for value in metrics.predictions["race_id"].to_list())
            return CandidateResult(
                candidate=candidate,
                sweep_id=sweep_id,
                log_loss=metrics.log_loss,
                accuracy=metrics.accuracy,
                brier=metrics.brier,
                ece=metrics.ece,
                interval=bootstrap_log_loss_ci(
                    actuals,
                    probabilities,
                    groups,
                    resamples=space.bootstrap_resamples,
                    seed=space.bootstrap_seed,
                ),
                actuals=actuals,
                probabilities=probabilities,
                groups=groups,
            )
    except Exception as error:
        return FailedCandidate(candidate=candidate, sweep_id=sweep_id, error=str(error))


def _metrics_payload(result: CandidateResult) -> dict[str, object]:
    return {
        "accuracy": result.accuracy,
        "brier": result.brier,
        "ci_high": result.interval.high,
        "ci_low": result.interval.low,
        "ece": result.ece,
        "log_loss": result.log_loss,
        "sample_size": len(result.actuals),
    }


def _paired_difference_ci(
    candidate: CandidateResult,
    best: CandidateResult,
    *,
    resamples: int,
    seed: int,
) -> BootstrapInterval:
    if candidate.groups != best.groups or candidate.actuals != best.actuals:
        raise ValueError("[error] 후보 간 홀드아웃 예측 행이 일치하지 않습니다.")
    by_group: dict[str, list[tuple[float, float]]] = {}
    for actual, candidate_p, best_p, group in zip(
        candidate.actuals,
        candidate.probabilities,
        best.probabilities,
        candidate.groups,
    ):
        candidate_loss = -math.log(clamp_probability(candidate_p) if actual else 1.0 - clamp_probability(candidate_p))
        best_loss = -math.log(clamp_probability(best_p) if actual else 1.0 - clamp_probability(best_p))
        by_group.setdefault(group, []).append((candidate_loss, best_loss))
    blocks = [(sum(left for left, _ in values), sum(right for _, right in values), len(values)) for values in by_group.values()]
    point = candidate.log_loss - best.log_loss
    if not blocks:
        return BootstrapInterval(point=point, low=point, high=point, resamples=0)
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(resamples):
        candidate_total = 0.0
        best_total = 0.0
        count = 0
        for _ in range(len(blocks)):
            candidate_sum, best_sum, size = blocks[rng.randrange(len(blocks))]
            candidate_total += candidate_sum
            best_total += best_sum
            count += size
        estimates.append((candidate_total - best_total) / float(count))
    estimates.sort()
    return BootstrapInterval(
        point=point,
        low=estimates[int(0.025 * len(estimates))],
        high=estimates[min(len(estimates) - 1, int(0.975 * len(estimates)))],
        resamples=len(estimates),
    )


def _identifiability(results: Sequence[CandidateResult]) -> dict[str, bool]:
    default = next((result for result in results if result.candidate.axis == "default"), None)
    if default is None:
        raise ValueError("[error] 식별성 분석에는 기본 후보가 필요합니다.")
    outcome: dict[str, bool] = {}
    for axis in sorted({result.candidate.axis for result in results if result.candidate.axis != "default"}):
        rows = [default, *(result for result in results if result.candidate.axis == axis)]
        spread = max(result.log_loss for result in rows) - min(result.log_loss for result in rows)
        ci_width = max(result.interval.high - result.interval.low for result in rows)
        outcome[axis] = spread >= ci_width
    return outcome


def _select(results: Sequence[CandidateResult], space: ParamSpace, identifiable_axes: Mapping[str, bool]) -> CandidateResult:
    best = min(results, key=lambda result: (result.log_loss, result.candidate.key))
    tied: list[CandidateResult] = []
    for result in results:
        interval = _paired_difference_ci(
            result,
            best,
            resamples=space.bootstrap_resamples,
            seed=space.bootstrap_seed,
        )
        if interval.low <= 0.0 <= interval.high:
            tied.append(result)
    usable = [
        result
        for result in tied
        if result.candidate.axis == "default" or identifiable_axes.get(result.candidate.axis, False)
    ]
    return min(usable or tied, key=lambda result: (result.complexity, result.candidate.key))


def run_sweep(space: ParamSpace, n_workers: int, objective: str = "log_loss") -> SweepResult:
    if objective != "log_loss":
        raise ValueError("[error] 현재 지원하는 목적함수는 log_loss뿐입니다.")
    if n_workers < 1:
        raise ValueError("[error] n_workers는 1 이상이어야 합니다.")
    discovered = _discover_policy_ledgers(space.ledger_root)
    if EVALUATION_POLICY not in discovered:
        raise FileNotFoundError(f"[error] 고정 평가셋 레저를 찾을 수 없습니다: {EVALUATION_POLICY}")
    input_id = input_snapshot_id(space.ledger_root)
    registry = RatingRegistry(space.registry_root)
    queued = [(candidate, _sweep_id(candidate, input_id, space)) for candidate in space.candidates()]
    for candidate, sweep_id in queued:
        registry.begin_sweep(sweep_id=sweep_id, params=candidate.params(), input_snapshot_id=input_id)

    items = [(candidate, space, sweep_id) for candidate, sweep_id in queued]
    try:
        if n_workers == 1:
            outcomes = [_worker(item) for item in items]
        else:
            with multiprocessing.get_context("spawn").Pool(processes=n_workers) as pool:
                outcomes = pool.map(_worker, items)
    except Exception as error:
        for _, sweep_id in queued:
            current = registry.get_sweep_run(sweep_id, include_incomplete=True)
            if current is not None and current.status == "running":
                registry.fail_sweep(sweep_id, error)
        raise

    results: list[CandidateResult] = []
    failures: list[FailedCandidate] = []
    for outcome in outcomes:
        current = registry.get_sweep_run(outcome.sweep_id, include_incomplete=True)
        if isinstance(outcome, FailedCandidate):
            failures.append(outcome)
            if current is not None and current.status == "running":
                registry.fail_sweep(outcome.sweep_id, outcome.error)
        else:
            results.append(outcome)
            if current is not None and current.status == "running":
                registry.complete_sweep(outcome.sweep_id, metrics=_metrics_payload(outcome))
    if failures:
        details = "; ".join(f"{failure.sweep_id}: {failure.error}" for failure in sorted(failures, key=lambda item: item.sweep_id))
        raise RuntimeError(f"[error] {len(failures)}개 스윕 후보가 실패했습니다: {details}")
    ordered = tuple(sorted(results, key=lambda result: result.candidate.key))
    identifiable_axes = _identifiability(ordered)
    return SweepResult(
        results=ordered,
        failures=(),
        selected=_select(ordered, space, identifiable_axes),
        identifiable_axes=identifiable_axes,
    )


def render_report(result: SweepResult, space: ParamSpace) -> str:
    ranked = sorted(result.results, key=lambda row: (row.log_loss, row.candidate.key))
    best = ranked[0]
    lines = [
        "# Parameter sweep results",
        "",
        "각 후보는 같은 마지막 2시즌 평가 구간에서, 평가 구간 이전 데이터만으로 새 Platt 보정기를 적합했습니다.",
        "점수 차이의 신뢰구간이 0을 포함하면 차이를 노이즈와 구분할 수 없어 더 단순한 설정을 고릅니다.",
        "",
        "## 결과",
        "",
        "| axis | tau | sigma0 | beta | period | policy | final weight | log loss | 95% CI | accuracy | ECE | registry |",
        "| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in result.results:
        candidate = row.candidate
        lines.append(
            f"| {candidate.axis} | {candidate.tau:.4f} | {candidate.sigma0:.3f} | {candidate.beta:.3f} | "
            f"{candidate.rating_period} | {candidate.policy} | {candidate.final_round_weight:.2f} | "
            f"{row.log_loss:.5f} | {row.interval.low:.5f}–{row.interval.high:.5f} | {row.accuracy:.4f} | "
            f"{row.ece:.5f} | `{row.sweep_id}` |"
        )
    lines.extend(
        [
            "",
            "## 최고 후보와의 차이",
            "",
            "같은 레이스를 함께 다시 뽑는 짝지은 부트스트랩으로 최고 점추정 후보와의 로그손실 차이를 계산했습니다.",
            "",
            "| axis | log loss difference | 95% CI | distinguishable |",
            "| --- | ---: | --- | --- |",
        ]
    )
    for row in result.results:
        difference = _paired_difference_ci(
            row,
            best,
            resamples=space.bootstrap_resamples,
            seed=space.bootstrap_seed,
        )
        distinguishable = "N" if difference.low <= 0.0 <= difference.high else "Y"
        lines.append(
            f"| {row.candidate.axis} | {difference.point:+.5f} | "
            f"{difference.low:+.5f}–{difference.high:+.5f} | {distinguishable} |"
        )
    lines.extend(["", "## 파라미터 민감도", "", "| axis | loss range | largest 95% CI width | conclusion |", "| --- | ---: | ---: | --- |"])
    for axis in sorted(result.identifiable_axes):
        default = next(row for row in result.results if row.candidate.axis == "default")
        rows = [default, *(row for row in result.results if row.candidate.axis == axis)]
        spread = max(row.log_loss for row in rows) - min(row.log_loss for row in rows)
        ci_width = max(row.interval.high - row.interval.low for row in rows)
        conclusion = "식별됨" if result.identifiable_axes[axis] else "식별 불가 — 기본값 고정"
        lines.append(f"| {axis} | {spread:.5f} | {ci_width:.5f} | {conclusion} |")
    lines.extend(
        [
            "",
            "## 선택",
            "",
            f"- 최소 점추정 후보: `{best.sweep_id}` (log loss {best.log_loss:.5f})",
            f"- 선택된 후보: `{result.selected.sweep_id}`",
            f"- 선택 규칙: 최저 로그손실 후보와의 레이스 단위 짝지은 부트스트랩 95% 구간이 0을 포함하면 동률로 보고, 기본값에서 바뀐 축 수가 가장 적은 후보를 선택합니다.",
            "- `rating_period`와 `policy`는 민감도 표의 결론을 따르며, 식별 불가면 기본값으로 고정합니다.",
            "",
        ]
    )
    return "\n".join(lines)


def write_production_config(path: Path, result: SweepResult) -> None:
    candidate = result.selected.candidate
    lines = [
        "[engine]",
        'name = "trueskill"',
        f'rating_period = "{candidate.rating_period}"',
        f"tau = {candidate.tau}",
        "initial_mu = 25.0",
        f"initial_sigma = {candidate.sigma0}",
        f"beta = {candidate.beta}",
        "draw_probability = 0.0",
        "convergence_tolerance = 0.0001",
        "ep_max_iterations = 10",
        "",
        "[ledger]",
        f'policy = "{candidate.policy}"',
        f"final_round_weight = {candidate.final_round_weight}",
        "",
        "[calibrator]",
        'method = "platt"',
        "",
        "[selection]",
        f'sweep_id = "{result.selected.sweep_id}"',
        'rule = "minimum log loss; statistically tied candidates use the simplest configuration"',
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_adr(path: Path, result: SweepResult) -> None:
    candidate = result.selected.candidate
    lines = [
        "# ADR 0014 — 파라미터 선택 (R-12)",
        "",
        "- 상태: Accepted",
        "",
        "## 결정",
        "",
        f"- TrueSkill 설정은 `tau={candidate.tau}`, `sigma0={candidate.sigma0}`, `beta={candidate.beta}`, "
        f"`rating_period={candidate.rating_period}`, `policy={candidate.policy}`, "
        f"`final_round_weight={candidate.final_round_weight}`로 고정합니다.",
        "- 최고 점추정 후보와 레이스 단위 짝지은 부트스트랩 95% 구간이 겹치면 성능 우열을 확정하지 않고, 더 단순한 설정(기본값에서 바뀐 축 수가 가장 적은 설정)을 선택합니다.",
        "- 격자 손실 폭이 같은 축의 부트스트랩 신뢰구간 폭보다 작으면 해당 축은 식별 불가로 보고 기본값을 유지합니다.",
        "",
        "## 근거",
        "",
        f"- 선택된 스윕 실행: `{result.selected.sweep_id}`",
        f"- 선택된 설정의 holdout log loss: **{result.selected.log_loss:.5f}** "
        f"(95% CI {result.selected.interval.low:.5f}–{result.selected.interval.high:.5f})",
        "- 각 설정은 마지막 2시즌 홀드아웃을 보기 전에 적합된 독립 Platt 보정기를 사용했습니다.",
        "- 반복 탐색은 홀드아웃 자체에 과적합될 수 있으므로, 시즌 단위로만 재검토하고 중요한 변경은 미사용 검증 시즌에서 다시 확인합니다.",
        "",
        "## 식별성",
        "",
    ]
    for axis in sorted(result.identifiable_axes):
        lines.append(f"- `{axis}`: {'식별됨' if result.identifiable_axes[axis] else '식별 불가, 기본값 고정'}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="결정적 TrueSkill 파라미터 스윕")
    parser.add_argument("--space", default="configs/sweep_space.toml", help="스윕 공간 TOML 경로")
    parser.add_argument("--ledger", help="정책별 race_ledger 루트")
    parser.add_argument("--registry-root", help="스윕 실행 레지스트리 루트")
    parser.add_argument("--workers", type=int, help="워커 수 (기본 CPU 코어 수 - 1)")
    parser.add_argument("--out", default="out/sweep_results.md", help="결과 보고서 경로")
    parser.add_argument("--production-out", default="configs/production.toml", help="선택 설정 TOML 경로")
    parser.add_argument("--adr-out", default="docs/adr/0014-parameter-selection.md", help="결정 ADR 경로")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    space = ParamSpace.from_toml(
        Path(args.space),
        ledger_root=Path(args.ledger).expanduser() if args.ledger else None,
        registry_root=Path(args.registry_root).expanduser() if args.registry_root else None,
    )
    workers = args.workers if args.workers is not None else max((multiprocessing.cpu_count() or 1) - 1, 1)
    result = run_sweep(space, workers)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(result, space), encoding="utf-8")
    write_production_config(Path(args.production_out).expanduser(), result)
    write_adr(Path(args.adr_out).expanduser(), result)
    print(f"[ok] candidates={len(result.results)}")
    print(f"[ok] selected={result.selected.sweep_id}")
    print(f"[ok] out={out}")


if __name__ == "__main__":
    main()
