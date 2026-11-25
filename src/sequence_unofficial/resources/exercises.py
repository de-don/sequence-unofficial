from __future__ import annotations

from .. import endpoints as ep
from ..models import ExerciseLibraryItem
from ._base import Resource


class Exercises(Resource):
    """The exercise library (built-in and custom exercises)."""

    def list(self, *, custom: bool | None = None, search: str | None = None) -> list[ExerciseLibraryItem]:
        """Experimental endpoint. ``custom`` and ``search`` are filtered client-side (no server
        parameters are known); ``search`` matches the name case-insensitively."""
        items = self._c.fetch_list(ep.EXERCISES_LIST)
        if custom is not None:
            items = [i for i in items if bool(i.custom) == custom]
        if search:
            needle = search.casefold()
            items = [i for i in items if needle in (i.name or "").casefold()]
        return items
