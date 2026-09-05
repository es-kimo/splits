from __future__ import annotations

import argparse
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import pstdev
from typing import Any, Callable

import polars as pl

from rating.ledger.schema import load_race_ledger

DEFAULT_PRIOR_MU = 25.0
DEFAULT_PRIOR_SIGMA = 25.0 / 3.0
_ACTIVE_DEBUT_PRIORS: pl.DataFrame | None = None
AGE_TAU_BANDS = ("<=12", "13-15", "16+")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def _norm_sex(value: Any) -> str:
    text = _norm(value)
    if not text:
        return ""
    return text[0]


def age_tau_band(age: int | None) -> str:
    if age is None or int(age) <= 0:
        return "unknown"
    if int(age) <= 12:
        return "<=12"
    if int(age) <= 15:
        return "13-15"
    return "16+"


def tau_for(age: int | None, division: str, tau_by_age_band: dict[str, float], *, default_tau: float) -> float:
    del division
    value = tau_by_age_band.get(age_tau_band(age), default_tau)
    tau = float(value)
    if not math.isfinite(tau) or tau < 0:
        raise ValueError("[error] tau_by_age_band 값은 0 이상의 유한값이어야 합니다.")
    return tau


def build_age_tau_provider(
    athlete_meta: pl.DataFrame,
    tau_by_age_band: dict[str, float],
    *,
    default_tau: float,
) -> Callable[[str, date], float]:
    required_meta = {"athlete_id", "birth_year", "debut_division"}
    missing_meta = sorted(required_meta.difference(set(athlete_meta.columns)))
    if missing_meta:
        raise ValueError(f"[error] age tau provider athlete_meta 컬럼 누락: {', '.join(missing_meta)}")
    athlete_index = {
        _norm(row["athlete_id"]): (
            int(row["birth_year"]) if row["birth_year"] is not None else None,
            _norm(row["debut_division"]),
        )
        for row in athlete_meta.select(["athlete_id", "birth_year", "debut_division"]).to_dicts()
        if _norm(row["athlete_id"])
    }

    def _provider(athlete_id: str, as_of: date) -> float:
        birth_year, division = athlete_index.get(_norm(athlete_id), (None, ""))
        age = int(as_of.year) - birth_year if birth_year is not None else None
        return tau_for(age, division, tau_by_age_band, default_tau=default_tau)

    return _provider


def _collect_age_deltas(history: pl.DataFrame) -> dict[int, list[float]]:
    required = {"athlete_id", "valid_date", "mu", "age"}
    missing = sorted(required.difference(set(history.columns)))
    if missing:
        raise ValueError(f"[error] fit_age_volatility 입력 컬럼이 없습니다: {', '.join(missing)}")

    clean = (
        history.select(["athlete_id", "valid_date", "mu", "age"])
        .with_columns(
            [
                pl.col("athlete_id").cast(pl.Utf8, strict=False).str.strip_chars().alias("athlete_id"),
                pl.col("age").cast(pl.Int64, strict=False).alias("age"),
                pl.col("mu").cast(pl.Float64, strict=False).alias("mu"),
                pl.col("valid_date").cast(pl.Date, strict=False).alias("valid_date"),
            ]
        )
        .filter(pl.col("athlete_id") != "")
        .filter(pl.col("mu").is_not_null() & pl.col("age").is_not_null() & pl.col("valid_date").is_not_null())
        .filter((pl.col("age") >= 3) & (pl.col("age") <= 40))
        .sort(["athlete_id", "valid_date"])
    )

    out: dict[int, list[float]] = defaultdict(list)
    for group in clean.partition_by("athlete_id", maintain_order=True):
        rows = group.select(["age", "mu"]).to_dicts()
        if len(rows) < 2:
            continue
        prev_mu = float(rows[0]["mu"])
        for row in rows[1:]:
            age = int(row["age"])
            mu = float(row["mu"])
            out[age].append(mu - prev_mu)
            prev_mu = mu
    return dict(out)


def fit_age_volatility(history: pl.DataFrame) -> dict[int, float]:
    deltas = _collect_age_deltas(history)
    out: dict[int, float] = {}
    for age, values in deltas.items():
        if not values:
            continue
        out[int(age)] = float(pstdev(values)) if len(values) > 1 else 0.0
    return out


