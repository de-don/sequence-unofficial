from __future__ import annotations

from .. import endpoints as ep
from ..models import Activity, Category
from ._base import Resource


class Activities(Resource):
    """Workouts (called "activities" by the API)."""

    def list(self, *, skip_widgets: bool = True) -> list[Activity]:
        """All workouts. Experimental: the list body was never captured; items may be partial."""
        return self._c.fetch_list(ep.ACTIVITIES_LIST, params={"skip_widgets": 1 if skip_widgets else None})

    def get(self, activity_id: str) -> Activity:
        """One workout with its exercises and sets."""
        return self._c.fetch(ep.ACTIVITY_GET, path_params={"id": activity_id})

    def categories(self) -> list[Category]:
        return self._c.fetch_list(ep.CATEGORIES_LIST)
