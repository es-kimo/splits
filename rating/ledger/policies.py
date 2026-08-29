from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PenaltyPolicy = Literal["exclude", "last_place"]
DnfPolicy = Literal["exclude", "loss_to_finishers"]
AdvancedPolicy = Literal["exclude", "keep"]

ROUND_HEAT = "heat"
ROUND_QUARTERFINAL = "quarterfinal"
ROUND_SEMIFINAL = "semifinal"
ROUND_FINAL = "final"
ROUND_FINAL_B = "final_b"
ROUND_OTHER = "other"


@dataclass(frozen=True)
class ExtractionPolicy:
    penalty: PenaltyPolicy
    dnf: DnfPolicy
    advanced: AdvancedPolicy
    round_weights: dict[str, float]
    include_rounds: frozenset[str]
    min_season: int = 2013
    exclude_hobby_divisions: bool = True


_BASE_WEIGHTS = {
    ROUND_HEAT: 1.0,
    ROUND_QUARTERFINAL: 1.0,
    ROUND_SEMIFINAL: 1.0,
    ROUND_FINAL: 1.0,
    ROUND_FINAL_B: 1.0,
    ROUND_OTHER: 1.0,
}

CONSERVATIVE = ExtractionPolicy(
    penalty="exclude",
    dnf="exclude",
    advanced="exclude",
    round_weights=dict(_BASE_WEIGHTS),
    include_rounds=frozenset({ROUND_HEAT, ROUND_QUARTERFINAL, ROUND_SEMIFINAL, ROUND_FINAL, ROUND_FINAL_B}),
)

AGGRESSIVE = ExtractionPolicy(
    penalty="last_place",
    dnf="loss_to_finishers",
    advanced="keep",
    round_weights=dict(_BASE_WEIGHTS),
    include_rounds=frozenset(
        {ROUND_HEAT, ROUND_QUARTERFINAL, ROUND_SEMIFINAL, ROUND_FINAL, ROUND_FINAL_B, ROUND_OTHER}
    ),
)

PLACE_ONLY = ExtractionPolicy(
    penalty="last_place",
    dnf="exclude",
    advanced="keep",
    round_weights=dict(_BASE_WEIGHTS),
    include_rounds=frozenset({ROUND_FINAL, ROUND_FINAL_B}),
)

POLICIES: dict[str, ExtractionPolicy] = {
    "conservative": CONSERVATIVE,
    "aggressive": AGGRESSIVE,
    "place_only": PLACE_ONLY,
}


def get_policy(name: str) -> ExtractionPolicy:
    key = (name or "").strip().lower()
    if key not in POLICIES:
        options = ", ".join(sorted(POLICIES))
        raise ValueError(f"[error] 알 수 없는 정책입니다: {name!r}. 사용 가능: {options}")
    return POLICIES[key]

