"""R-16 국가대표 궤적 검증 리포트 생성기.

이 모듈은 두 종류의 추정치를 **타입으로 분리**합니다.

- :class:`SmoothedEstimates` — 전체 데이터로 되돌아본 최선의 추정. 궤적 표시에만 씁니다.
- :class:`FilteredEstimates` — 그 시점까지의 정보만으로 만든 추정. 예측력 평가에만 씁니다.

스무딩 값으로 예측력을 재면 미래 정보가 과거로 새어 들어옵니다. 그래서 예측력 함수는
필터 추정치 외에는 받지 않고, 잘못된 타입이 들어오면 계산 대신 오류를 냅니다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_env import load_local_env
from rating.engine.age import attach_age, build_baseline_wide, fit_age_baseline
from rating.eval.metrics import BootstrapInterval, auc_score, bootstrap_auc_ci, wilson_interval
from rating.ledger.schema import load_race_ledger
from rating.replay.registry import DEFAULT_REGISTRY_ROOT, RatingRegistry

# 일반 선수 집단을 세는 칸은 10명 미만이면 수치를 숨깁니다(사이트 공개 기준과 동일).
MIN_COHORT_SIZE = 10
# 국가대표 표본이 3명 미만인 연령은 판정하지 않습니다.
MIN_POSITIVES = 3
# 누적 경기 수가 이만큼 쌓이기 전의 추정치로는 판정하지 않습니다(R-05 저경기 구간 정확도 근거).
MIN_MEAN_GAMES = 6.0
# 이 값 아래면 "예측력 약함"으로 서술합니다.
AUC_WEAK_THRESHOLD = 0.7
# 초5~6에 해당하는 연나이입니다.
DEFAULT_ELEMENTARY_AGES = (11, 12)
DEFAULT_TOP_SHARES = (0.10, 0.20, 0.30)
# 이 연령까지의 궤적을 리포트에 싣습니다.
DEFAULT_AGE_RANGE = (9, 22)
# 고등 단계 진입 전후를 나누는 기준 연나이입니다.
HIGH_SCHOOL_AGE = 16
COLLEGE_AGE = 19

DETERMINISTIC_PHRASES = (
    "될 것이다",
    "안 될 것이다",
    "될 수밖에",
    "보장",
    "확실히",
    "틀림없",
    "결정된다",
    "결정됩니다",
    "필연",
    "예정되어 있습니다",
)

_ESTIMATE_SCHEMA = {
    "athlete_id": pl.Utf8,
    "age": pl.Int64,
    "sex": pl.Utf8,
    "birth_year": pl.Int64,
    "z": pl.Float64,
    "z_sigma": pl.Float64,
    "n_games": pl.Int64,
    "top_share": pl.Float64,
    "cohort_size": pl.Int64,
}


@dataclass(frozen=True)
class FilteredEstimates:
    """그 시점까지의 정보만 반영한 연령별 추정치입니다. 예측력 평가 전용입니다."""

    frame: pl.DataFrame
    label: str = "필터 추정치"


@dataclass(frozen=True)
class SmoothedEstimates:
    """전체 기간을 되돌아본 연령별 추정치입니다. 궤적 표시 전용입니다."""

    frame: pl.DataFrame
    label: str = "스무딩 추정치"


@dataclass(frozen=True)
class AgeAucRow:
    age: int
    cohort_size: int
    positives: int
    cohort_mean_games: float
    national_mean_games: float
    auc: BootstrapInterval | None
    verdict: str
    reason: str


@dataclass(frozen=True)
class RateRow:
    share: float
    top_size: int
    national_total: int
    national_in_top: int
    reach_rate: tuple[float, float, float] | None
    top_given_national: tuple[float, float, float] | None
    reason: str


@dataclass(frozen=True)
class AttritionRow:
    last_age: int
    count: int
    share: float


@dataclass(frozen=True)
class AttritionSummary:
    top_size: int
    reached_national: int
    still_active: int
    left_before_high_school: int
    left_before_college: int
    rows: tuple[AttritionRow, ...]
    reason: str


@dataclass(frozen=True)
class TrajectoryPoint:
    age: int
    z: float
    z_sigma: float
    n_games: int


@dataclass(frozen=True)
class TrajectoryCase:
    label: str
    points: tuple[TrajectoryPoint, ...]


@dataclass(frozen=True)
class LateBloomerSummary:
    total: int
    late_risers: int
    early_leaders: int
    no_elementary_record: int


def national_team_athlete_ids(public_figures: Path, salt: str) -> list[str]:
    """공인 국가대표 명단을 익명 선수 ID로 바꿉니다."""

    if not salt:
        raise ValueError("[error] 국가대표 식별에는 SPLITS_ANON_SALT가 필요합니다.")
    if not public_figures.is_file():
        raise FileNotFoundError(f"[error] 공개 선수 명단이 없습니다: {public_figures}")
    athlete_ids: list[str] = []
    with public_figures.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("상태", "").strip() != "active":
                continue
            if "국가대표" not in row.get("지정근거", ""):
                continue
            id_no = row.get("idNo", "").strip()
            if not id_no:
                raise ValueError("[error] 공개 선수 명단에 idNo가 비어 있습니다.")
            athlete_ids.append(hashlib.sha256(f"{id_no}{salt}".encode("utf-8")).hexdigest()[:12])
    if not athlete_ids:
        raise LookupError("[error] 활성 상태인 공개 국가대표가 없습니다.")
    return sorted(set(athlete_ids))


def build_age_estimates(snapshots: pl.DataFrame, athlete_meta: pl.DataFrame) -> pl.DataFrame:
    """스냅샷을 연령별 한 줄짜리 z-score 표로 바꿉니다.

    한 연령에 여러 스냅샷이 있으면 그 연령의 마지막 값을 씁니다. z는 같은 연령·성별
    집단의 중앙값과 사분위 폭으로 만든 기준선 대비 위치이며, 기준 표본이 10명 미만인
    연령·성별은 기준선을 만들지 않고 비워 둡니다.
    """

    if snapshots.is_empty():
        return pl.DataFrame(schema=_ESTIMATE_SCHEMA)

    prepared = snapshots.select(["athlete_id", "valid_date", "mu", "sigma", "n_games"])
    prepared = prepared.rename({"sigma": "phi"}).with_columns(pl.lit(0.0).alias("sigma"))
    joined = attach_age(prepared, athlete_meta)
    baseline = build_baseline_wide(fit_age_baseline(joined.select(["age", "sex", "mu"])))
    if baseline.is_empty():
        return pl.DataFrame(schema=_ESTIMATE_SCHEMA)

    joined = (
        joined.filter(pl.col("age").is_not_null() & (pl.col("sex") != ""))
        .join(baseline, on=["age", "sex"], how="inner")
        .filter(
            pl.col("baseline_mu").is_not_null()
            & pl.col("baseline_spread").is_not_null()
            & (pl.col("baseline_spread") > 0)
            & (pl.col("baseline_sample_size") >= MIN_COHORT_SIZE)
        )
        .with_columns(
            [
                ((pl.col("mu") - pl.col("baseline_mu")) / pl.col("baseline_spread")).alias("z"),
                (pl.col("phi") / pl.col("baseline_spread")).alias("z_sigma"),
            ]
        )
        .sort(["athlete_id", "age", "valid_date"])
        .group_by(["athlete_id", "age"])
        .last()
    )
    if joined.is_empty():
        return pl.DataFrame(schema=_ESTIMATE_SCHEMA)

    ranked = joined.with_columns(
        [
            (
                pl.col("z").rank(method="min", descending=True).over(["age", "sex"]) / pl.len().over(["age", "sex"])
            ).alias("top_share"),
            pl.len().over(["age", "sex"]).alias("cohort_size"),
        ]
    )
    return (
        ranked.select(
            [
                pl.col("athlete_id").cast(pl.Utf8),
                pl.col("age").cast(pl.Int64),
                pl.col("sex").cast(pl.Utf8),
                pl.col("birth_year").cast(pl.Int64),
                pl.col("z").cast(pl.Float64),
                pl.col("z_sigma").cast(pl.Float64),
                pl.col("n_games").cast(pl.Int64),
                pl.col("top_share").cast(pl.Float64),
                pl.col("cohort_size").cast(pl.Int64),
            ]
        )
        .sort(["age", "athlete_id"])
    )


def make_filtered_estimates(snapshots: pl.DataFrame, athlete_meta: pl.DataFrame) -> FilteredEstimates:
    return FilteredEstimates(frame=build_age_estimates(snapshots, athlete_meta))


def make_smoothed_estimates(snapshots: pl.DataFrame, athlete_meta: pl.DataFrame) -> SmoothedEstimates:
    return SmoothedEstimates(frame=build_age_estimates(snapshots, athlete_meta))


def _require_filtered(estimates: object) -> pl.DataFrame:
    if not isinstance(estimates, FilteredEstimates):
        raise TypeError(
            "[error] 예측력 평가에는 필터 추정치만 쓸 수 있습니다. "
            "스무딩 추정치는 미래 정보를 포함하므로 예측 성능을 부풀립니다."
        )
    return estimates.frame


def _require_smoothed(estimates: object) -> pl.DataFrame:
    if not isinstance(estimates, SmoothedEstimates):
        raise TypeError("[error] 궤적 표시에는 스무딩 추정치만 쓸 수 있습니다.")
    return estimates.frame


def restrict_to_cohort(frame: pl.DataFrame, birth_years: tuple[int, int]) -> pl.DataFrame:
    """국가대표와 같은 시기에 태어난 코호트만 남깁니다.

    최근에 태어난 선수는 아직 국가대표가 될 시간 자체가 없었습니다. 그 선수들을 분모에
    넣으면 도달률이 실제보다 낮게 나옵니다.
    """

    low, high = birth_years
    if low > high:
        raise ValueError("[error] 출생연도 범위가 뒤집혀 있습니다.")
    return frame.filter((pl.col("birth_year") >= low) & (pl.col("birth_year") <= high))


def cohort_birth_year_range(frame: pl.DataFrame, national_ids: Sequence[str]) -> tuple[int, int]:
    selected = frame.filter(pl.col("athlete_id").is_in(list(national_ids)))
    matched = selected.select(pl.col("athlete_id").n_unique()).item()
    if not isinstance(matched, int):
        raise TypeError("[error] 국가대표 매칭 수 계산에 실패했습니다.")
    if matched == 0:
        raise LookupError(
            "[error] 공개 국가대표가 현재 레이팅 선수와 0건 매칭되었습니다. "
            "익명 선수 식별키 형식이 맞는 입력으로 레저/레이팅을 다시 생성하세요 "
            "(예: data/records_anon.csv 기준 실행)."
        )
    years = [int(value) for value in selected["birth_year"].drop_nulls().to_list()]
    if not years:
        raise LookupError(
            "[error] 국가대표는 매칭됐지만 출생연도 정보가 없습니다. "
            "출생연도가 포함된 athlete_meta로 다시 생성하세요."
        )
    return (min(years), max(years))


def age_auc_rows(
    estimates: object,
    national_ids: Sequence[str],
    *,
    ages: Sequence[int],
    resamples: int = 1000,
    seed: int = 20260907,
) -> list[AgeAucRow]:
    """연령별로 그 시점 추정치가 국가대표 여부를 얼마나 갈라내는지 잽니다."""

    frame = _require_filtered(estimates)
    national = set(national_ids)
    rows: list[AgeAucRow] = []
    for age in ages:
        at_age = frame.filter(pl.col("age") == age)
        cohort_size = at_age.height
        labels = [1 if str(value) in national else 0 for value in at_age["athlete_id"].to_list()]
        scores = [float(value) for value in at_age["z"].to_list()]
        games = [int(value) for value in at_age["n_games"].to_list()]
        positives = sum(labels)
        cohort_mean_games = (sum(games) / float(len(games))) if games else 0.0
        national_games = [game for label, game in zip(labels, games) if label == 1]
        national_mean_games = (sum(national_games) / float(len(national_games))) if national_games else 0.0

        reason = _auc_gate_reason(
            cohort_size=cohort_size,
            positives=positives,
            cohort_mean_games=cohort_mean_games,
            national_mean_games=national_mean_games,
        )
        if reason:
            rows.append(
                AgeAucRow(
                    age=age,
                    cohort_size=cohort_size,
                    positives=positives,
                    cohort_mean_games=cohort_mean_games,
                    national_mean_games=national_mean_games,
                    auc=None,
                    verdict="판정 불가",
                    reason=reason,
                )
            )
            continue

        interval = bootstrap_auc_ci(labels, scores, resamples=resamples, seed=seed)
        rows.append(
            AgeAucRow(
                age=age,
                cohort_size=cohort_size,
                positives=positives,
                cohort_mean_games=cohort_mean_games,
                national_mean_games=national_mean_games,
                auc=interval,
                verdict=_auc_verdict(interval),
                reason="",
            )
        )
    return rows


def _auc_gate_reason(
    *,
    cohort_size: int,
    positives: int,
    cohort_mean_games: float,
    national_mean_games: float,
) -> str:
    if cohort_size < MIN_COHORT_SIZE:
        return f"비교 집단이 {MIN_COHORT_SIZE}명 미만입니다"
    if positives < MIN_POSITIVES:
        return f"이 연령에 기록이 남은 국가대표가 {MIN_POSITIVES}명 미만입니다"
    if min(cohort_mean_games, national_mean_games) < MIN_MEAN_GAMES:
        return f"평균 누적 경기 수가 {MIN_MEAN_GAMES:.0f}회 미만이라 추정치가 아직 불안정합니다"
    return ""


def _auc_verdict(interval: BootstrapInterval) -> str:
    if interval.low <= 0.5:
        return "예측력 약함 (구간이 0.5를 포함)"
    if interval.point < AUC_WEAK_THRESHOLD:
        return "예측력 약함"
    return "구분되는 경향 관측"


def first_signal_age(rows: Sequence[AgeAucRow]) -> tuple[int | None, str]:
    """신호가 처음 나타나는 연령을 고릅니다. 판정 조건을 못 채우면 연령을 고르지 않습니다."""

    for row in rows:
        if row.auc is None:
            continue
        if row.auc.point >= AUC_WEAK_THRESHOLD and row.auc.low > 0.5:
            return row.age, ""
    judgeable = [row for row in rows if row.auc is not None]
    if not judgeable:
        return None, "판정 조건을 채우는 연령이 없어 데이터 부족으로 판정 불가입니다"
    return None, "판정 가능한 연령에서 0.5를 넘는 구간이 관측되지 않았습니다"


def bidirectional_rows(
    estimates: object,
    national_ids: Sequence[str],
    *,
    ages: Sequence[int],
    shares: Sequence[float] = DEFAULT_TOP_SHARES,
) -> list[RateRow]:
    """같은 기준에서 두 방향 확률을 함께 냅니다.

    - P(국가대표 | 어릴 때 상위 X%) — 학부모가 실제로 알고 싶은 방향입니다.
    - P(어릴 때 상위 X% | 국가대표) — 흔히 보고되는 방향이며 훨씬 높게 나옵니다.
    """

    frame = _require_filtered(estimates)
    national = set(national_ids)
    at_ages = frame.filter(pl.col("age").is_in(list(ages)))
    # 한 선수가 초5·초6에 모두 있으면 더 좋았던 쪽(작은 top_share)을 그 선수의 유년기 위치로 봅니다.
    per_athlete = (
        at_ages.sort(["athlete_id", "top_share"])
        .group_by("athlete_id")
        .first()
        .select(["athlete_id", "top_share"])
    )
    national_total = per_athlete.filter(pl.col("athlete_id").is_in(list(national))).height

    rows: list[RateRow] = []
    for share in shares:
        top = per_athlete.filter(pl.col("top_share") <= share)
        top_size = top.height
        national_in_top = sum(1 for value in top["athlete_id"].to_list() if str(value) in national)
        if top_size < MIN_COHORT_SIZE:
            rows.append(
                RateRow(
                    share=share,
                    top_size=top_size,
                    national_total=national_total,
                    national_in_top=national_in_top,
                    reach_rate=None,
                    top_given_national=None,
                    reason=f"상위 {share:.0%} 집단이 {MIN_COHORT_SIZE}명 미만이라 비율을 내지 않습니다",
                )
            )
            continue
        reach_low, reach_high = wilson_interval(national_in_top, top_size)
        if national_total > 0:
            given_low, given_high = wilson_interval(national_in_top, national_total)
            given = (national_in_top / float(national_total), given_low, given_high)
        else:
            given = None
        rows.append(
            RateRow(
                share=share,
                top_size=top_size,
                national_total=national_total,
                national_in_top=national_in_top,
                reach_rate=(national_in_top / float(top_size), reach_low, reach_high),
                top_given_national=given,
                reason="" if given is not None else "이 연령대에 기록이 남은 국가대표가 없습니다",
            )
        )
    return rows


def attrition_summary(
    estimates: object,
    race_ledger: pl.DataFrame,
    national_ids: Sequence[str],
    *,
    ages: Sequence[int],
    share: float = 0.10,
) -> AttritionSummary:
    """유년기 최상위였던 선수들이 언제까지 대회에 남았는지 셉니다."""

    frame = _require_filtered(estimates)
    national = set(national_ids)
    at_ages = frame.filter(pl.col("age").is_in(list(ages)))
    per_athlete = (
        at_ages.sort(["athlete_id", "top_share"])
        .group_by("athlete_id")
        .first()
        .select(["athlete_id", "top_share", "birth_year"])
        .filter(pl.col("top_share") <= share)
    )
    top_size = per_athlete.height
    reached = sum(1 for value in per_athlete["athlete_id"].to_list() if str(value) in national)
    if top_size < MIN_COHORT_SIZE:
        return AttritionSummary(
            top_size=top_size,
            reached_national=reached,
            still_active=0,
            left_before_high_school=0,
            left_before_college=0,
            rows=(),
            reason=f"상위 {share:.0%} 집단이 {MIN_COHORT_SIZE}명 미만이라 이탈 분포를 내지 않습니다",
        )

    last_season = (
        race_ledger.select(
            [
                pl.col("athlete_id").cast(pl.Utf8).str.strip_chars().alias("athlete_id"),
                pl.col("season_year").cast(pl.Int64).alias("season_year"),
            ]
        )
        .group_by("athlete_id")
        .agg(pl.col("season_year").max().alias("last_season"))
    )
    season_max = race_ledger.select(pl.col("season_year").cast(pl.Int64).max().alias("latest"))
    latest_value = season_max["latest"][0] if season_max.height else None
    latest_season = int(latest_value) if isinstance(latest_value, (int, float)) else 0
    joined = (
        per_athlete.join(last_season, on="athlete_id", how="inner")
        .with_columns((pl.col("last_season") - pl.col("birth_year")).alias("last_age"))
        .filter(pl.col("last_age").is_not_null())
    )
    still_active = joined.filter(pl.col("last_season") >= latest_season).height
    departed = joined.filter(pl.col("last_season") < latest_season)
    left_before_high_school = departed.filter(pl.col("last_age") < HIGH_SCHOOL_AGE).height
    left_before_college = departed.filter(pl.col("last_age") < COLLEGE_AGE).height

    counted = (
        departed.group_by("last_age").agg(pl.len().alias("count")).sort("last_age")
    )
    total = departed.height
    rows = tuple(
        AttritionRow(
            last_age=int(row["last_age"]),
            count=int(row["count"]),
            share=(int(row["count"]) / float(total)) if total > 0 else 0.0,
        )
        for row in counted.to_dicts()
    )
    return AttritionSummary(
        top_size=top_size,
        reached_national=reached,
        still_active=still_active,
        left_before_high_school=left_before_high_school,
        left_before_college=left_before_college,
        rows=rows,
        reason="",
    )


def late_bloomer_summary(
    estimates: object,
    national_ids: Sequence[str],
    *,
    elementary_ages: Sequence[int],
    later_age: int = HIGH_SCHOOL_AGE,
    leader_share: float = 0.10,
    late_share: float = 0.10,
) -> LateBloomerSummary:
    """국가대표 안에서도 궤적이 서로 달랐는지 셉니다."""

    frame = _require_smoothed(estimates)
    national = list(national_ids)
    early = (
        frame.filter(pl.col("age").is_in(list(elementary_ages)) & pl.col("athlete_id").is_in(national))
        .sort(["athlete_id", "top_share"])
        .group_by("athlete_id")
        .first()
        .select(["athlete_id", pl.col("top_share").alias("early_share")])
    )
    later = (
        frame.filter((pl.col("age") >= later_age) & pl.col("athlete_id").is_in(national))
        .sort(["athlete_id", "top_share"])
        .group_by("athlete_id")
        .first()
        .select(["athlete_id", pl.col("top_share").alias("later_share")])
    )
    merged = later.join(early, on="athlete_id", how="left")
    late_risers = merged.filter(
        (pl.col("later_share") <= late_share)
        & (pl.col("early_share").is_null() | (pl.col("early_share") > leader_share))
    ).height
    # 이후 연령 기록이 없더라도 유년기 위치 자체는 셀 수 있어야 합니다.
    early_leaders = early.filter(pl.col("early_share") <= leader_share).height
    no_record = len(set(national)) - early.height
    return LateBloomerSummary(
        total=len(national),
        late_risers=late_risers,
        early_leaders=early_leaders,
        no_elementary_record=no_record,
    )


def trajectory_cases(
    estimates: object,
    national_ids: Sequence[str],
    *,
    ages: Sequence[int],
) -> list[TrajectoryCase]:
    """국가대표 궤적을 사례 번호로만 묶어 냅니다. 이름은 쓰지 않습니다."""

    frame = _require_smoothed(estimates)
    cases: list[TrajectoryCase] = []
    for index, athlete_id in enumerate(sorted(set(national_ids)), start=1):
        selected = frame.filter((pl.col("athlete_id") == athlete_id) & pl.col("age").is_in(list(ages))).sort("age")
        points = tuple(
            TrajectoryPoint(
                age=int(row["age"]),
                z=float(row["z"]),
                z_sigma=float(row["z_sigma"]),
                n_games=int(row["n_games"]),
            )
            for row in selected.to_dicts()
        )
        cases.append(TrajectoryCase(label=f"사례 {index:02d}", points=points))
    return cases


def assert_no_deterministic_phrases(text: str) -> None:
    """결정론적 표현이 리포트에 섞이지 않았는지 검사합니다."""

    found = sorted({phrase for phrase in DETERMINISTIC_PHRASES if phrase in text})
    if found:
        raise ValueError(f"[error] 결정론적 표현이 리포트에 있습니다: {', '.join(found)}")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _mask_count(count: int) -> str:
    if 0 < count < MIN_COHORT_SIZE:
        return f"{MIN_COHORT_SIZE}명 미만"
    return f"{count:,}명"


def render_report(
    *,
    run_id: str,
    national_count: int,
    birth_years: tuple[int, int],
    elementary_ages: Sequence[int],
    auc_rows: Sequence[AgeAucRow],
    signal_age: tuple[int | None, str],
    rate_rows: Sequence[RateRow],
    attrition: AttritionSummary,
    late_bloomers: LateBloomerSummary,
    cases: Sequence[TrajectoryCase],
    svg_path: Path | None,
) -> str:
    elementary_text = "·".join(f"만 {age}세" for age in elementary_ages)
    lines: list[str] = []
    lines.append("# 국가대표 궤적 검증 리포트")
    lines.append("")
    lines.append(f"- 레이팅 실행: `{run_id}`")
    lines.append(f"- 대상: 공인 국가대표 {national_count}명")
    lines.append(f"- 비교 코호트: {birth_years[0]}~{birth_years[1]}년생")
    lines.append(f"- 유년기 기준 연령: {elementary_text} (초5~6에 해당)")
    lines.append("")

    lines.append("## 한 줄 결론")
    lines.append("")
    lines.extend(_conclusion_lines(auc_rows, rate_rows, signal_age))
    lines.append("")
    lines.append("이 리포트는 집단 통계입니다. 특정 아이의 앞날을 계산하는 도구가 아닙니다.")
    lines.append("")

    lines.append("## 이 리포트를 읽는 법")
    lines.append("")
    lines.append("두 가지 추정치를 구분해서 씁니다.")
    lines.append("")
    lines.append("| 추정치 | 뜻 | 이 리포트에서의 쓰임 |")
    lines.append("| --- | --- | --- |")
    lines.append("| 필터 추정치 | 그 시점까지 치른 경기만으로 만든 값 | 예측력 평가, 두 방향 확률, 이탈 분석 |")
    lines.append("| 스무딩 추정치 | 이후 경기까지 모두 본 뒤 되돌아본 값 | 궤적 표시 |")
    lines.append("")
    lines.append(
        "궤적을 스무딩 추정치로 그리는 이유는 이렇습니다. 어린 시절에는 치른 경기가 적어 그때의 값만으로는 "
        "실력을 좁게 잡기 어렵습니다. 이후 경기 결과까지 함께 보면 그 시절의 값도 더 촘촘하게 다시 잡을 수 "
        "있습니다. 다만 그 값에는 나중에야 알게 된 정보가 들어 있으므로, 예측이 되는지를 재는 데에는 쓰지 "
        "않습니다. 예측력 숫자는 모두 필터 추정치로만 계산했습니다."
    )
    lines.append("")

    lines.append("## 표본의 한계")
    lines.append("")
    lines.append(
        f"국가대표 {national_count}명은 통계적으로 매우 작은 표본입니다. 이 리포트의 모든 비율에는 95% 신뢰구간을 "
        "함께 적었고, 구간은 넓습니다. 넓은 구간은 \"아직 좁혀 말하기 어렵다\"는 뜻입니다. 구간을 빼고 가운데 "
        "값만 옮겨 적으면 실제보다 단단한 이야기가 됩니다."
    )
    lines.append("")
    lines.append(
        "국가대표가 되지 않았지만 비슷한 수준까지 갔던 선수들이 데이터 안에 있습니다. 국가대표 여부는 성취를 "
        "둘로 나누는 선이 아니라, 이 리포트가 관측 가능한 하나의 기준일 뿐입니다."
    )
    lines.append("")
    lines.append(
        f"비교 집단은 국가대표와 같은 시기에 태어난 {birth_years[0]}~{birth_years[1]}년생으로 제한했습니다. "
        "최근에 태어난 선수는 아직 국가대표가 될 기간 자체를 지나지 않았기 때문입니다."
    )
    lines.append("")

    lines.append("## 두 방향 확률")
    lines.append("")
    lines.append(
        "같은 데이터라도 어느 방향으로 묻는지에 따라 답이 크게 달라집니다. 학부모가 실제로 알고 싶은 방향을 "
        "먼저 적습니다."
    )
    lines.append("")
    lines.append("| 유년기 구간 | P(국가대표 \\| 유년기 상위권) | P(유년기 상위권 \\| 국가대표) | 상위권 집단 | 국가대표 중 해당 |")
    lines.append("| --- | --- | --- | ---: | ---: |")
    for row in rate_rows:
        if row.reach_rate is None:
            lines.append(
                f"| 상위 {row.share:.0%} | 판정 불가 | 판정 불가 | {_mask_count(row.top_size)} | "
                f"{row.national_in_top}명 |"
            )
            continue
        reach = f"{_pct(row.reach_rate[0])} (95% {_pct(row.reach_rate[1])}~{_pct(row.reach_rate[2])})"
        given = (
            f"{_pct(row.top_given_national[0])} (95% {_pct(row.top_given_national[1])}~{_pct(row.top_given_national[2])})"
            if row.top_given_national is not None
            else "판정 불가"
        )
        lines.append(
            f"| 상위 {row.share:.0%} | {reach} | {given} | {_mask_count(row.top_size)} | {row.national_in_top}명 |"
        )
    lines.append("")
    hidden_reasons = sorted({row.reason for row in rate_rows if row.reason})
    for reason in hidden_reasons:
        lines.append(f"- 판정 불가 사유: {reason}.")
    if hidden_reasons:
        lines.append("")
    lines.append(
        "왼쪽 열이 학부모가 알고 싶은 방향입니다. 오른쪽 열만 따로 옮기면 \"국가대표는 어릴 때부터 상위권이었다\"는 "
        "인상만 남고, 같은 자리에 있었던 나머지 아이들의 수가 사라집니다."
    )
    lines.append("")

    lines.append("## 연령별 예측력")
    lines.append("")
    lines.append(
        "각 연령에서 그때까지의 필터 추정치만으로 국가대표와 나머지를 얼마나 갈라낼 수 있었는지 잰 값입니다. "
        "0.5는 동전 던지기와 같고, 1.0은 완전히 갈라지는 경우입니다. "
        f"{AUC_WEAK_THRESHOLD} 미만이면 예측력이 약한 것으로 적었습니다."
    )
    lines.append("")
    lines.append("| 연나이 | AUC (95% 구간) | 비교 집단 | 국가대표 | 평균 누적 경기(집단/국가대표) | 판정 |")
    lines.append("| ---: | --- | ---: | ---: | ---: | --- |")
    for auc_row in auc_rows:
        if auc_row.auc is None:
            auc_text = "판정 불가"
        else:
            auc_text = f"{auc_row.auc.point:.3f} (95% {auc_row.auc.low:.3f}~{auc_row.auc.high:.3f})"
        lines.append(
            f"| {auc_row.age} | {auc_text} | {_mask_count(auc_row.cohort_size)} | {auc_row.positives}명 | "
            f"{auc_row.cohort_mean_games:.1f} / {auc_row.national_mean_games:.1f} | "
            f"{auc_row.verdict}{(' — ' + auc_row.reason) if auc_row.reason else ''} |"
        )
    lines.append("")
    age_value, signal_reason = signal_age
    if age_value is None:
        lines.append(f"- 신호가 처음 나타나는 연령: 데이터 부족으로 판정 불가입니다. {signal_reason}.")
    else:
        lines.append(
            f"- 신호가 처음 나타나는 연령: 만 {age_value}세입니다. 이 연령은 평균 누적 경기 수 기준을 "
            f"충족했고, 신뢰구간 아래끝이 0.5를 넘었습니다."
        )
    lines.append(
        f"- 평균 누적 경기 수가 {MIN_MEAN_GAMES:.0f}회 미만인 연령은 추정치가 아직 흔들리는 구간이라 판정에서 "
        "제외했습니다. 그 구간의 숫자를 근거로 결론을 내리지 않았습니다."
    )
    lines.append("")

    lines.append("## 국가대표 궤적 (스무딩 추정치)")
    lines.append("")
    lines.append(
        "값은 같은 연나이·성별 집단의 가운데를 0으로 놓았을 때의 상대 위치이며, 괄호 안은 그 시점까지의 누적 "
        "경기 수입니다. 누적 경기 수가 5회 미만인 값은 `*`로 표시했고, 그 값은 폭이 넓은 추정으로 읽어야 합니다."
    )
    lines.append("")
    ages_present = sorted({point.age for case in cases for point in case.points})
    if ages_present:
        header = " | ".join(f"만 {age}세" for age in ages_present)
        lines.append(f"| 사례 | {header} |")
        lines.append("| --- | " + " | ".join(["---"] * len(ages_present)) + " |")
        for case in cases:
            by_age = {point.age: point for point in case.points}
            cells: list[str] = []
            for age in ages_present:
                point = by_age.get(age)
                if point is None:
                    cells.append("-")
                    continue
                mark = "*" if point.n_games < 5 else ""
                cells.append(f"{point.z:+.2f}{mark} ({point.n_games})")
            lines.append(f"| {case.label} | " + " | ".join(cells) + " |")
    else:
        lines.append("표시할 궤적 값이 없습니다.")
    lines.append("")
    if svg_path is not None:
        lines.append(f"- 궤적 그래프: `{svg_path}` (연령별 누적 경기 수를 아래 축에 함께 그렸습니다)")
        lines.append("")
    lines.append(
        f"- 유년기에 상위 {0.10:.0%} 안에 있었던 사례: {late_bloomers.early_leaders}명 / {late_bloomers.total}명"
    )
    lines.append(
        f"- 유년기에는 상위 {0.10:.0%} 밖이었다가 만 {HIGH_SCHOOL_AGE}세 이후 상위 {0.10:.0%}로 올라온 사례: "
        f"{late_bloomers.late_risers}명"
    )
    lines.append(f"- 유년기 구간에 남은 기록이 없는 사례: {late_bloomers.no_elementary_record}명")
    lines.append(
        "- 기록이 없는 경우는 늦게 시작한 경우와 과거 전산 누락이 섞여 있습니다. 실력이 없었다는 뜻으로 읽으면 "
        "안 됩니다."
    )
    lines.append("")

    lines.append("## 유년기 최상위였던 선수들은 어디까지 남았는가")
    lines.append("")
    if attrition.reason:
        lines.append(f"이 항목은 판정 불가입니다. {attrition.reason}.")
        lines.append("")
    else:
        lines.append(
            f"유년기에 상위 10% 안에 있었던 선수는 {_mask_count(attrition.top_size)}입니다. 이 가운데 국가대표 "
            f"명단에서 확인되는 사례는 {attrition.reached_national}명입니다."
        )
        lines.append("")
        lines.append(
            f"- 아직 최근 시즌까지 대회에 나오고 있는 선수: {_mask_count(attrition.still_active)} "
            "(계속 이어질 수 있으므로 아래 분포에서 제외했습니다)"
        )
        lines.append(
            f"- 만 {HIGH_SCHOOL_AGE}세 이전에 마지막 기록이 남은 선수: {_mask_count(attrition.left_before_high_school)}"
        )
        lines.append(
            f"- 만 {COLLEGE_AGE}세 이전에 마지막 기록이 남은 선수: {_mask_count(attrition.left_before_college)} "
            f"(만 {HIGH_SCHOOL_AGE}세 이전 인원을 포함합니다)"
        )
        lines.append("")
        lines.append("| 마지막 기록이 남은 연나이 | 인원 | 비율 |")
        lines.append("| ---: | ---: | ---: |")
        for attrition_row in attrition.rows:
            share_text = "-" if attrition_row.count < MIN_COHORT_SIZE else _pct(attrition_row.share)
            lines.append(f"| {attrition_row.last_age} | {_mask_count(attrition_row.count)} | {share_text} |")
        lines.append("")
        lines.append(
            "대회 기록이 끊긴 시점을 셌을 뿐이며, 그만둔 이유는 이 데이터로 알 수 없습니다. 부상, 진학, 종목 "
            "전환, 다른 선택이 모두 같은 모양으로 보입니다."
        )
        lines.append("")

    lines.append("## 해석할 때 주의할 점")
    lines.append("")
    lines.append("- 이 수치들은 지나간 집단의 기록이며, 개인의 앞날을 계산해 주지 않습니다.")
    lines.append("- 국가대표에 이르는 길만 성공으로 두면, 데이터에 남은 다른 경로들이 보이지 않게 됩니다.")
    lines.append("- 유년기 순위가 낮았던 선수 중에도 이후 상위로 올라온 사례가 데이터 안에 있습니다.")
    lines.append(
        "- 어린 시절 구간은 치른 경기가 적어 추정이 가장 약한 구간입니다. 그 구간의 숫자를 진로 판단의 근거로 "
        "삼는 것은 이 데이터가 뒷받침하지 않습니다."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _conclusion_lines(
    auc_rows: Sequence[AgeAucRow],
    rate_rows: Sequence[RateRow],
    signal_age: tuple[int | None, str],
) -> list[str]:
    lines: list[str] = []
    judgeable = [row for row in auc_rows if row.auc is not None]
    if not judgeable:
        lines.append(
            "1. 어느 연령에서도 판정 조건을 채우지 못했습니다. 유년기 지표의 예측력은 이 데이터로 판정 불가입니다."
        )
    else:
        best = max(judgeable, key=lambda row: row.auc.point if row.auc is not None else 0.0)
        assert best.auc is not None
        weak = best.auc.point < AUC_WEAK_THRESHOLD or best.auc.low <= 0.5
        strength = "약한 편입니다" if weak else "관측됩니다"
        chance_note = " 구간이 0.5를 포함하므로 우연과 구분하기 어렵습니다." if best.auc.low <= 0.5 else ""
        lines.append(
            f"1. 판정 가능한 연령 가운데 가장 높은 값은 만 {best.age}세의 {best.auc.point:.3f}"
            f"(95% {best.auc.low:.3f}~{best.auc.high:.3f})이며, 유년기 지표의 예측력은 {strength}.{chance_note}"
        )
    top_row = next((row for row in rate_rows if row.reach_rate is not None), None)
    if top_row is not None and top_row.reach_rate is not None:
        lines.append(
            f"2. 유년기에 상위 {top_row.share:.0%} 안에 있었던 선수 중 국가대표 명단에서 확인되는 비율은 "
            f"{_pct(top_row.reach_rate[0])}(95% {_pct(top_row.reach_rate[1])}~{_pct(top_row.reach_rate[2])})입니다."
        )
    else:
        lines.append("2. 유년기 상위권 집단의 국가대표 도달 비율은 표본이 작아 판정 불가입니다.")
    age_value, _ = signal_age
    if age_value is None:
        lines.append("3. 신호가 처음 나타나는 연령은 데이터 부족으로 판정 불가입니다.")
    else:
        lines.append(f"3. 판정 조건을 채운 가장 이른 연령은 만 {age_value}세입니다.")
    return lines


def trajectory_svg(cases: Sequence[TrajectoryCase], *, title: str) -> str:
    """궤적과 연령별 평균 누적 경기 수를 한 장에 그립니다."""

    width = 900
    height = 560
    margin_left = 70
    margin_right = 30
    margin_top = 60
    plot_h = 300
    games_h = 120
    plot_w = width - margin_left - margin_right

    points = [point for case in cases for point in case.points]
    if not points:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="120" viewBox="0 0 {width} 120">'
            f'<text x="20" y="60" font-size="16">표시할 궤적 값이 없습니다.</text></svg>'
        )

    ages = sorted({point.age for point in points})
    age_min, age_max = ages[0], ages[-1]
    z_values = [point.z + point.z_sigma for point in points] + [point.z - point.z_sigma for point in points]
    z_min = min(min(z_values), -1.0)
    z_max = max(max(z_values), 1.0)

    def sx(age: int) -> float:
        if age_max == age_min:
            return margin_left + plot_w / 2.0
        return margin_left + (age - age_min) / float(age_max - age_min) * plot_w

    def sy(z: float) -> float:
        if z_max == z_min:
            return margin_top + plot_h / 2.0
        return margin_top + (z_max - z) / (z_max - z_min) * plot_h

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin_left}" y="30" font-size="18" font-weight="700">{title}</text>',
        f'<text x="{margin_left}" y="48" font-size="12" fill="#555">위: 같은 연나이·성별 집단 대비 상대 위치 (스무딩 추정치, 세로 막대는 추정 폭)</text>',
    ]
    parts.append(
        f'<line x1="{margin_left}" y1="{sy(0.0):.1f}" x2="{margin_left + plot_w}" y2="{sy(0.0):.1f}" '
        'stroke="#bbb" stroke-dasharray="4 4"/>'
    )
    parts.append(f'<text x="{margin_left - 8}" y="{sy(0.0) + 4:.1f}" font-size="11" fill="#777" text-anchor="end">0</text>')

    for age in ages:
        x = sx(age)
        parts.append(
            f'<text x="{x:.1f}" y="{margin_top + plot_h + 18:.1f}" font-size="11" fill="#555" '
            f'text-anchor="middle">{age}</text>'
        )

    for case in cases:
        if not case.points:
            continue
        path = " ".join(f"{sx(point.age):.1f},{sy(point.z):.1f}" for point in case.points)
        parts.append(f'<polyline points="{path}" fill="none" stroke="#5b7cfa" stroke-width="1.4" opacity="0.55"/>')
        for point in case.points:
            x = sx(point.age)
            top = sy(point.z + point.z_sigma)
            bottom = sy(point.z - point.z_sigma)
            thin = point.n_games < 5
            parts.append(
                f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{bottom:.1f}" '
                f'stroke="{"#e07b39" if thin else "#5b7cfa"}" stroke-width="{2.4 if thin else 1.2}" '
                f'opacity="{0.55 if thin else 0.35}"/>'
            )
            parts.append(
                f'<circle cx="{x:.1f}" cy="{sy(point.z):.1f}" r="2.6" '
                f'fill="{"#ffffff" if thin else "#5b7cfa"}" stroke="{"#e07b39" if thin else "#5b7cfa"}"/>'
            )

    games_top = margin_top + plot_h + 60
    mean_games: dict[int, float] = {}
    for age in ages:
        values = [point.n_games for point in points if point.age == age]
        mean_games[age] = sum(values) / float(len(values)) if values else 0.0
    max_games = max(max(mean_games.values()), MIN_MEAN_GAMES)
    parts.append(
        f'<text x="{margin_left}" y="{games_top - 14:.1f}" font-size="12" fill="#555">'
        '아래: 연령별 평균 누적 경기 수 (주황 선 = 5회)</text>'
    )
    bar_width = max(6.0, plot_w / float(max(len(ages), 1)) * 0.5)
    for age in ages:
        value = mean_games[age]
        bar_h = (value / max_games) * games_h
        x = sx(age) - bar_width / 2.0
        parts.append(
            f'<rect x="{x:.1f}" y="{games_top + games_h - bar_h:.1f}" width="{bar_width:.1f}" '
            f'height="{bar_h:.1f}" fill="#9aa7c7"/>'
        )
        parts.append(
            f'<text x="{sx(age):.1f}" y="{games_top + games_h + 16:.1f}" font-size="10" fill="#555" '
            f'text-anchor="middle">{value:.0f}</text>'
        )
    threshold_y = games_top + games_h - (5.0 / max_games) * games_h
    parts.append(
        f'<line x1="{margin_left}" y1="{threshold_y:.1f}" x2="{margin_left + plot_w}" y2="{threshold_y:.1f}" '
        'stroke="#e07b39" stroke-dasharray="4 4"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def build_report(
    *,
    registry_root: Path,
    run_id: str | None,
    ledger: Path,
    athlete_meta_path: Path | None,
    public_figures: Path,
    salt: str,
    ages: Sequence[int],
    elementary_ages: Sequence[int],
    cohort_birth_years: tuple[int, int] | None,
    resamples: int,
    seed: int,
    svg_path: Path | None,
) -> tuple[str, str]:
    registry = RatingRegistry(registry_root)
    resolved_run_id = run_id or registry.current_run_id()
    filtered_snapshots = registry.load_snapshots(resolved_run_id).snapshots
    smoothed_snapshots = registry.load_smoothed_snapshots(resolved_run_id).snapshots
    meta_path = athlete_meta_path or (ledger / "athlete_meta.parquet")
    if not meta_path.exists():
        raise FileNotFoundError(f"[error] athlete_meta 파일이 없습니다: {meta_path}")
    athlete_meta = pl.read_parquet(meta_path)
    race_ledger = load_race_ledger(ledger)
    national_ids = national_team_athlete_ids(public_figures, salt)

    filtered = make_filtered_estimates(filtered_snapshots, athlete_meta)
    smoothed = make_smoothed_estimates(smoothed_snapshots, athlete_meta)
    birth_years = cohort_birth_years or cohort_birth_year_range(filtered.frame, national_ids)
    filtered = FilteredEstimates(frame=restrict_to_cohort(filtered.frame, birth_years))
    smoothed = SmoothedEstimates(frame=restrict_to_cohort(smoothed.frame, birth_years))

    auc_rows = age_auc_rows(filtered, national_ids, ages=ages, resamples=resamples, seed=seed)
    rate_rows = bidirectional_rows(filtered, national_ids, ages=elementary_ages)
    attrition = attrition_summary(filtered, race_ledger, national_ids, ages=elementary_ages)
    late_bloomers = late_bloomer_summary(smoothed, national_ids, elementary_ages=elementary_ages)
    cases = trajectory_cases(smoothed, national_ids, ages=ages)

    report = render_report(
        run_id=resolved_run_id,
        national_count=len(national_ids),
        birth_years=birth_years,
        elementary_ages=elementary_ages,
        auc_rows=auc_rows,
        signal_age=first_signal_age(auc_rows),
        rate_rows=rate_rows,
        attrition=attrition,
        late_bloomers=late_bloomers,
        cases=cases,
        svg_path=svg_path,
    )
    assert_no_deterministic_phrases(report)
    svg = trajectory_svg(cases, title="국가대표 궤적과 연령별 누적 경기 수")
    return report, svg


def _parse_ages(text: str) -> tuple[int, ...]:
    values = [int(part.strip()) for part in text.split(",") if part.strip()]
    if not values:
        raise ValueError("[error] 연령 목록이 비어 있습니다.")
    return tuple(values)


def _parse_range(text: str) -> tuple[int, int]:
    parts = [part.strip() for part in text.split(":") if part.strip()]
    if len(parts) != 2:
        raise ValueError("[error] 범위는 `시작:끝` 형식으로 지정하세요.")
    return (int(parts[0]), int(parts[1]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-16 국가대표 궤적 검증 리포트 생성기")
    parser.add_argument("--registry-root", default=str(DEFAULT_REGISTRY_ROOT), help="레이팅 실행 레지스트리 루트")
    parser.add_argument("--run-id", help="완료된 실행 ID; 생략하면 current 실행을 사용합니다")
    parser.add_argument("--ledger", default="out/ledger", help="race_ledger와 athlete_meta가 있는 경로")
    parser.add_argument("--athlete-meta", default="", help="athlete_meta.parquet 경로 (기본: <ledger>/athlete_meta.parquet)")
    parser.add_argument("--public-figures", default="data/public_figures.csv", help="공개 선수 명단 경로")
    parser.add_argument("--out", default="out/national_team_report.md", help="Markdown 리포트 경로")
    parser.add_argument(
        "--svg-out",
        default="out/national_team_trajectory/trajectory.svg",
        help="궤적 그래프 SVG 경로",
    )
    parser.add_argument(
        "--ages",
        default=f"{DEFAULT_AGE_RANGE[0]}:{DEFAULT_AGE_RANGE[1]}",
        help="분석 연나이 범위 (시작:끝)",
    )
    parser.add_argument(
        "--elementary-ages",
        default=",".join(str(age) for age in DEFAULT_ELEMENTARY_AGES),
        help="유년기 기준 연나이 목록",
    )
    parser.add_argument("--cohort-birth-years", default="", help="비교 코호트 출생연도 범위 (시작:끝)")
    parser.add_argument("--bootstrap-resamples", type=int, default=1000, help="부트스트랩 반복 횟수")
    parser.add_argument("--seed", type=int, default=20260907, help="부트스트랩 난수 seed")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    load_local_env()
    args = build_parser().parse_args(argv)
    age_range = _parse_range(args.ages)
    ages = tuple(range(age_range[0], age_range[1] + 1))
    svg_path = Path(args.svg_out).expanduser() if args.svg_out else None
    report, svg = build_report(
        registry_root=Path(args.registry_root).expanduser(),
        run_id=args.run_id,
        ledger=Path(args.ledger).expanduser(),
        athlete_meta_path=Path(args.athlete_meta).expanduser() if args.athlete_meta else None,
        public_figures=Path(args.public_figures).expanduser(),
        salt=os.environ.get("SPLITS_ANON_SALT", "").strip(),
        ages=ages,
        elementary_ages=_parse_ages(args.elementary_ages),
        cohort_birth_years=_parse_range(args.cohort_birth_years) if args.cohort_birth_years else None,
        resamples=int(args.bootstrap_resamples),
        seed=int(args.seed),
        svg_path=svg_path,
    )
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"[ok] report={out_path}")
    if svg_path is not None:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(svg, encoding="utf-8")
        print(f"[ok] svg={svg_path}")


if __name__ == "__main__":
    main()
