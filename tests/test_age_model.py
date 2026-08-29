import math
import sys
from datetime import date
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.engine.age import (
    build_debut_prior_provider,
    debut_prior,
    fit_age_baseline,
    fit_age_volatility,
    fit_debut_priors,
    normalize,
    set_debut_prior_table,
)


def test_fit_age_baseline_applies_k10_gate():
    rows = []
    for value in range(10):
        rows.append({"age": 12, "sex": "남", "mu": 20.0 + value})
    for value in range(9):
        rows.append({"age": 13, "sex": "남", "mu": 30.0 + value})

    baseline = fit_age_baseline(pl.DataFrame(rows))
    kept = baseline.filter((pl.col("age") == 12) & (pl.col("sex") == "남"))
    dropped = baseline.filter((pl.col("age") == 13) & (pl.col("sex") == "남"))
    assert kept.height == 6
    assert dropped.is_empty()
    assert int(kept["sample_size"][0]) == 10


def test_normalize_uses_p50_and_spread():
    baseline = pl.DataFrame(
        [
            {"age": 12, "sex": "남", "quantile": "p50", "mu": 25.0, "sample_size": 20},
            {"age": 12, "sex": "남", "quantile": "spread", "mu": 2.0, "sample_size": 20},
        ]
    )
    assert normalize(29.0, 12, "남", baseline) == 2.0
    assert math.isnan(normalize(29.0, 13, "남", baseline))


def test_fit_age_volatility_uses_consecutive_delta():
    history = pl.DataFrame(
        [
            {"athlete_id": "a1", "valid_date": date(2024, 1, 1), "mu": 20.0, "age": 10},
            {"athlete_id": "a1", "valid_date": date(2024, 2, 1), "mu": 21.0, "age": 11},
            {"athlete_id": "a1", "valid_date": date(2024, 3, 1), "mu": 19.0, "age": 12},
            {"athlete_id": "a2", "valid_date": date(2024, 1, 1), "mu": 18.0, "age": 10},
            {"athlete_id": "a2", "valid_date": date(2024, 2, 1), "mu": 19.5, "age": 11},
            {"athlete_id": "a2", "valid_date": date(2024, 3, 1), "mu": 18.5, "age": 12},
        ]
    )
    out = fit_age_volatility(history)
    assert 11 in out and 12 in out
    assert out[11] > 0
    assert out[12] > 0


def test_fit_debut_priors_builds_cell_and_fallback_rows():
    ratings = pl.DataFrame(
        [
            {"athlete_id": "a1", "valid_date": date(2023, 1, 1), "mu": 20.0, "n_games": 2},
            {"athlete_id": "a1", "valid_date": date(2023, 2, 1), "mu": 22.0, "n_games": 5},
            {"athlete_id": "a2", "valid_date": date(2023, 1, 1), "mu": 23.0, "n_games": 4},
            {"athlete_id": "a3", "valid_date": date(2023, 1, 1), "mu": 24.0, "n_games": 3},
            {"athlete_id": "a4", "valid_date": date(2023, 1, 1), "mu": 25.0, "n_games": 3},
        ]
    )
    athlete_meta = pl.DataFrame(
        [
            {"athlete_id": "a1", "debut_season": 2023, "debut_division": "초등", "sex": "남"},
            {"athlete_id": "a2", "debut_season": 2023, "debut_division": "초등", "sex": "남"},
            {"athlete_id": "a3", "debut_season": 2023, "debut_division": "중등", "sex": "남"},
            {"athlete_id": "a4", "debut_season": 2023, "debut_division": "중등", "sex": "여"},
        ]
    )
    priors = fit_debut_priors(ratings, athlete_meta, up_to_season=2023, min_count=3)
    assert priors.filter((pl.col("division") == "초등") & (pl.col("sex") == "남")).height == 1
    assert priors.filter((pl.col("division") == "*") & (pl.col("sex") == "*")).height == 1


def test_debut_prior_provider_and_lookup_use_fallback():
    priors = pl.DataFrame(
        [
            {"division": "초등", "sex": "남", "sample_size": 12, "mu0": 21.0, "sigma0": 4.0, "source": "cell", "up_to_season": 2024},
            {"division": "*", "sex": "남", "sample_size": 20, "mu0": 22.0, "sigma0": 5.0, "source": "sex_fallback", "up_to_season": 2024},
            {"division": "*", "sex": "*", "sample_size": 30, "mu0": 23.0, "sigma0": 6.0, "source": "global_fallback", "up_to_season": 2024},
        ]
    )
    athlete_meta = pl.DataFrame(
        [
            {"athlete_id": "a1", "debut_division": "초등", "sex": "남"},
            {"athlete_id": "a2", "debut_division": "고등", "sex": "남"},
            {"athlete_id": "a3", "debut_division": "고등", "sex": "여"},
        ]
    )
    provider = build_debut_prior_provider(priors, athlete_meta)
    assert provider("a1") == (21.0, 4.0)
    assert provider("a2") == (22.0, 5.0)
    assert provider("a3") == (23.0, 6.0)

    set_debut_prior_table(priors)
    assert debut_prior("초등", "남", 2025) == (21.0, 4.0)
    assert debut_prior("고등", "여", 2025) == (23.0, 6.0)
