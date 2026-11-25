"""Thin typed wrappers around the endpoint registry, one class per area."""

from .account import Account
from .activities import Activities
from .dashboard import Dashboard
from .exercises import Exercises
from .metrics import Metrics
from .schedules import Schedules
from .tests import Tests

__all__ = ["Account", "Activities", "Dashboard", "Exercises", "Metrics", "Schedules", "Tests"]