def fit_age_baseline(ratings: pl.DataFrame) -> pl.DataFrame:
    required = {"age", "sex", "mu"}
    missing = sorted(required.difference(set(ratings.columns)))
    if missing:
        raise ValueError(f"[error] fit_age_baseline 입력 컬럼이 없습니다: {', '.join(missing)}")

    grouped = (
        ratings.select(["age", "sex", "mu"])
        .with_columns(
            [
                pl.col("age").cast(pl.Int64, strict=False).alias("age"),
                pl.col("mu").cast(pl.Float64, strict=False).alias("mu"),
                pl.col("sex").map_elements(_norm_sex, return_dtype=pl.Utf8).alias("sex"),
            ]
        )
        .filter(pl.col("age").is_not_null() & pl.col("mu").is_not_null() & (pl.col("sex") != ""))
        .filter((pl.col("age") >= 3) & (pl.col("age") <= 40))
        .group_by(["age", "sex"])
        .agg(
            [
                pl.len().alias("sample_size"),
                pl.col("mu").quantile(0.10).alias("p10"),
                pl.col("mu").quantile(0.25).alias("p25"),
                pl.col("mu").quantile(0.50).alias("p50"),
                pl.col("mu").quantile(0.75).alias("p75"),
                pl.col("mu").quantile(0.90).alias("p90"),
            ]
        )
        .filter(pl.col("sample_size") >= 10)
        .with_columns((pl.col("p75") - pl.col("p25")).alias("spread"))
        .sort(["age", "sex"])
    )

    if grouped.is_empty():
        return pl.DataFrame(
            schema={
                "age": pl.Int64,
                "sex": pl.Utf8,
                "quantile": pl.Utf8,
                "mu": pl.Float64,
                "sample_size": pl.Int64,
            }
        )

    rows: list[dict[str, Any]] = []
    for row in grouped.to_dicts():
        age = int(row["age"])
        sex = _norm_sex(row["sex"])
        sample_size = int(row["sample_size"])
        for quantile in ("p10", "p25", "p50", "p75", "p90", "spread"):
            value = row.get(quantile)
            if value is None:
                continue
            rows.append(
                {
                    "age": age,
                    "sex": sex,
                    "quantile": quantile,
                    "mu": float(value),
                    "sample_size": sample_size,
                }
            )
    return pl.DataFrame(rows).sort(["age", "sex", "quantile"])


def normalize(mu: float, age: int, sex: str, baseline: pl.DataFrame) -> float:
    if baseline.is_empty():
        return float("nan")
    sex_norm = _norm_sex(sex)
    if not sex_norm:
        return float("nan")
    match = baseline.filter((pl.col("age") == int(age)) & (pl.col("sex") == sex_norm))
    if match.is_empty():
        return float("nan")
    p50_row = match.filter(pl.col("quantile") == "p50")
    spread_row = match.filter(pl.col("quantile") == "spread")
    if p50_row.is_empty() or spread_row.is_empty():
        return float("nan")
    center = float(p50_row["mu"][0])
    spread = float(spread_row["mu"][0])
    if spread <= 0:
        return float("nan")
    return (float(mu) - center) / spread


def _build_baseline_wide(baseline: pl.DataFrame) -> pl.DataFrame:
    if baseline.is_empty():
        return pl.DataFrame(
            schema={
                "age": pl.Int64,
                "sex": pl.Utf8,
                "baseline_mu": pl.Float64,
                "baseline_spread": pl.Float64,
                "baseline_sample_size": pl.Int64,
            }
        )
    return (
        baseline.group_by(["age", "sex"])
        .agg(
            [
                pl.col("sample_size").max().alias("baseline_sample_size"),
                pl.when(pl.col("quantile") == "p50").then(pl.col("mu")).drop_nulls().first().alias("baseline_mu"),
                pl.when(pl.col("quantile") == "spread").then(pl.col("mu")).drop_nulls().first().alias("baseline_spread"),
            ]
        )
        .sort(["age", "sex"])
    )


