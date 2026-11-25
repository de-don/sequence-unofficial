"""Write safety (disabled by default, dry-run, confirm), experimental warnings, log redaction."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
import respx

from sequence_unofficial import ConfirmationRequired, PreparedRequest, WritesDisabled
from sequence_unofficial.endpoints import Endpoint

from .conftest import FAKE_CSRF, FAKE_PASSWORD, load_fixture, signin_response

# Test-only endpoints: the real registry deliberately contains no write endpoint.
WRITE: Endpoint[Any] = Endpoint("fake_write", "POST", "/api/v1/fake_write", "tests", returns="json")
DELETE: Endpoint[Any] = Endpoint(
    "fake_delete",
    "DELETE",
    "/api/v1/fake/{id}",
    "tests",
    returns="json",
    destructive=True,
    confirm_param="id",
)


def test_writes_are_disabled_by_default(mock: respx.MockRouter, make_client: Any) -> None:
    signin = mock.post("/signin").mock(return_value=signin_response())
    route = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, json={}))
    client = make_client()
    assert client.allow_writes is False
    with pytest.raises(WritesDisabled):
        client.request(WRITE, body={"a": 1})
    assert not route.called and not signin.called  # nothing at all was sent


def test_dry_run_returns_the_request_and_sends_nothing(mock: respx.MockRouter, make_client: Any) -> None:
    signin = mock.post("/signin").mock(return_value=signin_response())
    route = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, json={}))
    client = make_client()  # even with writes disabled a preview is allowed
    prepared = client.request(WRITE, body={"title": "x", "password": "hunter2"}, dry_run=True)
    assert isinstance(prepared, PreparedRequest)
    assert (prepared.method, prepared.url) == ("POST", "/api/v1/fake_write")
    assert prepared.json == {"title": "x", "password": "[REDACTED]"}
    assert prepared.headers["X-CSRF-Token"] == "[REDACTED]"
    assert not route.called and not signin.called


def test_destructive_calls_need_matching_confirm(
    mock: respx.MockRouter, make_client: Any, allow_unbacked_destructive: None
) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    route = mock.delete("/api/v1/fake/42").mock(return_value=httpx.Response(200, json={}))
    client = make_client(allow_writes=True)
    with pytest.raises(ConfirmationRequired):
        client.request(DELETE, path_params={"id": "42"})
    with pytest.raises(ConfirmationRequired):
        client.request(DELETE, path_params={"id": "42"}, confirm="43")
    assert not route.called
    client.request(DELETE, path_params={"id": "42"}, confirm="42")
    assert route.call_count == 1


EXPERIMENTAL: Endpoint[Any] = Endpoint(
    "fake_experimental",
    "GET",
    "/api/v1/fake_experimental",
    "tests",
    returns="json",
    status="experimental",
    note="test only",
)


def test_destructive_dry_run_needs_no_confirm(make_client: Any) -> None:
    prepared = make_client().request(DELETE, path_params={"id": "42"}, dry_run=True)
    assert prepared.url == "/api/v1/fake/42"


def test_experimental_endpoint_logs_a_warning(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    mock.get("/api/v1/fake_experimental").mock(return_value=httpx.Response(200, json=[]))
    with caplog.at_level(logging.WARNING, logger="sequence_unofficial"):
        make_client().request(EXPERIMENTAL)
    assert "experimental" in caplog.text


def test_logs_never_contain_secrets(
    mock: respx.MockRouter, make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    mock.get("/accounts/status").mock(
        return_value=httpx.Response(200, json=load_fixture("get_accounts_status.json")["response"])
    )
    mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, json={}))
    with caplog.at_level(logging.DEBUG, logger="sequence_unofficial"):
        client = make_client(allow_writes=True)
        client.account.status()
        client.request(WRITE, body={"note": "n", "password": "pw-in-body"})
    assert caplog.text  # something was logged...
    for secret in (FAKE_PASSWORD, FAKE_CSRF, "fake-session-1", "pw-in-body"):
        assert secret not in caplog.text


def test_session_and_models_do_not_leak_in_repr(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    mock.get("/accounts/get_preferences").mock(
        return_value=httpx.Response(200, json=load_fixture("get_accounts_get_preferences.json")["response"])
    )
    prefs = make_client().account.preferences()
    assert prefs.user_email == "user@example.com"
    assert "user@example.com" not in repr(prefs) and "user_name" not in repr(prefs)
    assert FAKE_PASSWORD not in repr(make_client().auth.credentials())
