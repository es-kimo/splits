import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.eval.backtest import _build_schedule, _period_key
from rating.eval.baselines import RaceObservation, RaceParticipant


def _race(race_id: str, day: int, meet_id: str, month: int = 1) -> RaceObservation:
    return RaceObservation(
        race_id=race_id,
        race_date=date(2025, month, day),
        meet_id=meet_id,
        season_year=2024,
        event="500M",
        round_class="final",
        grade_text="5",
        gender="남",
        participants=(
            RaceParticipant(athlete_id="a1", rank=1, status="FIN", time_sec=43.0),
            RaceParticipant(athlete_id="a2", rank=2, status="FIN", time_sec=44.0),
        ),
    )


class TestSchedule:
    def test_month_period_still_batches_model_updates(self):
        """모델은 rating period 경계에서 한 번만 갱신됩니다."""
        races = [_race("r1", 5, "m1"), _race("r2", 20, "m2")]
        steps = _build_schedule(races, races, "month")
        assert len(steps) == 1
        assert len(steps[0].train_races) == 2

    def test_month_period_keeps_baselines_on_meet_granularity(self):
        """같은 달이라도 베이스라인은 대회별로 나뉘어 전진합니다."""
        races = [_race("r1", 5, "m1"), _race("r2", 20, "m2")]
        steps = _build_schedule(races, races, "month")
        assert len(steps[0].eval_meets) == 2

    def test_meet_period_gives_one_meet_per_step(self):
        races = [_race("r1", 5, "m1"), _race("r2", 20, "m2")]
        steps = _build_schedule(races, races, "meet")
        assert len(steps) == 2
        assert all(len(step.eval_meets) == 1 for step in steps)

    def test_steps_are_chronological(self):
        races = [_race("r2", 20, "m2", month=3), _race("r1", 5, "m1", month=1)]
        steps = _build_schedule(races, races, "meet")
        assert [step.period_key for step in steps] == sorted(step.period_key for step in steps)

    def test_meets_within_a_step_are_chronological(self):
        races = [_race("r3", 25, "m3"), _race("r1", 5, "m1"), _race("r2", 20, "m2")]
        steps = _build_schedule(races, races, "month")
        days = [meet[0].race_date.day for meet in steps[0].eval_meets]
        assert days == [5, 20, 25]

    def test_training_races_absent_from_the_eval_set_still_get_a_step(self):
        """정책이 더 많은 레이스를 학습에 넣어도 그 레이스로 평가하지는 않습니다."""
        eval_races = [_race("r1", 5, "m1")]
        train_races = [_race("r1", 5, "m1"), _race("r2", 20, "m2")]
        steps = _build_schedule(train_races, eval_races, "meet")
        assert len(steps) == 2
        evaluated = sum(len(step.eval_meets) for step in steps)
        trained = sum(len(step.train_races) for step in steps)
        assert (evaluated, trained) == (1, 2)

    def test_eval_meets_never_come_from_the_training_ledger(self):
        eval_races = [_race("r1", 5, "m1")]
        train_races = [_race("r2", 20, "m2")]
        steps = _build_schedule(train_races, eval_races, "meet")
        eval_ids = {race.race_id for step in steps for meet in step.eval_meets for race in meet}
        assert eval_ids == {"r1"}

    def test_period_key_matches_the_schedule_grouping(self):
        race = _race("r1", 5, "m1")
        assert _period_key(race, "month") == "2025-01"
        assert _period_key(race, "meet") == "2025-01-05|m1"