def _attach_age(ratings: pl.DataFrame, athlete_meta: pl.DataFrame) -> pl.DataFrame:
    required = {"athlete_id", "valid_date", "mu", "phi", "sigma", "n_games"}
    missing = sorted(required.difference(set(ratings.columns)))
    if missing:
        raise ValueError(f"[error] ratings 입력 컬럼이 없습니다: {', '.join(missing)}")

    meta_cols = {"athlete_id", "birth_year", "sex", "debut_division"}
    if "gender" in athlete_meta.columns and "sex" not in athlete_meta.columns:
        athlete_meta = athlete_meta.rename({"gender": "sex"})
    if "division_text" in athlete_meta.columns and "debut_division" not in athlete_meta.columns:
        athlete_meta = athlete_meta.rename({"division_text": "debut_division"})
    missing_meta = sorted(meta_cols.difference(set(athlete_meta.columns)))
    if missing_meta:
        raise ValueError(f"[error] athlete_meta 입력 컬럼이 없습니다: {', '.join(missing_meta)}")

    merged = (
        ratings.with_columns(
            [
                pl.col("athlete_id").cast(pl.Utf8, strict=False).str.strip_chars().alias("athlete_id"),
                pl.col("valid_date").cast(pl.Date, strict=False).alias("valid_date"),
                pl.col("mu").cast(pl.Float64, strict=False).alias("mu"),
                pl.col("phi").cast(pl.Float64, strict=False).alias("phi"),
                pl.col("sigma").cast(pl.Float64, strict=False).alias("sigma"),
                pl.col("n_games").cast(pl.Int64, strict=False).alias("n_games"),
            ]
        )
        .join(
            athlete_meta.select(
                [
                    pl.col("athlete_id").cast(pl.Utf8, strict=False).str.strip_chars().alias("athlete_id"),
                    pl.col("birth_year").cast(pl.Int64, strict=False).alias("birth_year"),
                    pl.col("sex").map_elements(_norm_sex, return_dtype=pl.Utf8).alias("sex"),
                    pl.col("debut_division").cast(pl.Utf8, strict=False).fill_null("").alias("division"),
                ]
            ),
            on="athlete_id",
            how="left",
        )
        .with_columns(pl.col("valid_date").dt.year().alias("season_year"))
        .with_columns(
            pl.when(
                pl.col("birth_year").is_not_null()
                & pl.col("valid_date").is_not_null()
                & (pl.col("birth_year") >= 1900)
                & (pl.col("birth_year") <= 2099)
            )
            .then(pl.col("season_year") - pl.col("birth_year"))
            .otherwise(None)
            .cast(pl.Int64)
            .alias("age")
        )
    )
    return merged


def _compute_attrition_by_age(race_ledger: pl.DataFrame, athlete_meta: pl.DataFrame) -> pl.DataFrame:
    base = (
        race_ledger.select(["athlete_id", "season_year"])
        .with_columns(
            [
                pl.col("athlete_id").cast(pl.Utf8, strict=False).str.strip_chars().alias("athlete_id"),
                pl.col("season_year").cast(pl.Int64, strict=False).alias("season_year"),
            ]
        )
        .join(
            athlete_meta.select(
                [
                    pl.col("athlete_id").cast(pl.Utf8, strict=False).str.strip_chars().alias("athlete_id"),
                    pl.col("birth_year").cast(pl.Int64, strict=False).alias("birth_year"),
                    pl.col("sex").map_elements(_norm_sex, return_dtype=pl.Utf8).alias("sex"),
                ]
            ),
            on="athlete_id",
            how="left",
        )
        .with_columns(
            pl.when(
                pl.col("season_year").is_not_null()
                & pl.col("birth_year").is_not_null()
                & (pl.col("birth_year") >= 1900)
                & (pl.col("birth_year") <= 2099)
            )
            .then(pl.col("season_year") - pl.col("birth_year"))
            .otherwise(None)
            .cast(pl.Int64)
            .alias("age")
        )
        .filter(pl.col("age").is_not_null() & (pl.col("age") >= 3) & (pl.col("age") <= 40))
        .filter(pl.col("sex") != "")
        .unique(subset=["athlete_id", "sex", "age"])
        .sort(["sex", "age", "athlete_id"])
    )

    by_key: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in base.select(["athlete_id", "sex", "age"]).to_dicts():
        by_key[(_norm_sex(row["sex"]), int(row["age"]))].add(_norm(row["athlete_id"]))

    rows: list[dict[str, Any]] = []
    for (sex, age), athletes in sorted(by_key.items(), key=lambda item: (item[0][0], item[0][1])):
        if not athletes:
            continue
        next_athletes = by_key.get((sex, age + 1), set())
        retained = athletes.intersection(next_athletes)
        dropped = athletes.difference(next_athletes)
        active_count = len(athletes)
        rows.append(
            {
                "sex": sex,
                "age": age,
                "active_athletes": active_count,
                "retained_athletes": len(retained),
                "dropped_athletes": len(dropped),
                "dropout_rate": (len(dropped) / active_count) if active_count > 0 else 0.0,
            }
        )
    return pl.DataFrame(rows).sort(["sex", "age"]) if rows else pl.DataFrame(
        schema={
            "sex": pl.Utf8,
            "age": pl.Int64,
            "active_athletes": pl.Int64,
            "retained_athletes": pl.Int64,
            "dropped_athletes": pl.Int64,
            "dropout_rate": pl.Float64,
        }
    )


