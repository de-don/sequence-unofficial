from __future__ import annotations

from .. import endpoints as ep
from ..models import Dashboard as DashboardModel
from ._base import Resource


class Dashboard(Resource):
    def get(self) -> DashboardModel:
        return self._c.fetch(ep.DASHBOARD)
