"""백테스트 산출물이 물리적으로 불가능한 상태를 통과하지 못하게 막는 검사.

R-05 1차 실행은 다음을 모두 담은 채로 `Accepted` ADR을 만들어냈습니다.

- 홀드아웃 비교의 84.6%가 실제로 붙은 적 없는 선수 쌍 (부문 병합)
- ECE가 캘리브레이션이 아니라 `1 - mean(p)` 항등식
- B2/B3가 동전 던지기보다 나쁨

셋 다 리포트 표에는 드러나 있었지만 판정 로직이 보지 않았습니다. 여기 있는
검사는 그 셋을 각각 실행 중단으로 바꿉니다.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .backtest import ConfigResult

LN2 = math.log(2.0)

# 기준선이 무작위보다 이만큼 넘게 나쁘면 기준선 구현 결함으로 봅니다.
BASELINE_TOLERANCE = 1.05
# 마지막 N시즌 홀드아웃이 전체 비교에서 차지할 수 있는 상한.
MAX_HOLDOUT_RATIO = 0.25
# log loss가 정확도의 이진 엔트로피보다 이만큼 넘게 낮으면 지표가 깨진 것입니다.
ENTROPY_SLACK = 0.1


def binary_entropy(p: float) -> float:
    bounded = min(max(float(p), 1e-9), 1.0 - 1e-9)
    return -(bounded * math.log(bounded) + (1.0 - bounded) * math.log(1.0 - bounded))


def assert_harness_invariants(result: "ConfigResult") -> None:
    tag = f"{result.policy}/{result.rating_period}/{result.engine}"
    metrics = result.metrics_by_predictor

    # 1. 동전 던지기 검산 — 하네스의 라벨/확률 경로 자체가 살아 있는지.
    b0 = metrics["B0"].log_loss
    if abs(b0 - LN2) > 1e-3:
        raise ValueError(
            f"[error] {tag}: B0(동전 던지기) log loss={b0:.5f}, 기대값 {LN2:.5f}. "
            "라벨 구성 또는 확률 기록 경로가 잘못됐습니다."
        )

    # 2. 기준선이 무작위보다 나쁘면 그건 발견이 아니라 구현 결함입니다.
    for name in ("B1", "B2", "B3"):
        if name not in metrics:
            continue
        loss = metrics[name].log_loss
        if loss > b0 * BASELINE_TOLERANCE:
            raise ValueError(
                f"[error] {tag}: {name} log loss={loss:.5f}가 B0×{BASELINE_TOLERANCE} "
                f"({b0 * BASELINE_TOLERANCE:.5f})를 넘습니다. 확률 스케일이 포화했을 가능성이 높습니다."
            )

    # 3. 홀드아웃 크기 상한 — 시즌 필터가 실제로 걸렸는지.
    holdout_n = result.holdout_comparison_count
    total_n = result.total_comparison_count
    if total_n > 0 and holdout_n > total_n * MAX_HOLDOUT_RATIO:
        raise ValueError(
            f"[error] {tag}: 홀드아웃 비교 {holdout_n:,} / 전체 {total_n:,} = "
            f"{holdout_n / total_n:.1%}로 상한 {MAX_HOLDOUT_RATIO:.0%}를 넘습니다. "
            f"마지막 {len(result.holdout_seasons)}시즌 홀드아웃으로는 불가능한 비율입니다."
        )

    model = metrics[result.engine]

    # 4. log loss가 정확도가 허용하는 하한보다 낮을 수 없습니다.
    floor = binary_entropy(model.accuracy) - ENTROPY_SLACK
    if model.log_loss < floor:
        raise ValueError(
            f"[error] {tag}: log loss={model.log_loss:.5f}가 정확도 {model.accuracy:.4f}의 "
            f"엔트로피 하한 {floor:.5f}보다 낮습니다. 두 지표가 서로 다른 데이터를 보고 있습니다."
        )

    # 5. ECE가 1-mean(p) 항등식이면 라벨이 한쪽으로 쏠려 캘리브레이션이 측정되지
    #    않고 있습니다. log loss는 정상이라 4번으로는 잡히지 않습니다.
    mean_probability = float(model.predictions["probability"].mean())
    if abs(model.ece - (1.0 - mean_probability)) < 1e-6:
        raise ValueError(
            f"[error] {tag}: ECE={model.ece:.5f}가 1-mean(p)={1.0 - mean_probability:.5f}와 동일합니다. "
            "모든 라벨이 같은 값인 상태로 캘리브레이션을 재고 있습니다."
        )

    # 6. 방향 정규화가 실제로 걸렸는지 — 라벨이 한쪽으로 쏠리면 개선율의 기준선이
    #    0.5가 아니게 되고, B0 accuracy가 100%로 나옵니다.
    label_rate = float(model.predictions["actual"].mean())
    if not 0.4 <= label_rate <= 0.6:
        raise ValueError(
            f"[error] {tag}: 라벨 평균={label_rate:.5f}로 0.4~0.6 범위를 벗어납니다. "
            "비교 방향 정규화가 동작하지 않았습니다."
        )