def fit_debut_priors(
    ratings: pl.DataFrame,
    athlete_meta: pl.DataFrame,
    *,
    up_to_season: int,
    min_count: int = 10,
    default_mu: float = DEFAULT_PRIOR_MU,
    default_sigma: float = DEFAULT_PRIOR_SIGMA,
) -> pl.DataFrame:
    if min_count <= 0:
        raise ValueError("[error] min_count는 1 이상이어야 합니다.")

    required_meta = {"athlete_id", "debut_season", "debut_division", "sex"}
    missing_meta = sorted(required_meta.difference(set(athlete_meta.columns)))
    if missing_meta:
        raise ValueError(f"[error] fit_debut_priors athlete_meta 컬럼 누락: {', '.join(missing_meta)}")

    merged = (
        ratings.select(["athlete_id", "valid_date", "mu", "n_games"])
        .with_columns(
            [
                pl.col("athlete_id").cast(pl.Utf8, strict=False).str.strip_chars().alias("athlete_id"),
                pl.col("valid_date").cast(pl.Date, strict=False).alias("valid_date"),
                pl.col("mu").cast(pl.Float64, strict=False).alias("mu"),
                pl.col("n_games").cast(pl.Int64, strict=False).alias("n_games"),
            ]
        )
        .join(
            athlete_meta.select(
                [
                    pl.col("athlete_id").cast(pl.Utf8, strict=False).str.strip_chars().alias("athlete_id"),
                    pl.col("debut_season").cast(pl.Int64, strict=False).alias("debut_season"),
                    pl.col("debut_division").cast(pl.Utf8, strict=False).fill_null("").alias("division"),
                    pl.col("sex").map_elements(_norm_sex, return_dtype=pl.Utf8).alias("sex"),
                ]
            ),
            on="athlete_id",
            how="inner",
        )
        .with_columns(pl.col("valid_date").dt.year().alias("season_year"))
        .filter(pl.col("valid_date").is_not_null() & pl.col("mu").is_not_null() & pl.col("n_games").is_not_null())
        .filter(pl.col("n_games") <= 5)
        .filter(pl.col("debut_season").is_not_null() & (pl.col("debut_season") <= int(up_to_season)))
        .filter(pl.col("season_year") <= int(up_to_season))
        .filter((pl.col("division") != "") & (pl.col("sex") != ""))
        .sort(["athlete_id", "n_games", "valid_date"])
    )

    if merged.is_empty():
        return pl.DataFrame(
            [
                {
                    "division": "*",
                    "sex": "*",
                    "sample_size": 0,
                    "mu0": float(default_mu),
                    "sigma0": float(default_sigma),
                    "source": "global_default",
                    "up_to_season": int(up_to_season),
                }
            ]
        )

    per_athlete = merged.group_by("athlete_id").tail(1)
    by_cell = (
        per_athlete.group_by(["division", "sex"])
        .agg(
            [
                pl.len().alias("sample_size"),
                pl.col("mu").median().alias("mu_cell"),
                pl.col("mu").std().alias("sigma_cell"),
            ]
        )
        .with_columns(
            pl.when(pl.col("sigma_cell").is_null() | (pl.col("sigma_cell") <= 0))
            .then(float(default_sigma))
            .otherwise(pl.col("sigma_cell"))
            .alias("sigma_cell")
        )
        .sort(["division", "sex"])
    )
    by_sex = (
        per_athlete.group_by("sex")
        .agg(
            [
                pl.len().alias("sample_size"),
                pl.col("mu").median().alias("mu_sex"),
                pl.col("mu").std().alias("sigma_sex"),
            ]
        )
        .with_columns(
            pl.when(pl.col("sigma_sex").is_null() | (pl.col("sigma_sex") <= 0))
            .then(float(default_sigma))
            .otherwise(pl.col("sigma_sex"))
            .alias("sigma_sex")
        )
    )

    global_row = per_athlete.select(
        [
            pl.len().alias("sample_size"),
            pl.col("mu").median().alias("mu_global"),
            pl.col("mu").std().alias("sigma_global"),
        ]
    ).row(0, named=True)
    global_mu = float(global_row["mu_global"]) if global_row.get("mu_global") is not None else float(default_mu)
    global_sigma_raw = global_row.get("sigma_global")
    global_sigma = float(global_sigma_raw) if global_sigma_raw is not None and float(global_sigma_raw) > 0 else float(default_sigma)

    sex_stats: dict[str, tuple[float, float, int]] = {}
    for row in by_sex.to_dicts():
        sex_stats[_norm_sex(row["sex"])] = (
            float(row["mu_sex"]),
            float(row["sigma_sex"]),
            int(row["sample_size"]),
        )

    rows: list[dict[str, Any]] = []
    for row in by_cell.to_dicts():
        division = _norm(row["division"])
        sex = _norm_sex(row["sex"])
        sample_size = int(row["sample_size"])
        mu_cell = float(row["mu_cell"])
        sigma_cell = float(row["sigma_cell"])
        if sample_size >= min_count:
            mu0 = mu_cell
            sigma0 = sigma_cell
            source = "cell"
        else:
            weight = float(sample_size) / float(min_count)
            parent_mu, parent_sigma, parent_count = sex_stats.get(sex, (global_mu, global_sigma, 0))
            if parent_count <= 0:
                parent_mu = global_mu
                parent_sigma = global_sigma
            mu0 = (weight * mu_cell) + ((1.0 - weight) * parent_mu)
            sigma0 = (weight * sigma_cell) + ((1.0 - weight) * parent_sigma)
            source = "shrink_sex"
        rows.append(
            {
                "division": division,
                "sex": sex,
                "sample_size": sample_size,
                "mu0": float(mu0),
                "sigma0": float(max(sigma0, 1e-6)),
                "source": source,
                "up_to_season": int(up_to_season),
            }
        )

    for sex, (mu, sigma, sample_size) in sorted(sex_stats.items()):
        rows.append(
            {
                "division": "*",
                "sex": sex,
                "sample_size": int(sample_size),
                "mu0": float(mu),
                "sigma0": float(sigma),
                "source": "sex_fallback",
                "up_to_season": int(up_to_season),
            }
        )
    rows.append(
        {
            "division": "*",
            "sex": "*",
            "sample_size": int(global_row["sample_size"]),
            "mu0": float(global_mu),
            "sigma0": float(global_sigma),
            "source": "global_fallback",
            "up_to_season": int(up_to_season),
        }
    )
    return pl.DataFrame(rows).sort(["division", "sex", "source"])


