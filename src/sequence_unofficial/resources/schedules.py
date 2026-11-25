from __future__ import annotations

from datetime import date, timedelta

from .. import endpoints as ep
from ..models import ScheduleDay
from ._base import Resource


def grid_start(year: int, month: int) -> date:
    """Monday on or before the 1st: where the planner grid for that month starts (inferred)."""
    first = date(year, month, 1)
    return first - timedelta(days=first.weekday())


class Schedules(Resource):
    """The planner."""

    def user_month(self, start_date_of_period: date) -> list[ScheduleDay]:
        """Raw planner call: the days of the grid starting at ``start_date_of_period``."""
        return self._c.fetch_list(
            ep.SCHEDULES_USER_MONTH, params={"start_date_of_period": start_date_of_period.isoformat()}
        )

    def month(self, year: int, month: int) -> list[ScheduleDay]:
        """Planner grid for a month (it may include days of the neighbouring months)."""
        return self.user_month(grid_start(year, month))
