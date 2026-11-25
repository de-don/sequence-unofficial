from __future__ import annotations

from typing import Any

from .. import endpoints as ep
from ..models import WeeklyMetric
from ._base import Resource


class Metrics(Resource):
    """Per-workout metrics. All experimental: shapes are only partly known."""

    def activity_all_time(self, activity_id: str) -> Any:
        return self._c.fetch_json(ep.METRICS_ACTIVITY_ALL_TIME, params={"activity_id": activity_id})

    def activity_list(self, activity_id: str) -> Any:
        return self._c.fetch_json(ep.METRICS_ACTIVITY_LIST, params={"activity_id": activity_id})

    def activity_magic_number(self, activity_id: str, weeks: int = 10) -> list[WeeklyMetric]:
        return self._c.fetch_list(
            ep.METRICS_ACTIVITY_MAGIC_NUMBER, params={"activity_id": activity_id, "weeks": weeks}
        )
