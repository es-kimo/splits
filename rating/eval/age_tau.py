from __future__ import annotations

import argparse
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rating.ledger.policies import POLICIES

from .backtest import AGE_TAU_PROFILES, ConfigResult, EVALUATION_POLICY, _discover_policy_ledgers, _evaluate_config
from .metrics import BootstrapInterval, bootstrap_log_loss_ci


@dataclass(frozen=True)
class TauProfileResult:
    name: str
    tau_by_age_band: dict[str, float]
    log_loss: float
    accuracy: float
    interval: BootstrapInterval


def _profile_order() -> list[str]:
    return ["global", *sorted(name for name in AGE_TAU_PROFILES if name != "global")]


def _to_profile_result(name: str, result: ConfigResult) -> TauProfileResult:
    metrics = result.metrics_by_predictor["trueskill"]
    predictions = metrics.predictions
    return TauProfileResult(
        name=name,
        tau_by_age_band=dict(AGE_TAU_PROFILES[name]),
        log_loss=metrics.log_loss,
        accuracy=metrics.accuracy,
        interval=bootstrap_log_loss_ci(
            predictions["actual"].to_list(),
            predictions["probability"].to_list(),
            predictions["race_id"].to_list(),
            resamples=1000,
        ),
    )


def evaluate_age_tau_profiles(
    *,
    ledger_root: Path,
    policy: str,
    holdout_seasons: int,
    head2head_prob: float,
) -> list[TauProfileResult]:
    discovered = _discover_policy_ledgers(ledger_root)
    if policy not in discovered:
        raise FileNotFoundError(f"[error] 학습 정책 레저를 찾을 수 없습니다: {policy}")
    if EVALUATION_POLICY not in discovered:
        raise FileNotFoundError(f"[error] 고정 평가셋 레저를 찾을 수 없습니다: {EVALUATION_POLICY}")

    rows: list[TauProfileResult] = []
    with tempfile.TemporaryDirectory(prefix="age-tau-calibration-") as temp_dir:
        calibration_dir = Path(temp_dir)
        for name in _profile_order():
            result = _evaluate_config(
                config_name="age_adjusted",
                policy=policy,
                ledger_path=discovered[policy],
                eval_ledger_path=discovered[EVALUATION_POLICY],
                engine="trueskill",
                rating_period="meet",
                holdout_season_count=holdout_seasons,
                head2head_prob=head2head_prob,
                calibration_dir=calibration_dir,
                tau_by_age_band=AGE_TAU_PROFILES[name],
            )
            rows.append(_to_profile_result(name, result))
    return rows


def render_report(rows: list[TauProfileResult]) -> str:
    if not rows:
        raise ValueError("[error] 연령별 tau 결과가 없습니다.")
    global_result = next((row for row in rows if row.name == "global"), None)
    if global_result is None:
        raise ValueError("[error] global tau 기준 결과가 없습니다.")
    best = min(rows, key=lambda row: row.log_loss)
    separated = [
        row
        for row in rows
        if row.name != "global" and not row.interval.overlaps(global_result.interval)
    ]
    verdict = "채택" if separated else "기각 (식별 불가)"

    lines = [
        "# 연령별 tau 식별성 리포트",
        "",
        "## 사전 고정 후보",
        "",
        "- 기준은 전역 `tau=0.50`입니다.",
        "- 연령 구간은 `<=12`, `13-15`, `16+`으로 고정했습니다.",
        "- 각 후보는 한 구간만 `0.25` 또는 `1.00`으로 바꾸고, 나머지는 `0.50`으로 유지했습니다.",
        "- 평가셋은 conservative 정책의 마지막 2시즌이며, 신인 사전분포와 Platt 보정 절차는 모든 후보에서 동일합니다.",
        "",
        "## 결과",
        "",
        "| profile | tau <=12 | tau 13-15 | tau 16+ | log_loss | 전역 대비 | accuracy | 95% CI | 전역 CI와 겹침 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        delta = row.log_loss - global_result.log_loss
        overlap = "기준" if row.name == "global" else ("Y" if row.interval.overlaps(global_result.interval) else "N")
        lines.append(
            f"| {row.name} | {row.tau_by_age_band['<=12']:.2f} | {row.tau_by_age_band['13-15']:.2f} | "
            f"{row.tau_by_age_band['16+']:.2f} | {row.log_loss:.5f} | {delta:+.5f} | {row.accuracy:.4f} | "
            f"{row.interval.low:.5f}–{row.interval.high:.5f} | {overlap} |"
        )

    lines.extend(
        [
            "",
            "## 판정",
            "",
            f"- 최고 점추정 후보: `{best.name}` (log loss {best.log_loss:.5f})",
            f"- 최종 판정: **{verdict}**",
        ]
    )
    if separated:
        names = ", ".join(f"`{row.name}`" for row in separated)
        lines.append(f"- 전역 tau와 95% 구간이 분리된 후보: {names}")
    else:
        lines.append(
            "- 모든 후보의 95% 구간이 전역 tau 기준과 겹칩니다. 점추정 차이는 재현 가능한 연령별 파라미터로 승격할 근거가 아닙니다."
        )
    lines.extend(
        [
            "",
            "## 후속 결정",
            "",
            "- `tau(age)`는 프로덕션 설정에 넣지 않고 전역 tau를 유지합니다.",
            "- 드리프트 항은 `tau(age)` 채택 시에만 시도한다는 사전 조건이 충족되지 않아 적용하지 않습니다.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-06 연령 3구간 tau 식별성 실험")
    parser.add_argument("--ledger", default="out/ledger_age_policies", help="정책별 race_ledger 루트")
    parser.add_argument("--policy", default="aggressive", choices=sorted(POLICIES), help="학습 정책")
    parser.add_argument("--holdout-seasons", type=int, default=2, help="홀드아웃 시즌 수")
    parser.add_argument("--head2head-prob", type=float, default=0.65, help="B1 고정 확률")
    parser.add_argument("--out", default="out/age_tau_report.md", help="리포트 출력 경로")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    rows = evaluate_age_tau_profiles(
        ledger_root=Path(args.ledger).expanduser(),
        policy=args.policy,
        holdout_seasons=int(args.holdout_seasons),
        head2head_prob=float(args.head2head_prob),
    )
    output = Path(args.out).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(rows), encoding="utf-8")
    print(f"[ok] out={output}")
    print(f"[ok] profiles={len(rows)}")


if __name__ == "__main__":
    main()
