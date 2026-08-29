from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Sequence


def _clamp_probability(value: float, *, eps: float = 1e-6) -> float:
    return min(max(float(value), eps), 1.0 - eps)


@dataclass(frozen=True)
class Calibrator:
    method: str
    slope: float
    intercept: float
    sample_size: int
    fit_fold: str
    fit_iterations: int
    fit_learning_rate: float

    def apply(self, probability: float) -> float:
        p = _clamp_probability(probability)
        logit = math.log(p / (1.0 - p))
        return _clamp_probability(1.0 / (1.0 + math.exp(-(self.slope * logit + self.intercept))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "slope": float(self.slope),
            "intercept": float(self.intercept),
            "sample_size": int(self.sample_size),
            "fit_fold": self.fit_fold,
            "fit_iterations": int(self.fit_iterations),
            "fit_learning_rate": float(self.fit_learning_rate),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "Calibrator":
        method = str(payload.get("method", "")).strip()
        if method != "platt":
            raise ValueError(f"[error] 지원하지 않는 calibrator method입니다: {method!r}")
        return Calibrator(
            method=method,
            slope=float(payload["slope"]),
            intercept=float(payload["intercept"]),
            sample_size=int(payload["sample_size"]),
            fit_fold=str(payload["fit_fold"]),
            fit_iterations=int(payload["fit_iterations"]),
            fit_learning_rate=float(payload["fit_learning_rate"]),
        )

    @staticmethod
    def from_json(raw: str) -> "Calibrator":
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("[error] calibrator JSON은 객체여야 합니다.")
        return Calibrator.from_dict(payload)

    @staticmethod
    def identity() -> "Calibrator":
        return Calibrator(
            method="platt",
            slope=1.0,
            intercept=0.0,
            sample_size=0,
            fit_fold="identity",
            fit_iterations=0,
            fit_learning_rate=0.0,
        )


IDENTITY_CALIBRATOR = Calibrator.identity()


def fit(
    probabilities: Sequence[float],
    labels: Sequence[int],
    *,
    fold_id: str,
    iterations: int = 200,
    learning_rate: float = 0.5,
) -> Calibrator:
    if len(probabilities) != len(labels):
        raise ValueError("[error] probabilities/labels 길이가 일치하지 않습니다.")
    if not probabilities:
        raise ValueError("[error] calibrator 적합 입력이 비어 있습니다.")
    if not fold_id.strip():
        raise ValueError("[error] fold_id는 비어 있을 수 없습니다.")
    logits = []
    for probability in probabilities:
        p = _clamp_probability(probability)
        logits.append(math.log(p / (1.0 - p)))
    targets = [int(value) for value in labels]
    size = float(len(targets))

    slope, intercept = 1.0, 0.0
    for _ in range(iterations):
        grad_slope = 0.0
        grad_intercept = 0.0
        for logit, label in zip(logits, targets):
            predicted = 1.0 / (1.0 + math.exp(-max(min(slope * logit + intercept, 60.0), -60.0)))
            error = predicted - label
            grad_slope += error * logit
            grad_intercept += error
        slope -= learning_rate * (grad_slope / size)
        intercept -= learning_rate * (grad_intercept / size)
    return Calibrator(
        method="platt",
        slope=slope,
        intercept=intercept,
        sample_size=len(targets),
        fit_fold=fold_id,
        fit_iterations=int(iterations),
        fit_learning_rate=float(learning_rate),
    )


def apply(probability: float, calibrator: Calibrator) -> float:
    return calibrator.apply(probability)
