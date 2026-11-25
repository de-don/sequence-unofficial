from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sequence_unofficial.models import Activity, ExerciseLibraryItem, ScheduleDay, WeeklyMetric
from sequence_unofficial.resources.schedules import grid_start

from .conftest import load_fixture

ACTIVITY = load_fixture("get_api_v1_activities_id.json")["response"]


def test_numeric_strings_become_decimals_and_duration_is_a_timedelta() -> None:
    a = Activity.model_validate(ACTIVITY)
    assert a.duration == Decimal("6300000.0")
    assert a.duration_timedelta == timedelta(minutes=105)
    sets = [s for e in a.exercises or [] for s in e.sets or []]
    assert Decimal("5.0") in [s.weight for s in sets]
    assert a.raw["duration"] == "6300000.0"  # the original string is preserved in .raw


def test_unknown_fields_and_new_enum_values_do_not_break_parsing() -> None:
    data = {**ACTIVITY, "brand_new_field": {"x": 1}}
    data["exercises"] = [{**ACTIVITY["exercises"][0], "category": "some_future_category"}]
    a = Activity.model_validate(data)
    assert a.model_extra == {"brand_new_field": {"x": 1}}
    assert a.exercises and a.exercises[0].category == "some_future_category"
    assert a.raw["brand_new_field"] == {"x": 1}


def test_only_id_is_required() -> None:
    assert ExerciseLibraryItem.model_validate({"id": "x"}).name is None
    assert Activity.model_validate({"id": "x"}).duration_timedelta is None


def test_planner_dates_are_dates() -> None:
    day = ScheduleDay.model_validate(load_fixture("get_api_v1_schedules_user_month.json")["response"][0])
    assert day.date == date(2026, 8, 31)
    assert day.total_actual_duration == Decimal(0)


def test_grid_starts_on_the_monday_on_or_before_the_first() -> None:
    assert grid_start(2026, 9) == date(2026, 8, 31)  # the observed sample: Tue 1 Sep -> Mon 31 Aug
    assert grid_start(2026, 11) == date(2026, 10, 26)  # 1 Nov 2026 is a Sunday
    assert grid_start(2026, 6) == date(2026, 6, 1)  # already a Monday
    assert all(grid_start(2026, m).weekday() == 0 for m in range(1, 13))


def test_weekly_metric_epoch_millis_stay_ints() -> None:
    m = WeeklyMetric.model_validate(
        load_fixture("get_api_v1_metrics_activity_magic_number.json")["response"][0]
    )
    assert isinstance(m.date_value, int)
