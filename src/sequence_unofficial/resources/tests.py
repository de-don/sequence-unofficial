from __future__ import annotations

from .. import endpoints as ep
from ..models import CustomTestProgress, CustomTestSummary
from ._base import Resource


class Tests(Resource):
    """Custom tests (templates and their results)."""

    def list(self) -> list[CustomTestSummary]:
        return self._c.fetch_list(ep.TESTS_LIST)

    def progress(self, template_id: str) -> CustomTestProgress:
        return self._c.fetch(ep.TEST_PROGRESS, path_params={"id": template_id})
