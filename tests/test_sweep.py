import json
import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.metrics import BootstrapInterval
from rating.eval.sweep import (
    CandidateResult,
    ParamSpace,
    SweepCandidate,
    SweepResult,
    _identifiability,
    _select,
    render_report,
    run_sweep,
    write_adr,
    write_production_config,
)
from rating.ledger.ordering import make_ordering_key, make_race_ordering_key
from rating.replay.registry import RatingRegistry


def _row(
    *,
    race_date: str,
    season_year: int,
    meet_id: str,
    race_id: str,
    athlete_id: str,
    rank: int,
) -> dict[str, object]:
    return {
        "ordering_key": make_ordering_key(
            {
                "race_date": race_date,
                "meet_id": meet_id,
                "race_seq": 1,
                "race_id": race_id,
                "rank": rank,
                "athlete_id": athlete_id,
            }
        ),
        "race_ordering_key": make_race_ordering_key(
            {"race_date": race_date, "meet_id": meet_id, "race_seq": 1, "race_id": race_id}
        ),
        "race_id": race_id,
        "athlete_id": athlete_id,
        "rank": rank,
        "status": "FIN",
        "race_date": race_date,
        "season_year": season_year,
        "meet_id": meet_id,
        "race_seq": 1,
        "event": "500m",
        "round": "결승",
        "round_kind": "결승",
        "round_class": "final",
        "place_num": rank,
        "time_sec": 43.0 + rank,
        "weight": 1.0,
    }


def _write_ledger(root: Path) -> None:
    rows = []
    seasons = [(2022 + index, f"{2023 + index:04d}0110") for index in range(12)]
    for index, (season, race_date) in enumerate(seasons):
        for repeat in range(2):
            ranking = ("a1", "a2", "a3") if (index + repeat) % 2 == 0 else ("a2", "a1", "a3")
            rows.extend(
                _row(
                    race_date=race_date,
                    season_year=season,
                    meet_id=f"m{index}-{repeat}",
                    race_id=f"r{index}-{repeat}",
                    athlete_id=athlete_id,
                    rank=rank,
                )
                for rank, athlete_id in enumerate(ranking, start=1)
            )
    destination = root / "race_ledger" / "season=all"
    destination.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(destination / "part.parquet")


def _space(tmp_path: Path, *, resamples: int = 20) -> ParamSpace:
    ledger_root = tmp_path / "ledgers"
    _write_ledger(ledger_root / "conservative")
    _write_ledger(ledger_root / "aggressive")
    default = SweepCandidate(
        axis="default",
        tau=1.0,
        sigma0=8.333,
        beta_ratio=0.5,
        rating_period="meet",
        policy="conservative",
        final_round_weight=1.0,
    )
    return ParamSpace(
        tau=(0.5, 1.0),
        sigma0=(8.333, 12.0),
        beta_ratio=(0.5, 1.0),
        rating_period=("meet", "month"),
        policy=("conservative", "aggressive"),
        final_round_weight=(1.0, 1.5),
        defaults=default,
        ledger_root=ledger_root,
        registry_root=tmp_path / "registry",
        holdout_seasons=2,
        bootstrap_resamples=resamples,
        bootstrap_seed=7,
    )


def _result(candidate: SweepCandidate, loss: float, low: float, high: float) -> CandidateResult:
    return CandidateResult(
        candidate=candidate,
        sweep_id=candidate.axis * 16,
        log_loss=loss,
        accuracy=0.7,
        brier=0.2,
        ece=0.01,
        interval=BootstrapInterval(point=loss, low=low, high=high, resamples=100),
        actuals=(1, 0, 1, 0),
        probabilities=(0.7, 0.3, 0.7, 0.3),
        groups=("r1", "r1", "r2", "r2"),
    )


def test_param_space_expands_each_axis_once_and_keeps_default(tmp_path: Path):
    space = _space(tmp_path)
    candidates = space.candidates()

    assert sum(candidate.axis == "default" for candidate in candidates) == 1
    assert {candidate.axis for candidate in candidates} == {
        "default",
        "tau",
        "sigma0",
        "beta_ratio",
        "rating_period",
        "policy",
        "final_round_weight",
    }
    assert len({candidate.key for candidate in candidates}) == len(candidates)


def test_run_sweep_is_deterministic_and_records_ranked_results(tmp_path: Path):
    first = run_sweep(_space(tmp_path / "first"), n_workers=1)
    second = run_sweep(_space(tmp_path / "second"), n_workers=2)

    assert [row.candidate.key for row in first.results] == [row.candidate.key for row in second.results]
    assert first.selected.candidate.key == second.selected.candidate.key
    first_report = render_report(first, _space(tmp_path / "first"))
    second_report = render_report(second, _space(tmp_path / "second"))
    assert first_report == second_report

    registry = RatingRegistry(tmp_path / "first" / "registry")
    ranked = registry.list_sweep_runs(sort_by="log_loss")
    assert len(ranked) == len(first.results)
    losses = [json.loads(row.metrics_json)["log_loss"] for row in ranked]
    assert losses == sorted(losses)


def test_identifiability_and_selection_choose_simplest_tied_candidate(tmp_path: Path):
    space = _space(tmp_path)
    default = space.defaults
    changed = SweepCandidate(
        axis="tau",
        tau=0.5,
        sigma0=default.sigma0,
        beta_ratio=default.beta_ratio,
        rating_period=default.rating_period,
        policy=default.policy,
        final_round_weight=default.final_round_weight,
    )
    rows = (_result(default, 0.560, 0.550, 0.570), _result(changed, 0.559, 0.549, 0.569))
    identifiable = _identifiability(rows)

    assert identifiable == {"tau": False}
    assert _select(rows, space, identifiable).candidate == default


def test_selection_artifacts_include_chosen_candidate(tmp_path: Path):
    space = _space(tmp_path)
    row = _result(space.defaults, 0.56, 0.55, 0.57)
    result = SweepResult(results=(row,), failures=(), selected=row, identifiable_axes={})
    production = tmp_path / "production.toml"
    adr = tmp_path / "0014.md"

    write_production_config(production, result)
    write_adr(adr, result)

    assert 'name = "trueskill"' in production.read_text(encoding="utf-8")
    assert row.sweep_id in production.read_text(encoding="utf-8")
    assert "더 단순한 설정" in adr.read_text(encoding="utf-8")


def test_registry_keeps_failed_sweep_records(tmp_path: Path):
    registry = RatingRegistry(tmp_path / "registry")
    sweep_id = "a" * 16
    registry.begin_sweep(sweep_id=sweep_id, params={"tau": 1.0}, input_snapshot_id="b" * 64)
    registry.fail_sweep(sweep_id, "simulated failure")

    failed = registry.list_sweep_runs(include_incomplete=True)
    assert [(row.sweep_id, row.status) for row in failed] == [(sweep_id, "failed")]


def test_invalid_toml_requires_all_axes(tmp_path: Path):
    path = tmp_path / "invalid.toml"
    path.write_text("[sweep]\n[defaults]\ntau = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"\[axes\]"):
        ParamSpace.from_toml(path)
