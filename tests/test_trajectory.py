import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.metrics import auc_score, bootstrap_auc_ci, wilson_interval
from rating.eval.trajectory import (
    AUC_WEAK_THRESHOLD,
    DETERMINISTIC_PHRASES,
    MIN_COHORT_SIZE,
    AgeAucRow,
    AttritionSummary,
    FilteredEstimates,
    LateBloomerSummary,
    RateRow,
    SmoothedEstimates,
    age_auc_rows,
    assert_no_deterministic_phrases,
    attrition_summary,
    bidirectional_rows,
    build_age_estimates,
    first_signal_age,
    late_bloomer_summary,
    national_team_athlete_ids,
    render_report,
    trajectory_cases,
    trajectory_svg,
)

ESTIMATE_SCHEMA = {
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


def _estimates(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=ESTIMATE_SCHEMA)


def _linear_cohort(
    *,
    age: int,
    size: int = 100,
    n_games: int = 20,
    birth_year: int = 2000,
) -> list[dict[str, object]]:
    """상위 1%부터 100%까지 고르게 퍼진 합성 코호트를 만듭니다."""

    rows: list[dict[str, object]] = []
    for index in range(size):
        rows.append(
            {
                "athlete_id": f"a{index:03d}",
                "age": age,
                "sex": "남",
                "birth_year": birth_year,
                "z": float(size - index) / 10.0,
                "z_sigma": 0.2,
                "n_games": n_games,
                "top_share": float(index + 1) / float(size),
                "cohort_size": size,
            }
        )
    return rows


def test_auc_score_handles_separation_and_ties() -> None:
    assert auc_score([1, 1, 0, 0], [2.0, 3.0, 0.0, 1.0]) == pytest.approx(1.0)
    assert auc_score([1, 1, 0, 0], [0.0, 1.0, 2.0, 3.0]) == pytest.approx(0.0)
    assert auc_score([1, 0, 1, 0], [1.0, 1.0, 1.0, 1.0]) == pytest.approx(0.5)
    # 양성만 있으면 갈라낼 대상이 없습니다.
    assert auc_score([1, 1], [1.0, 2.0]) == pytest.approx(0.5)


def test_bootstrap_auc_ci_is_deterministic_and_brackets_point() -> None:
    labels = [1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    scores = [2.0, 1.0, 0.2, 0.9, 0.4, 0.1, -0.5, -1.0, 0.3, -0.2]
    first = bootstrap_auc_ci(labels, scores, resamples=200, seed=7)
    second = bootstrap_auc_ci(labels, scores, resamples=200, seed=7)
    assert first == second
    assert first.low <= first.point <= first.high
    assert 0.0 <= first.low <= 1.0 and 0.0 <= first.high <= 1.0


def test_smoothed_estimates_are_rejected_by_predictive_functions() -> None:
    """스무딩 값으로 예측력을 재면 미래 정보가 새어 들어옵니다. 타입으로 막습니다."""

    smoothed = SmoothedEstimates(frame=_estimates(_linear_cohort(age=11)))
    with pytest.raises(TypeError, match="필터 추정치"):
        age_auc_rows(smoothed, ["a000"], ages=[11])
    with pytest.raises(TypeError, match="필터 추정치"):
        bidirectional_rows(smoothed, ["a000"], ages=[11])
    with pytest.raises(TypeError, match="필터 추정치"):
        attrition_summary(smoothed, pl.DataFrame({"athlete_id": ["a000"], "season_year": [2015]}), ["a000"], ages=[11])

    filtered = FilteredEstimates(frame=_estimates(_linear_cohort(age=11)))
    with pytest.raises(TypeError, match="스무딩 추정치"):
        trajectory_cases(filtered, ["a000"], ages=[11])
    with pytest.raises(TypeError, match="스무딩 추정치"):
        late_bloomer_summary(filtered, ["a000"], elementary_ages=[11])


def test_bidirectional_rates_report_both_directions() -> None:
    national = ["a000", "a001", "a002", "a003", "a050"]
    filtered = FilteredEstimates(frame=_estimates(_linear_cohort(age=11)))
    rows = bidirectional_rows(filtered, national, ages=[11], shares=[0.10])
    row = rows[0]

    assert row.top_size == 10
    assert row.national_in_top == 4
    assert row.national_total == 5
    assert row.reach_rate is not None and row.top_given_national is not None
    # P(국가대표 | 상위 10%) = 4/10, P(상위 10% | 국가대표) = 4/5
    assert row.reach_rate[0] == pytest.approx(0.4)
    assert row.top_given_national[0] == pytest.approx(0.8)
    assert row.reach_rate[1:] == pytest.approx(wilson_interval(4, 10))
    assert row.top_given_national[1:] == pytest.approx(wilson_interval(4, 5))
    # 두 방향은 서로 다른 질문입니다.
    assert row.reach_rate[0] < row.top_given_national[0]


def test_small_top_group_is_not_reported() -> None:
    filtered = FilteredEstimates(frame=_estimates(_linear_cohort(age=11, size=20)))
    rows = bidirectional_rows(filtered, ["a000"], ages=[11], shares=[0.10])
    assert rows[0].reach_rate is None
    assert f"{MIN_COHORT_SIZE}명 미만" in rows[0].reason


def test_age_auc_gating_blocks_thin_evidence() -> None:
    national = ["a000", "a001", "a002"]

    # 국가대표 표본이 2명이면 판정하지 않습니다.
    thin_positive = FilteredEstimates(frame=_estimates(_linear_cohort(age=11)))
    rows = age_auc_rows(thin_positive, ["a000", "a001"], ages=[11], resamples=50)
    assert rows[0].auc is None
    assert rows[0].verdict == "판정 불가"
    assert "국가대표가" in rows[0].reason

    # 누적 경기 수가 적은 연령도 판정하지 않습니다.
    few_games = FilteredEstimates(frame=_estimates(_linear_cohort(age=8, n_games=3)))
    rows = age_auc_rows(few_games, national, ages=[8], resamples=50)
    assert rows[0].auc is None
    assert "평균 누적 경기 수" in rows[0].reason

    # 비교 집단 자체가 작으면 판정하지 않습니다.
    tiny = FilteredEstimates(frame=_estimates(_linear_cohort(age=11, size=6)))
    rows = age_auc_rows(tiny, ["a000", "a001", "a002"], ages=[11], resamples=50)
    assert rows[0].auc is None
    assert f"{MIN_COHORT_SIZE}명 미만" in rows[0].reason


def test_age_auc_computes_when_evidence_is_sufficient() -> None:
    filtered = FilteredEstimates(frame=_estimates(_linear_cohort(age=13)))
    rows = age_auc_rows(filtered, ["a000", "a001", "a002"], ages=[13], resamples=100)
    assert rows[0].auc is not None
    assert rows[0].auc.point == pytest.approx(1.0)
    assert rows[0].verdict == "구분되는 경향 관측"


def test_weak_auc_is_described_as_weak() -> None:
    # 상위권과 하위권에 국가대표가 흩어져 있으면 갈라내는 힘이 약합니다.
    filtered = FilteredEstimates(frame=_estimates(_linear_cohort(age=13)))
    rows = age_auc_rows(filtered, ["a000", "a050", "a099"], ages=[13], resamples=100)
    assert rows[0].auc is not None
    assert rows[0].auc.point < AUC_WEAK_THRESHOLD
    assert "예측력 약함" in rows[0].verdict
    assert first_signal_age(rows)[0] is None


def test_first_signal_age_requires_interval_above_chance() -> None:
    blocked = AgeAucRow(
        age=9,
        cohort_size=100,
        positives=2,
        cohort_mean_games=2.0,
        national_mean_games=2.0,
        auc=None,
        verdict="판정 불가",
        reason="평균 누적 경기 수가 6회 미만입니다",
    )
    assert first_signal_age([blocked]) == (None, "판정 조건을 채우는 연령이 없어 데이터 부족으로 판정 불가입니다")


def test_attrition_counts_departures_and_excludes_active_athletes() -> None:
    rows = _linear_cohort(age=11, size=100)
    filtered = FilteredEstimates(frame=_estimates(rows))
    ledger_rows: list[dict[str, object]] = []
    for index in range(100):
        # 상위 10명 중 절반은 만 14세에 기록이 끊기고, 나머지는 최근 시즌까지 남습니다.
        last_season = 2014 if index < 5 else 2020
        ledger_rows.append({"athlete_id": f"a{index:03d}", "season_year": last_season})
    ledger = pl.DataFrame(ledger_rows, schema={"athlete_id": pl.Utf8, "season_year": pl.Int64})

    summary = attrition_summary(filtered, ledger, ["a000"], ages=[11], share=0.10)
    assert summary.top_size == 10
    assert summary.reached_national == 1
    assert summary.still_active == 5
    assert summary.left_before_high_school == 5
    assert summary.left_before_college == 5
    assert [(row.last_age, row.count) for row in summary.rows] == [(14, 5)]


def test_late_bloomer_summary_counts_paths() -> None:
    rows = _linear_cohort(age=11, size=100) + _linear_cohort(age=17, size=100)
    frame = _estimates(rows)
    # 사례 하나는 유년기에 상위권 밖이었다가 이후 최상위로 올라온 것으로 둡니다.
    frame = frame.with_columns(
        pl.when((pl.col("athlete_id") == "a090") & (pl.col("age") == 17))
        .then(pl.lit(0.02))
        .otherwise(pl.col("top_share"))
        .alias("top_share")
    )
    smoothed = SmoothedEstimates(frame=frame)
    summary = late_bloomer_summary(smoothed, ["a000", "a090"], elementary_ages=[11], later_age=17)
    assert summary.total == 2
    assert summary.early_leaders == 1
    assert summary.late_risers == 1
    assert summary.no_elementary_record == 0


def test_late_bloomer_summary_counts_early_position_without_later_records() -> None:
    """이후 연령 기록이 없어도 유년기 위치는 세야 합니다."""

    smoothed = SmoothedEstimates(frame=_estimates(_linear_cohort(age=11, size=100)))
    summary = late_bloomer_summary(smoothed, ["a000", "a050", "a900"], elementary_ages=[11], later_age=17)
    assert summary.total == 3
    assert summary.early_leaders == 1
    assert summary.late_risers == 0
    assert summary.no_elementary_record == 1


def test_build_age_estimates_uses_last_snapshot_of_each_age() -> None:
    athletes = [f"s{index:02d}" for index in range(12)]
    athlete_meta = pl.DataFrame(
        {
            "athlete_id": athletes,
            "birth_year": [2000] * 12,
            "sex": ["남"] * 12,
            "debut_division": ["초등부"] * 12,
        }
    )
    rows: list[dict[str, object]] = []
    for index, athlete_id in enumerate(athletes):
        rows.append(
            {
                "athlete_id": athlete_id,
                "valid_date": date(2011, 6, 1),
                "mu": 20.0,
                "sigma": 4.0,
                "n_games": 3,
            }
        )
        rows.append(
            {
                "athlete_id": athlete_id,
                "valid_date": date(2011, 12, 1),
                "mu": 20.0 + float(index),
                "sigma": 2.0,
                "n_games": 9,
            }
        )
    snapshots = pl.DataFrame(
        rows,
        schema={
            "athlete_id": pl.Utf8,
            "valid_date": pl.Date,
            "mu": pl.Float64,
            "sigma": pl.Float64,
            "n_games": pl.Int64,
        },
    )

    estimates = build_age_estimates(snapshots, athlete_meta)
    assert estimates.height == 12
    assert estimates["age"].unique().to_list() == [11]
    assert estimates["n_games"].unique().to_list() == [9]
    best = estimates.sort("z", descending=True).row(0, named=True)
    assert best["athlete_id"] == "s11"
    assert best["top_share"] == pytest.approx(1.0 / 12.0)
    assert best["cohort_size"] == 12
    assert best["z_sigma"] > 0.0


def test_national_team_ids_require_salt_and_active_designation(tmp_path: Path) -> None:
    path = tmp_path / "public_figures.csv"
    path.write_text(
        "idNo,이름,슬러그,출생연도,지정근거,언론보도URL,지정일자,상태\n"
        "111,가나다,ganada,2004,2026/27 시즌 쇼트트랙 국가대표(연맹 등재),https://example.com,2026-08-09,active\n"
        "222,라마바,ramaba,2005,지도자 공개 활동,https://example.com,2026-08-09,active\n"
        "333,사아자,saaja,2006,2026/27 시즌 쇼트트랙 국가대표(연맹 등재),https://example.com,2026-08-09,retired\n",
        encoding="utf-8",
    )
    ids = national_team_athlete_ids(path, "salt")
    assert len(ids) == 1
    assert all(len(value) == 12 for value in ids)
    with pytest.raises(ValueError, match="SPLITS_ANON_SALT"):
        national_team_athlete_ids(path, "")


def _report_fixture(*, attrition: AttritionSummary) -> str:
    auc_rows = [
        AgeAucRow(
            age=9,
            cohort_size=120,
            positives=4,
            cohort_mean_games=2.1,
            national_mean_games=2.4,
            auc=None,
            verdict="판정 불가",
            reason="평균 누적 경기 수가 6회 미만이라 추정치가 아직 불안정합니다",
        ),
        AgeAucRow(
            age=12,
            cohort_size=140,
            positives=9,
            cohort_mean_games=11.0,
            national_mean_games=14.0,
            auc=bootstrap_auc_ci([1, 1, 1, 0, 0, 0, 0, 0, 0, 0], [1.0, 0.2, -0.3, 0.5, 0.1, -0.2, -0.7, -1.1, 0.0, -0.4], resamples=50),
            verdict="예측력 약함",
            reason="",
        ),
    ]
    rate_rows = [
        RateRow(
            share=0.10,
            top_size=48,
            national_total=12,
            national_in_top=7,
            reach_rate=(7 / 48, *wilson_interval(7, 48)),
            top_given_national=(7 / 12, *wilson_interval(7, 12)),
            reason="",
        ),
        RateRow(
            share=0.20,
            top_size=6,
            national_total=12,
            national_in_top=2,
            reach_rate=None,
            top_given_national=None,
            reason="상위 20% 집단이 10명 미만이라 비율을 내지 않습니다",
        ),
    ]
    smoothed = SmoothedEstimates(frame=_estimates(_linear_cohort(age=12, size=100)))
    cases = trajectory_cases(smoothed, ["a000", "a001"], ages=[12])
    return render_report(
        run_id="run-test",
        national_count=14,
        birth_years=(1998, 2010),
        elementary_ages=[11, 12],
        auc_rows=auc_rows,
        signal_age=first_signal_age(auc_rows),
        rate_rows=rate_rows,
        attrition=attrition,
        late_bloomers=LateBloomerSummary(total=14, late_risers=3, early_leaders=6, no_elementary_record=2),
        cases=cases,
        svg_path=Path("out/national_team_trajectory/trajectory.svg"),
    )


def _attrition_fixture() -> AttritionSummary:
    from rating.eval.trajectory import AttritionRow

    return AttritionSummary(
        top_size=64,
        reached_national=5,
        still_active=12,
        left_before_high_school=21,
        left_before_college=38,
        rows=(
            AttritionRow(last_age=13, count=4, share=4 / 52),
            AttritionRow(last_age=15, count=17, share=17 / 52),
        ),
        reason="",
    )


def test_report_contains_required_sections_and_no_deterministic_phrases() -> None:
    report = _report_fixture(attrition=_attrition_fixture())
    assert_no_deterministic_phrases(report)
    for phrase in DETERMINISTIC_PHRASES:
        assert phrase not in report

    for heading in (
        "## 한 줄 결론",
        "## 이 리포트를 읽는 법",
        "## 표본의 한계",
        "## 두 방향 확률",
        "## 연령별 예측력",
        "## 국가대표 궤적 (스무딩 추정치)",
        "## 유년기 최상위였던 선수들은 어디까지 남았는가",
        "## 해석할 때 주의할 점",
    ):
        assert heading in report

    # 필터/스무딩 구분과 표본 한계가 본문에 있어야 합니다.
    assert "필터 추정치" in report and "스무딩 추정치" in report
    assert "국가대표 14명은 통계적으로 매우 작은 표본입니다" in report
    assert "1998~2010년생" in report
    # 두 방향 확률이 같은 표에 함께 있어야 합니다.
    assert "P(국가대표 \\| 유년기 상위권)" in report
    assert "P(유년기 상위권 \\| 국가대표)" in report
    # 실명이 아니라 사례 번호만 씁니다.
    assert "사례 01" in report


def test_report_masks_small_cells() -> None:
    report = _report_fixture(attrition=_attrition_fixture())
    # 10명 미만 칸은 인원 수를 그대로 적지 않습니다.
    assert "| 상위 20% | 판정 불가 | 판정 불가 | 10명 미만 |" in report
    assert "| 13 | 10명 미만 | - |" in report
    assert "상위 20% 집단이 10명 미만이라 비율을 내지 않습니다" in report


def test_report_reports_unjudgeable_ages_with_reason() -> None:
    report = _report_fixture(attrition=_attrition_fixture())
    assert "판정 불가" in report
    assert "평균 누적 경기 수가 6회 미만이라 추정치가 아직 불안정합니다" in report
    assert "신호가 처음 나타나는 연령: 데이터 부족으로 판정 불가입니다" in report


def test_report_rejects_deterministic_phrases() -> None:
    with pytest.raises(ValueError, match="결정론적 표현"):
        assert_no_deterministic_phrases("이 아이는 국가대표가 될 것이다.")


def test_trajectory_svg_shows_cumulative_games_axis() -> None:
    smoothed = SmoothedEstimates(frame=_estimates(_linear_cohort(age=12, size=100, n_games=4)))
    cases = trajectory_cases(smoothed, ["a000", "a001"], ages=[12])
    svg = trajectory_svg(cases, title="테스트")
    assert svg.startswith("<svg")
    assert "연령별 평균 누적 경기 수" in svg
    # 경기 수가 5회 미만인 점은 넓은 폭으로 표시합니다.
    assert "#e07b39" in svg


def test_conclusion_matches_verdict_when_interval_includes_chance() -> None:
    """구간이 0.5를 포함하면 결론 문장도 약하게 적어야 합니다."""

    filtered = FilteredEstimates(frame=_estimates(_linear_cohort(age=13)))
    rows = age_auc_rows(filtered, ["a000", "a050", "a099"], ages=[13], resamples=100)
    report = render_report(
        run_id="run-test",
        national_count=14,
        birth_years=(1998, 2010),
        elementary_ages=[11, 12],
        auc_rows=rows,
        signal_age=first_signal_age(rows),
        rate_rows=[],
        attrition=AttritionSummary(
            top_size=4,
            reached_national=1,
            still_active=0,
            left_before_high_school=0,
            left_before_college=0,
            rows=(),
            reason="상위 10% 집단이 10명 미만이라 이탈 분포를 내지 않습니다",
        ),
        late_bloomers=LateBloomerSummary(total=14, late_risers=0, early_leaders=1, no_elementary_record=0),
        cases=[],
        svg_path=None,
    )
    assert "예측력은 약한 편입니다" in report
    assert "관측됩니다" not in report
    assert "이 항목은 판정 불가입니다" in report


def _write_ledger(root: Path, athletes: list[str], birth_year: int, last_seasons: dict[str, int]) -> None:
    rows: list[dict[str, object]] = []
    for athlete_id in athletes:
        for season in range(birth_year + 11, last_seasons[athlete_id] + 1):
            rows.append({"athlete_id": athlete_id, "season_year": season})
    (root / "race_ledger").mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, schema={"athlete_id": pl.Utf8, "season_year": pl.Int64}).write_parquet(
        root / "race_ledger" / "part-0.parquet"
    )
    pl.DataFrame(
        {
            "athlete_id": athletes,
            "birth_year": [birth_year] * len(athletes),
            "sex": ["남"] * len(athletes),
            "debut_division": ["초등부"] * len(athletes),
        }
    ).write_parquet(root / "athlete_meta.parquet")


def test_build_report_runs_end_to_end(tmp_path: Path) -> None:
    from rating.eval.trajectory import build_report
    from rating.replay.registry import RatingRegistry
    from rating.replay.snapshot import run_id as content_run_id

    birth_year = 2000
    athletes = [f"e{index:03d}" for index in range(40)]
    salt = "test-salt"
    id_numbers = [f"{100000 + index}" for index in range(40)]
    hashed = {
        number: __import__("hashlib").sha256(f"{number}{salt}".encode("utf-8")).hexdigest()[:12]
        for number in id_numbers
    }
    # 앞의 4명을 국가대표로 지정하고, 그 익명 ID를 스냅샷 선수 ID로 씁니다.
    national_numbers = id_numbers[:4]
    athletes = [hashed[number] for number in national_numbers] + athletes[4:]

    snapshot_rows: list[dict[str, object]] = []
    for index, athlete_id in enumerate(athletes):
        for age in (11, 12, 13):
            snapshot_rows.append(
                {
                    "athlete_id": athlete_id,
                    "valid_date": date(birth_year + age, 11, 1),
                    "mu": 30.0 - float(index) * 0.3,
                    "sigma": 3.0,
                    "n_games": 10 + age,
                }
            )
    snapshots = pl.DataFrame(
        snapshot_rows,
        schema={
            "athlete_id": pl.Utf8,
            "valid_date": pl.Date,
            "mu": pl.Float64,
            "sigma": pl.Float64,
            "n_games": pl.Int64,
        },
    )

    registry_root = tmp_path / "rating_runs"
    registry = RatingRegistry(registry_root)
    engine_params = {"engine": "trueskill", "tau": 0.1}
    calibrator_spec = {"method": "platt", "slope": 1.0, "intercept": 0.0}
    run = content_run_id(
        algo_version="rating.replay.v2",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_id="b" * 64,
    )
    registry.begin(
        run_id=run,
        algo_version="rating.replay.v2",
        engine_params=engine_params,
        calibrator_spec=calibrator_spec,
        input_snapshot_id="b" * 64,
        git_sha="test",
    )
    registry.complete(run, snapshots, smoothed_snapshots=snapshots)

    ledger_root = tmp_path / "ledger"
    last_seasons = {athlete_id: (birth_year + 14 if index % 3 == 0 else birth_year + 20) for index, athlete_id in enumerate(athletes)}
    _write_ledger(ledger_root, athletes, birth_year, last_seasons)

    public_path = tmp_path / "public_figures.csv"
    lines = ["idNo,이름,슬러그,출생연도,지정근거,언론보도URL,지정일자,상태"]
    for index, number in enumerate(national_numbers):
        lines.append(
            f"{number},선수{index},athlete-{index},{birth_year},"
            "2026/27 시즌 쇼트트랙 국가대표(연맹 등재),https://example.com,2026-08-09,active"
        )
    public_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report, svg = build_report(
        registry_root=registry_root,
        run_id=run,
        ledger=ledger_root,
        athlete_meta_path=None,
        public_figures=public_path,
        salt=salt,
        ages=(11, 12, 13),
        elementary_ages=(11, 12),
        cohort_birth_years=None,
        resamples=50,
        seed=11,
        svg_path=None,
    )
    assert "# 국가대표 궤적 검증 리포트" in report
    assert "## 두 방향 확률" in report
    assert "사례 04" in report
    assert svg.startswith("<svg")
    assert_no_deterministic_phrases(report)
