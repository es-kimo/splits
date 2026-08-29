import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.ledger.extract import _build_reconstructed_race_id, division_key, resolve_gender, split_division
from rating.ledger.schema import assert_rank_ties_are_consistent


def _race_id_row(category: str, gender: str = "", **overrides: str) -> dict[str, str]:
    row = {
        "meet_id": "202513828",
        "meet_name": "제107회 전국동계체육대회",
        "season_text": "2025",
        "event": "1500M",
        "category": category,
        "gender": gender,
        "distance_text": "1500",
        "round": "결승Final",
        "round_kind": "결승",
        "date": "2025-10-31",
    }
    row.update(overrides)
    return row


class TestSplitDivision:
    @pytest.mark.parametrize(
        ("category", "gender", "expected"),
        [
            ("남자중학부", "", ("남", "중학부")),
            ("여자초등5,6학년", "", ("여", "초등5,6학년")),
            ("남자부", "", ("남", "부")),
            # records_anon.csv는 성별이 별도 컬럼이고 종별에서 성별이 제거돼 있습니다.
            ("중학부", "남", ("남", "중학부")),
            ("일반부", "여", ("여", "일반부")),
            # 두 소스가 같은 부문 키로 수렴해야 합니다.
            ("남자고등부", "", ("남", "고등부")),
            ("고등부", "남", ("남", "고등부")),
        ],
    )
    def test_normalizes_both_sources_to_the_same_shape(self, category, gender, expected):
        assert split_division(category, gender) == expected

    def test_gender_column_wins_over_prefix(self):
        assert resolve_gender("남자중학부", "여") == "여"

    def test_missing_gender_and_category_yields_sentinel(self):
        assert division_key("", "") == "-:-"


class TestReconstructedRaceId:
    def test_divisions_do_not_collapse_into_one_race(self):
        """부문이 다르면 같은 대회/종목/라운드/날짜라도 다른 레이스여야 합니다."""
        middle = _build_reconstructed_race_id(_race_id_row("남자중학부"))
        high = _build_reconstructed_race_id(_race_id_row("남자고등부"))
        assert middle != high

    def test_genders_do_not_collapse_into_one_race(self):
        men = _build_reconstructed_race_id(_race_id_row("남자중학부"))
        women = _build_reconstructed_race_id(_race_id_row("여자중학부"))
        assert men != women

    def test_gender_neutral_category_splits_on_gender_column(self):
        """`고등부`처럼 성별 접두사가 없는 종별도 성별 컬럼으로 갈라져야 합니다."""
        men = _build_reconstructed_race_id(_race_id_row("고등부", gender="남"))
        women = _build_reconstructed_race_id(_race_id_row("고등부", gender="여"))
        assert men != women

    def test_same_division_stays_one_race(self):
        first = _build_reconstructed_race_id(_race_id_row("남자중학부"))
        second = _build_reconstructed_race_id(_race_id_row("남자중학부"))
        assert first == second and first != ""

    def test_division_is_required(self):
        assert _build_reconstructed_race_id(_race_id_row("", gender="")) == ""


def _ledger_row(rank: int, athlete_id: str, time_sec: float | None, race: str = "r1") -> dict[str, object]:
    return {"race_ordering_key": race, "rank": rank, "athlete_id": athlete_id, "time_sec": time_sec}


class TestRankTieInvariant:
    def test_genuine_tie_is_allowed(self):
        """같은 기록으로 공동 순위인 동착은 원천에 실제로 존재합니다."""
        frame = pl.DataFrame(
            [
                _ledger_row(1, "a", 174.1),
                _ledger_row(5, "b", 174.337),
                _ledger_row(5, "c", 174.337),
                _ledger_row(7, "d", 174.350),
            ]
        )
        assert_rank_ties_are_consistent(frame)

    def test_same_rank_with_different_times_is_rejected(self):
        frame = pl.DataFrame([_ledger_row(1, "a", 174.1), _ledger_row(1, "b", 189.4)])
        with pytest.raises(ValueError, match="같은 순위인데 기록이 서로 다릅니다"):
            assert_rank_ties_are_consistent(frame)

    def test_crowded_rank_is_rejected(self):
        """부문 병합의 전형적 신호: 한 순위에 여러 부문의 1위가 몰립니다."""
        frame = pl.DataFrame([_ledger_row(1, f"a{i}", None) for i in range(4)])
        with pytest.raises(ValueError, match="넘는 참가자가 있습니다"):
            assert_rank_ties_are_consistent(frame)

    def test_error_points_at_the_race_key(self):
        frame = pl.DataFrame([_ledger_row(1, "a", 174.1), _ledger_row(1, "b", 189.4)])
        with pytest.raises(ValueError, match="_build_reconstructed_race_id"):
            assert_rank_ties_are_consistent(frame)