def set_debut_prior_table(priors: pl.DataFrame | None) -> None:
    global _ACTIVE_DEBUT_PRIORS
    _ACTIVE_DEBUT_PRIORS = priors


def debut_prior(division: str, sex: str, season: int) -> tuple[float, float]:
    del season
    if _ACTIVE_DEBUT_PRIORS is None or _ACTIVE_DEBUT_PRIORS.is_empty():
        return float(DEFAULT_PRIOR_MU), float(DEFAULT_PRIOR_SIGMA)
    div = _norm(division)
    sex_norm = _norm_sex(sex)
    table = _ACTIVE_DEBUT_PRIORS
    keys = [(div, sex_norm), (div, "*"), ("*", sex_norm), ("*", "*")]
    for key_div, key_sex in keys:
        matched = table.filter((pl.col("division") == key_div) & (pl.col("sex") == key_sex))
        if matched.is_empty():
            continue
        return float(matched["mu0"][0]), float(matched["sigma0"][0])
    return float(DEFAULT_PRIOR_MU), float(DEFAULT_PRIOR_SIGMA)


def build_debut_prior_provider(
    priors: pl.DataFrame,
    athlete_meta: pl.DataFrame,
    *,
    default_mu: float = DEFAULT_PRIOR_MU,
    default_sigma: float = DEFAULT_PRIOR_SIGMA,
) -> Any:
    if priors.is_empty():
        return lambda _athlete_id: (float(default_mu), float(default_sigma))
    required_meta = {"athlete_id", "debut_division", "sex"}
    missing_meta = sorted(required_meta.difference(set(athlete_meta.columns)))
    if missing_meta:
        raise ValueError(f"[error] prior provider athlete_meta 컬럼 누락: {', '.join(missing_meta)}")
    prior_index = {
        (_norm(row["division"]), _norm_sex(row["sex"])): (float(row["mu0"]), float(row["sigma0"]))
        for row in priors.select(["division", "sex", "mu0", "sigma0"]).to_dicts()
    }
    athlete_index = {
        _norm(row["athlete_id"]): (_norm(row["debut_division"]), _norm_sex(row["sex"]))
        for row in athlete_meta.select(["athlete_id", "debut_division", "sex"]).to_dicts()
        if _norm(row["athlete_id"])
    }

    def _provider(athlete_id: str) -> tuple[float, float] | None:
        division, sex = athlete_index.get(_norm(athlete_id), ("", ""))
        for key in ((division, sex), (division, "*"), ("*", sex), ("*", "*")):
            if key in prior_index:
                return prior_index[key]
        return float(default_mu), float(default_sigma)

    return _provider


