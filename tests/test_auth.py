"""Login, session persistence, expiry detection, re-login and replay."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from sequence_unofficial import (
    AuthenticationRequired,
    InvalidCredentials,
    SessionExpired,
)
from sequence_unofficial import endpoints as ep
from sequence_unofficial.endpoints import Endpoint

from .conftest import FAKE_CSRF, FAKE_EMAIL, FAKE_PASSWORD, load_fixture, sent, signin_response

STATUS = load_fixture("get_accounts_status.json")["response"]
# A write endpoint that exists ONLY in tests: the real registry has no write endpoints yet.
FAKE_WRITE: Endpoint[Any] = Endpoint("fake_write", "POST", "/api/v1/fake_write", "tests", returns="json")
REDIRECT = httpx.Response(302, headers={"Location": "https://dashboard.sequence-app.com/sign-in"})


def test_lazy_login_then_session_is_persisted_safely(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, session_path: Path
) -> None:
    status = mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    client = make_client()
    assert not signin.called  # nothing is sent until the first request
    assert client.account.status().subscribed is False
    assert signin.call_count == 1 and status.call_count == 1
    # the login body is what the app sends; the password is not stored anywhere on disk
    assert json.loads(sent(signin)[0].content) == {"email": FAKE_EMAIL, "password": FAKE_PASSWORD}
    raw = session_path.read_text()
    assert FAKE_PASSWORD not in raw
    data = json.loads(raw)
    assert data["csrf"] == FAKE_CSRF and data["email"] == FAKE_EMAIL
    assert stat.S_IMODE(session_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(session_path.parent.stat().st_mode) == 0o700
    assert "_seq_session=fake-session-1" in sent(status)[0].headers["cookie"]


def test_stored_session_is_reused_without_login(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    make_client().account.status()
    assert signin.call_count == 1
    second = make_client()  # new process, same session file
    second.account.status()
    assert signin.call_count == 1


def test_stored_session_of_another_account_is_ignored(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    make_client().account.status()
    make_client(email="someone.else@example.com").account.status()
    assert signin.call_count == 2


def test_invalid_credentials(mock: respx.MockRouter, make_client: Any, session_path: Path) -> None:
    mock.post("/signin").mock(return_value=httpx.Response(401, json={"error": "nope"}))
    with pytest.raises(InvalidCredentials):
        make_client().account.status()
    assert not session_path.exists()


def test_signin_without_csrf_is_an_auth_error(mock: respx.MockRouter, make_client: Any) -> None:
    from sequence_unofficial import AuthError

    mock.post("/signin").mock(return_value=httpx.Response(200, json={"needs_otp": True}))
    with pytest.raises(AuthError, match="2FA"):
        make_client().login()


@pytest.mark.parametrize(
    "expired",
    [
        httpx.Response(302, headers={"Location": "/sign-in"}),
        httpx.Response(401),
        httpx.Response(200, html="<html>Sign in</html>"),
    ],
    ids=["redirect", "401", "html"],
)
def test_expired_get_relogs_in_once_and_replays(
    expired: httpx.Response, mock: respx.MockRouter, make_client: Any, session_path: Path
) -> None:
    signin = mock.post("/signin").mock(
        side_effect=[signin_response(cookie="old"), signin_response(csrf="csrf-2", cookie="new")]
    )
    status = mock.get("/accounts/status").mock(side_effect=[expired, httpx.Response(200, json=STATUS)])
    client = make_client()
    assert client.account.status().valid is True
    assert signin.call_count == 2 and status.call_count == 2
    assert "_seq_session=new" in sent(status)[1].headers["cookie"]
    assert json.loads(session_path.read_text())["csrf"] == "csrf-2"  # the CSRF token was kept up to date


def test_replay_is_attempted_only_once(mock: respx.MockRouter, signin: respx.Route, make_client: Any) -> None:
    status = mock.get("/accounts/status").mock(return_value=REDIRECT)
    with pytest.raises(SessionExpired):
        make_client().account.status()
    assert status.call_count == 2 and signin.call_count == 2


def test_redirect_elsewhere_or_403_do_not_trigger_relogin(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    from sequence_unofficial import UnexpectedResponse

    mock.get("/accounts/status").mock(return_value=httpx.Response(403, json={}))
    with pytest.raises(UnexpectedResponse):
        make_client().account.status()
    assert signin.call_count == 1  # only the initial login


def test_no_credentials_at_expiry_raises_and_drops_dead_session(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, session_path: Path
) -> None:
    mock.get("/accounts/status").mock(side_effect=[httpx.Response(200, json=STATUS), REDIRECT])
    make_client().account.status()
    assert session_path.exists()
    offline = make_client(email=None, password=None)  # loads the stored session, has no credentials
    with pytest.raises(AuthenticationRequired):
        offline.account.status()
    assert not session_path.exists()


def test_credential_provider_is_used_as_last_resort(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    from sequence_unofficial.auth import Credentials

    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    calls: list[int] = []

    def provider() -> Credentials:
        calls.append(1)
        return Credentials(FAKE_EMAIL, FAKE_PASSWORD)

    make_client(email=None, password=None, credential_provider=provider).account.status()
    assert calls == [1]


def test_env_credentials(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEQUENCE_EMAIL", FAKE_EMAIL)
    monkeypatch.setenv("SEQUENCE_PASSWORD", FAKE_PASSWORD)
    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    make_client(email=None, password=None).account.status()
    assert json.loads(sent(signin)[0].content)["email"] == FAKE_EMAIL


# --- writes after expiry (synthetic endpoint, writes enabled) -------------------------------------
def test_write_rejected_before_handler_is_replayed_with_new_csrf(
    mock: respx.MockRouter, make_client: Any
) -> None:
    mock.post("/signin").mock(side_effect=[signin_response(csrf="csrf-1"), signin_response(csrf="csrf-2")])
    write = mock.post("/api/v1/fake_write").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={})]
    )
    client = make_client(allow_writes=True)
    client.request(FAKE_WRITE, body={"x": 1})
    assert [r.headers["x-csrf-token"] for r in sent(write)] == ["csrf-1", "csrf-2"]


def test_write_with_ambiguous_expiry_is_not_replayed(mock: respx.MockRouter, make_client: Any) -> None:
    signin = mock.post("/signin").mock(return_value=signin_response())
    write = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, html="<html/>"))
    with pytest.raises(SessionExpired):
        make_client(allow_writes=True).request(FAKE_WRITE, body={})
    assert write.call_count == 1 and signin.call_count == 1


def test_write_replay_can_be_switched_off(mock: respx.MockRouter, make_client: Any) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    write = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(401))
    with pytest.raises(SessionExpired):
        make_client(allow_writes=True, replay_writes_after_reauth=False).request(FAKE_WRITE, body={})
    assert write.call_count == 1


def test_csrf_header_is_configurable_and_only_on_writes(mock: respx.MockRouter, make_client: Any) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    get = mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    write = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, json={}))
    client = make_client(allow_writes=True, csrf_header="X-Custom-CSRF")
    client.account.status()
    client.request(FAKE_WRITE, body={})
    assert "x-custom-csrf" not in sent(get)[0].headers
    assert sent(write)[0].headers["x-custom-csrf"] == FAKE_CSRF


def test_logout_removes_session_file(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, session_path: Path
) -> None:
    client = make_client()
    client.login()
    assert session_path.exists()
    client.logout()
    assert not session_path.exists()


def test_registry_has_no_write_endpoints() -> None:
    assert not any(e.is_write for e in ep.ENDPOINTS)
