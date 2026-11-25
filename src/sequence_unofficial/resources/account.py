from __future__ import annotations

from typing import Any

from .. import endpoints as ep
from ..models import (
    AccountStatus,
    ExperimentalFeatures,
    Preferences,
    Settings,
    StravaStatus,
    TheCragStatus,
)
from ._base import Resource


class Account(Resource):
    """Account state, preferences and integration status."""

    def status(self) -> AccountStatus:
        """Subscription/trial state. Also the cheapest way to check the session is alive."""
        return self._c.fetch(ep.ACCOUNT_STATUS)

    def preferences(self) -> Preferences:
        """User preferences. Contains the account e-mail and name (hidden from ``repr``)."""
        return self._c.fetch(ep.ACCOUNT_PREFERENCES)

    def settings(self) -> Settings:
        return self._c.fetch(ep.ACCOUNT_SETTINGS)

    def experimental_features(self) -> ExperimentalFeatures:
        return self._c.fetch(ep.EXPERIMENTAL_FEATURES)

    def strava_status(self) -> StravaStatus:
        return self._c.fetch(ep.STRAVA_STATUS)

    def the_crag_status(self) -> TheCragStatus:
        return self._c.fetch(ep.THE_CRAG_STATUS)

    def coaching_conversations(self) -> Any:
        """Experimental: plain JSON (only an empty list has been captured)."""
        return self._c.fetch_json(ep.COACHING_CONVERSATIONS)
