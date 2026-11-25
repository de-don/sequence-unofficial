"""Declarative endpoint registry: the single source of truth for what the client knows.

Adding a captured endpoint = one line here + one wrapper method in ``resources/`` + one fixture.
``tools/gen_docs.py`` renders this registry (plus the samples) into ``docs/api.md``.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from .models import (
    AccountStatus,
    Activity,
    Category,
    CustomTestProgress,
    CustomTestSummary,
    Dashboard,
    ExerciseLibraryItem,
    ExperimentalFeatures,
    Preferences,
    ScheduleDay,
    SequenceModel,
    Settings,
    SignIn,
    StravaStatus,
    TheCragStatus,
    WeeklyMetric,
)

M = TypeVar("M", bound=SequenceModel)

Status = Literal["verified", "experimental"]
Returns = Literal["one", "list", "json"]
VERIFIED_ON = "2026-11-25"  # date of the capture the samples come from


@dataclass(frozen=True)
class Endpoint(Generic[M]):
    """One API operation.

    ``status="verified"``: request and response shape seen in a capture (on ``verified_on``).
    ``status="experimental"``: seen only partially; a warning is logged when it is called.
    ``returns``: ``"one"`` -> ``model``; ``"list"`` -> ``list[model]``; ``"json"`` -> plain JSON.
    """

    name: str
    method: str
    path: str  # may contain {placeholders}
    resource: str  # the client attribute it belongs to; also an accepted list-wrapper key
    model: type[M] | None = None
    returns: Returns = "one"
    query: tuple[str, ...] = ()  # query parameters seen in captures
    status: Status = "verified"
    verified_on: str | None = VERIFIED_ON
    note: str | None = None
    auth: bool = False  # the login call itself: not a "write", never needs a session
    destructive: bool = False  # needs confirm=<value of confirm_param>
    confirm_param: str | None = None
    sample: str | None = None  # "METHOD path" key into docs/samples, defaults to method + path

    def __post_init__(self) -> None:
        if not self.destructive:
            return
        if self.method == "GET":
            raise ValueError(f"{self.name}: a GET endpoint cannot be destructive")
        if self.confirm_param is None or self.confirm_param not in self.placeholders:
            raise ValueError(
                f"{self.name}: destructive endpoints need a confirm_param that is a path placeholder"
            )

    @property
    def placeholders(self) -> frozenset[str]:
        """Names of the ``{placeholders}`` in ``path``."""
        return frozenset(name for _, name, _, _ in string.Formatter().parse(self.path) if name)

    @property
    def is_write(self) -> bool:
        return self.method != "GET" and not self.auth

    @property
    def sample_key(self) -> str:
        return self.sample or f"{self.method} {self.path}"


def _ep(name: str, path: str, resource: str, model: type[M] | None = None, **kw: Any) -> Endpoint[M]:
    return Endpoint(name, "GET", path, resource, model, **kw)


SIGNIN = Endpoint("signin", "POST", "/signin", "account", SignIn, auth=True)
ACCOUNT_STATUS = _ep("account_status", "/accounts/status", "account", AccountStatus)
ACCOUNT_PREFERENCES = _ep("account_preferences", "/accounts/get_preferences", "account", Preferences)
ACCOUNT_SETTINGS = _ep("account_settings", "/accounts/get_settings", "account", Settings)
EXPERIMENTAL_FEATURES = _ep(
    "experimental_features", "/api/v1/experimental_features", "account", ExperimentalFeatures
)
STRAVA_STATUS = _ep("strava_status", "/api/v1/strava/status", "account", StravaStatus)
THE_CRAG_STATUS = _ep("the_crag_status", "/api/v1/the_crag/status", "account", TheCragStatus)
COACHING_CONVERSATIONS: Endpoint[Any] = _ep(
    "coaching_conversations",
    "/api/v1/coaching/messages/conversations",
    "account",
    returns="json",
    status="experimental",
    note="HTTP 200 observed live on 2026-11-25, but the body was empty ([]), so its shape is unknown",
)
ACTIVITIES_LIST = _ep(
    "activities_list",
    "/api/v1/activities",
    "activities",
    Activity,
    returns="list",
    query=("skip_widgets",),
    status="verified",
    verified_on=VERIFIED_ON,
    note="full response observed live on 2026-11-25; skip_widgets=1 sends empty dicts for "
    "widgets/measures instead of lists",
)
ACTIVITY_GET = _ep("activity_get", "/api/v1/activities/{id}", "activities", Activity)
CATEGORIES_LIST = _ep("categories_list", "/api/v1/categories", "categories", Category, returns="list")
EXERCISES_LIST = _ep(
    "exercises_list",
    "/api/v1/exercise_library_items",
    "exercises",
    ExerciseLibraryItem,
    returns="list",
    status="verified",
    verified_on=VERIFIED_ON,
    note="full response observed live on 2026-11-25; items parse as ExerciseLibraryItem; "
    "no pagination parameters known",
)
SCHEDULES_USER_MONTH = _ep(
    "schedules_user_month",
    "/api/v1/schedules/user_month",
    "schedules",
    ScheduleDay,
    returns="list",
    query=("start_date_of_period",),
    note="start_date_of_period looks like the Monday of the first grid week; grid length unverified",
)
TESTS_LIST = _ep("tests_list", "/api/v1/custom_test_progress", "tests", CustomTestSummary, returns="list")
TEST_PROGRESS = _ep(
    "test_progress", "/api/v1/custom_test_templates/{id}/progress", "tests", CustomTestProgress
)
DASHBOARD = _ep("dashboard", "/api/v1/dashboard", "dashboard", Dashboard)
METRICS_ACTIVITY_ALL_TIME: Endpoint[Any] = _ep(
    "metrics_activity_all_time",
    "/api/v1/metrics/activity_all_time",
    "metrics",
    returns="json",
    query=("activity_id",),
    status="experimental",
    note="HTTP 200 observed live on 2026-11-25, but the body was empty ({}), so its shape is unknown",
)
METRICS_ACTIVITY_LIST: Endpoint[Any] = _ep(
    "metrics_activity_list",
    "/api/v1/metrics/activity_list",
    "metrics",
    returns="json",
    query=("activity_id",),
    status="experimental",
    note="HTTP 200 observed live on 2026-11-25, but the body was empty ([]), so its shape is unknown",
)
METRICS_ACTIVITY_MAGIC_NUMBER = _ep(
    "metrics_activity_magic_number",
    "/api/v1/metrics/activity_magic_number",
    "metrics",
    WeeklyMetric,
    returns="list",
    query=("activity_id", "weeks"),
    status="verified",
    verified_on=VERIFIED_ON,
    note="observed live on 2026-11-25; 2-item sample, field meanings inferred from their names",
)

ENDPOINTS: tuple[Endpoint[Any], ...] = (
    SIGNIN,
    ACCOUNT_STATUS,
    ACCOUNT_PREFERENCES,
    ACCOUNT_SETTINGS,
    EXPERIMENTAL_FEATURES,
    STRAVA_STATUS,
    THE_CRAG_STATUS,
    COACHING_CONVERSATIONS,
    ACTIVITIES_LIST,
    ACTIVITY_GET,
    CATEGORIES_LIST,
    EXERCISES_LIST,
    SCHEDULES_USER_MONTH,
    TESTS_LIST,
    TEST_PROGRESS,
    DASHBOARD,
    METRICS_ACTIVITY_ALL_TIME,
    METRICS_ACTIVITY_LIST,
    METRICS_ACTIVITY_MAGIC_NUMBER,
)
