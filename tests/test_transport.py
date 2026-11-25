from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from sequence_unofficial import RateLimited, ServerError, UnexpectedResponse, __version__
from sequence_unofficial import endpoints as ep
from sequence_unofficial._transport import Transport

from .conftest import load_fixture, sent

STATUS = load_fixture("get_accounts_status.json")["response"]


def test_get_is_retried_on_503_with_backoff(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, sleeps: list[float]
) -> None:
    route = mock.get("/accounts/status").mock(
        side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200, json=STATUS)]
    )
    make_client().account.status()
    assert route.call_count == 3
    assert len(sleeps) == 2 and all(s > 0 for s in sleeps)


def test_retry_after_is_honoured(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, sleeps: list[float]
) -> None:
    mock.get("/accounts/status").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json=STATUS)]
    )
    make_client().account.status()
    assert sleeps == [7.0]


def test_retries_are_bounded_then_error_is_typed(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    route = mock.get("/accounts/status").mock(return_value=httpx.Response(503))
    with pytest.raises(ServerError):
        make_client(max_retries=2).account.status()
    assert route.call_count == 3
    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(429))
    with pytest.raises(RateLimited):
        make_client(max_retries=1).dashboard.get()


def test_connection_errors_are_retried_for_get(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    route = mock.get("/accounts/status").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=STATUS)]
    )
    make_client().account.status()
    assert route.call_count == 2


def test_non_get_is_never_retried(mock: respx.MockRouter, sleeps: list[float]) -> None:
    route = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(503))
    t = Transport(
        base_url="https://dashboard.sequence-app.com",
        user_agent="x",
        requests_per_second=None,
        sleep=sleeps.append,
    )
    assert t.send("POST", "/api/v1/fake_write", json={}).status_code == 503
    assert route.call_count == 1 and sleeps == []
    mock.post("/api/v1/boom").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ServerError):
        t.send("POST", "/api/v1/boom", json={})
    t.close()


def test_throttle_spaces_requests() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    with respx.mock(base_url="https://dashboard.sequence-app.com") as m:
        m.get("/x").mock(return_value=httpx.Response(200, json={}))
        t = Transport(
            base_url="https://dashboard.sequence-app.com",
            user_agent="x",
            requests_per_second=2.0,
            sleep=sleep,
            clock=lambda: now[0],
        )
        for _ in range(3):
            t.send("GET", "/x")
        t.close()
    assert slept == [0.5, 0.5]  # first request immediate, then 2 req/s


def test_user_agent_is_honest_and_json_is_requested(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    route = mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    make_client().account.status()
    h = sent(route)[0].headers
    assert h["user-agent"] == f"sequence-unofficial/{__version__} (unofficial client)"
    assert h["accept"] == "application/json"


def test_redirects_are_not_followed(mock: respx.MockRouter, signin: respx.Route, make_client: Any) -> None:
    mock.get("/accounts/status").mock(return_value=httpx.Response(302, headers={"Location": "/elsewhere"}))
    with pytest.raises(UnexpectedResponse):
        make_client().account.status()


def test_html_200_on_get_is_an_error_after_relogin(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    from sequence_unofficial import SessionExpired

    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(200, html="<html/>"))
    with pytest.raises(SessionExpired):
        make_client().dashboard.get()


def test_typed_errors(mock: respx.MockRouter, signin: respx.Route, make_client: Any) -> None:
    from sequence_unofficial import NotFound, ValidationError

    mock.get("/api/v1/activities/missing").mock(return_value=httpx.Response(404, json={}))
    mock.get("/api/v1/activities/bad").mock(return_value=httpx.Response(422, json={"errors": ["x"]}))
    c = make_client()
    with pytest.raises(NotFound):
        c.activities.get("missing")
    with pytest.raises(ValidationError) as ei:
        c.activities.get("bad")
    assert ei.value.body == {"errors": ["x"]}


def test_ids_are_url_quoted(mock: respx.MockRouter, signin: respx.Route, make_client: Any) -> None:
    route = mock.get(url__regex=r".*/api/v1/activities/.*").mock(
        return_value=httpx.Response(200, json={"id": "a"})
    )
    make_client().activities.get("../accounts/status")
    assert sent(route)[0].url.raw_path == b"/api/v1/activities/..%2Faccounts%2Fstatus"
    assert ep.ACTIVITY_GET.path == "/api/v1/activities/{id}"