def _render_report(
    *,
    joined: pl.DataFrame,
    baseline_wide: pl.DataFrame,
    volatility: dict[int, float],
    volatility_counts: dict[int, int],
    attrition: pl.DataFrame,
    debut_priors: pl.DataFrame,
) -> str:
    total_rows = int(joined.height)
    with_age = int(joined.filter(pl.col("age").is_not_null()).height)
    with_sex = int(joined.filter(pl.col("sex") != "").height)
    baseline_ready = int(joined.filter(pl.col("baseline_available") == True).height)

    lines = [
        "# 연령 곡선 리포트",
        "",
        "## 요약",
        "",
        f"- 스냅샷 행 수: {total_rows:,}",
        f"- 연령 계산 가능 행 수: {with_age:,} ({(with_age / total_rows * 100.0) if total_rows else 0.0:.2f}%)",
        f"- 성별 보유 행 수: {with_sex:,} ({(with_sex / total_rows * 100.0) if total_rows else 0.0:.2f}%)",
        f"- z-score 산출 가능 행 수: {baseline_ready:,} ({(baseline_ready / total_rows * 100.0) if total_rows else 0.0:.2f}%)",
        "",
        "## 연령 베이스라인 (p50, spread, k>=10)",
        "",
        "| age | sex | sample_size | p50 | spread |",
        "| ---: | --- | ---: | ---: | ---: |",
    ]
    for row in baseline_wide.sort(["age", "sex"]).to_dicts():
        lines.append(
            f"| {int(row['age'])} | {_norm(row['sex'])} | {int(row['baseline_sample_size'])} | "
            f"{float(row['baseline_mu']):.4f} | {float(row['baseline_spread']):.4f} |"
        )

    lines.extend(
        [
            "",
            "## 신인 사전분포 (부문×성별)",
            "",
            "| division | sex | sample_size | mu0 | sigma0 | source |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in debut_priors.sort(["division", "sex", "source"]).to_dicts():
        lines.append(
            f"| {_norm(row['division'])} | {_norm(row['sex'])} | {int(row['sample_size'])} | "
            f"{float(row['mu0']):.4f} | {float(row['sigma0']):.4f} | {_norm(row['source'])} |"
        )

    lines.extend(
        [
            "",
            "## 연령별 변동성 (연속 period Δmu 표준편차)",
            "",
            "| age | delta_count | volatility |",
            "| ---: | ---: | ---: |",
        ]
    )
    for age in sorted(volatility.keys()):
        lines.append(f"| {age} | {int(volatility_counts.get(age, 0)):,} | {float(volatility[age]):.6f} |")

    lines.extend(
        [
            "",
            "## 생존 편향 지표 (age→age+1 이탈률)",
            "",
            "| sex | age | active | retained(next age) | dropped | dropout_rate |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in attrition.sort(["sex", "age"]).to_dicts():
        lines.append(
            f"| {_norm(row['sex'])} | {int(row['age'])} | {int(row['active_athletes']):,} | "
            f"{int(row['retained_athletes']):,} | {int(row['dropped_athletes']):,} | "
            f"{float(row['dropout_rate']) * 100.0:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## 한계",
            "",
            "- 연령은 `대회연도 - 출생연도`로 계산해 생월이 없으므로 ±1세 오차가 있습니다.",
            "- 이 리포트의 z-score는 코호트 내 상대 위치이며, 절대 실력 앵커링은 포함하지 않습니다.",
            "- 고연령 구간 표본은 생존자 편향 영향을 받습니다. 이탈률 표를 함께 해석해야 합니다.",
            "",
        ]
    )
    return "\n".join(lines)


def build_age_adjusted_outputs(
    *,
    ratings: pl.DataFrame,
    race_ledger: pl.DataFrame,
    athlete_meta: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[int, float], dict[int, int], pl.DataFrame]:
    joined = _attach_age(ratings, athlete_meta)
    baseline = fit_age_baseline(joined.select(["age", "sex", "mu"]))
    baseline_wide = _build_baseline_wide(baseline)
    deltas = _collect_age_deltas(joined.select(["athlete_id", "valid_date", "mu", "age"]))
    volatility = {age: float(pstdev(values)) if len(values) > 1 else 0.0 for age, values in deltas.items() if values}
    volatility_counts = {age: len(values) for age, values in deltas.items() if values}

    adjusted = joined
    if baseline_wide.is_empty():
        adjusted = adjusted.with_columns(
            [
                pl.lit(None).cast(pl.Float64).alias("baseline_mu"),
                pl.lit(None).cast(pl.Float64).alias("baseline_spread"),
                pl.lit(None).cast(pl.Int64).alias("baseline_sample_size"),
            ]
        )
    else:
        adjusted = adjusted.join(baseline_wide, on=["age", "sex"], how="left")

    adjusted = adjusted.with_columns(
        [
            pl.when(
                pl.col("age").is_not_null()
                & (pl.col("sex") != "")
                & pl.col("baseline_mu").is_not_null()
                & pl.col("baseline_spread").is_not_null()
                & (pl.col("baseline_spread") > 0)
                & pl.col("baseline_sample_size").is_not_null()
                & (pl.col("baseline_sample_size") >= 10)
            )
            .then(True)
            .otherwise(False)
            .alias("baseline_available"),
            pl.when(pl.col("birth_year").is_null())
            .then(pl.lit("birth_year_missing"))
            .when(pl.col("sex") == "")
            .then(pl.lit("sex_missing"))
            .when(pl.col("age").is_null())
            .then(pl.lit("age_unavailable"))
            .when(pl.col("baseline_sample_size").is_null() | (pl.col("baseline_sample_size") < 10))
            .then(pl.lit("sample_lt_10"))
            .when(pl.col("baseline_spread").is_null() | (pl.col("baseline_spread") <= 0))
            .then(pl.lit("spread_zero"))
            .otherwise(pl.lit(""))
            .alias("baseline_unavailable_reason"),
        ]
    ).with_columns(
        pl.when(pl.col("baseline_available") == True)
        .then((pl.col("mu") - pl.col("baseline_mu")) / pl.col("baseline_spread"))
        .otherwise(None)
        .cast(pl.Float64)
        .alias("z")
    )

    adjusted = adjusted.select(
        [
            "athlete_id",
            "valid_date",
            "season_year",
            "birth_year",
            "age",
            "sex",
            "division",
            "mu",
            "phi",
            "sigma",
            "n_games",
            "baseline_mu",
            "baseline_spread",
            "baseline_sample_size",
            "baseline_available",
            "baseline_unavailable_reason",
            "z",
        ]
    ).sort(["valid_date", "athlete_id"])

    attrition = _compute_attrition_by_age(race_ledger, athlete_meta)
    return adjusted, baseline_wide, volatility, volatility_counts, attrition


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R-06 연령 기반 정규화 리포트/산출물 생성기")
    parser.add_argument("--ratings", default="out/ratings_baseline.parquet", help="레이팅 스냅샷 parquet")
    parser.add_argument("--ledger", default="out/ledger", help="race_ledger를 포함한 입력 경로")
    parser.add_argument("--athlete-meta", default="", help="athlete_meta.parquet 경로 (기본: <ledger>/athlete_meta.parquet)")
    parser.add_argument("--out", default="out/age_curves.md", help="리포트 출력 경로")
    parser.add_argument("--adjusted-out", default="out/ratings_age_adjusted.parquet", help="정규화 스냅샷 출력 경로")
    parser.add_argument("--debut-prior-out", default="out/debut_priors.parquet", help="신인 사전분포 출력 경로")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    ratings_path = Path(args.ratings).expanduser()
    ledger_path = Path(args.ledger).expanduser()
    report_path = Path(args.out).expanduser()
    adjusted_path = Path(args.adjusted_out).expanduser()
    debut_prior_path = Path(args.debut_prior_out).expanduser()

    if not ratings_path.exists():
        raise FileNotFoundError(f"[error] ratings 파일이 없습니다: {ratings_path}")

    if args.athlete_meta:
        athlete_meta_path = Path(args.athlete_meta).expanduser()
    else:
        athlete_meta_path = ledger_path / "athlete_meta.parquet"
        if not athlete_meta_path.exists() and ledger_path.is_dir() and (ledger_path / "race_ledger").exists():
            athlete_meta_path = ledger_path / "athlete_meta.parquet"

    if not athlete_meta_path.exists():
        raise FileNotFoundError(f"[error] athlete_meta 파일이 없습니다: {athlete_meta_path}")

    ratings = pl.read_parquet(ratings_path)
    race_ledger = load_race_ledger(ledger_path)
    athlete_meta = pl.read_parquet(athlete_meta_path)

    adjusted, baseline_wide, volatility, volatility_counts, attrition = build_age_adjusted_outputs(
        ratings=ratings,
        race_ledger=race_ledger,
        athlete_meta=athlete_meta,
    )
    max_season = int(adjusted["season_year"].max()) if adjusted.height else 0
    fit_until = max_season - 1 if max_season > 0 else 0
    debut_priors = fit_debut_priors(
        ratings=ratings,
        athlete_meta=athlete_meta,
        up_to_season=fit_until,
    )
    set_debut_prior_table(debut_priors)
    report_text = _render_report(
        joined=adjusted,
        baseline_wide=baseline_wide,
        volatility=volatility,
        volatility_counts=volatility_counts,
        attrition=attrition,
        debut_priors=debut_priors,
    )

    adjusted_path.parent.mkdir(parents=True, exist_ok=True)
    adjusted.write_parquet(adjusted_path)
    debut_prior_path.parent.mkdir(parents=True, exist_ok=True)
    debut_priors.write_parquet(debut_prior_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    print(f"[ok] adjusted={adjusted_path}")
    print(f"[ok] debut_priors={debut_prior_path}")
    print(f"[ok] report={report_path}")
    print(f"[ok] rows={adjusted.height:,}")


if __name__ == "__main__":
    main()
