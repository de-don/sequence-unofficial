"""The two list endpoints whose bodies were never captured: defensive parsing rules.

The bodies below are SYNTHETIC (built from the detail sample); they only exercise the rules.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from sequence_unofficial import UnexpectedResponse

from .conftest import load_fixture, sent

ACTIVITY = load_fixture("get_api_v1_activities_id.json")["response"]
ITEMS = [e["exercise_library_item"] for e in ACTIVITY["exercises"]]


def test_activities_list_accepts_a_bare_list(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    route = mock.get("/api/v1/activities").mock(return_value=httpx.Response(200, json=[ACTIVITY]))
    result = make_client().activities.list()
    assert [a.id for a in result] == [ACTIVITY["id"]]
    assert sent(route)[0].url.params["skip_widgets"] == "1"


def test_wrapped_list_is_unwrapped_with_a_warning(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    mock.get("/api/v1/activities").mock(return_value=httpx.Response(200, json={"activities": [ACTIVITY]}))
    assert len(make_client().activities.list()) == 1
    assert "wrapped in key 'activities'" in caplog.text


@pytest.mark.parametrize("body", [{"foo": 1}, {"data": [], "items": []}, "text", [{"no_id": 1}]])
def test_unrecognised_shapes_raise_unexpected_response(
    body: Any, mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    mock.get("/api/v1/activities").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(UnexpectedResponse):
        make_client().activities.list()


def test_exercise_filters_are_client_side(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    items = [
        {**ITEMS[0], "name": "Hangboard Repeaters", "custom": False},
        {**ITEMS[1], "name": "my pull", "custom": True},
    ]
    route = mock.get("/api/v1/exercise_library_items").mock(return_value=httpx.Response(200, json=items))
    c = make_client()
    assert len(c.exercises.list()) == 2
    assert [i.name for i in c.exercises.list(custom=True)] == ["my pull"]
    assert [i.name for i in c.exercises.list(search="HANG")] == ["Hangboard Repeaters"]
    assert all(not r.url.params for r in sent(route))  # no invented server-side parameters


def test_metrics_and_planner_send_the_observed_query(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    month = mock.get("/api/v1/schedules/user_month").mock(return_value=httpx.Response(200, json=[]))
    mag = mock.get("/api/v1/metrics/activity_magic_number").mock(return_value=httpx.Response(200, json=[]))
    c = make_client()
    c.schedules.month(2026, 9)
    c.metrics.activity_magic_number("abc", weeks=10)
    assert dict(sent(month)[0].url.params) == {"start_date_of_period": "2026-08-31"}
    assert dict(sent(mag)[0].url.params) == {"activity_id": "abc", "weeks": "10"}


def test_skip_widgets_variant_with_empty_dicts_parses(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    """Live regression (2026-11-25): skip_widgets=1 sends {} for widgets/measures, not lists."""
    body: list[dict[str, Any]] = [{**ACTIVITY, "widgets": {}, "measures": {}}]
    mock.get("/api/v1/activities").mock(return_value=httpx.Response(200, json=body))
    result = make_client().activities.list()
    assert result[0].widgets is None
    assert result[0].measures is None


def test_dashboard_snapshot_live_shapes(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    """Live regression: sessions_completed is an int, session_breakdown an object."""
    body = load_fixture("get_api_v1_dashboard.json")["response"]
    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(200, json=body))
    snap = make_client().dashboard.get().snapshot
    assert snap is not None and isinstance(snap.sessions_completed, int)
    assert snap.session_breakdown is not None and snap.session_breakdown.categories
