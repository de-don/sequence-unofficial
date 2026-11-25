"""Regression tests for the v0.1 review: leaks, input validation, write safety, session store, export, CLI."""

from __future__ import annotations

import json
import logging
import os
import stat
import threading
import traceback
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from sequence_unofficial import (
    AuthenticationRequired,
    AuthError,
    InvalidArgument,
    OutcomeUnknown,
    RateLimited,
    ServerError,
    UnexpectedResponse,
)
from sequence_unofficial import cli as cli_module
from sequence_unofficial._transport import Transport, parse_retry_after
from sequence_unofficial.cli import app
from sequence_unofficial.endpoints import Endpoint
from sequence_unofficial.export import _safe_name, _write, export_all  # pyright: ignore[reportPrivateUsage]
from sequence_unofficial.models import SignIn
from sequence_unofficial.redact import redact_headers, redact_json, redact_text
from sequence_unofficial.session_store import SessionStore, StoredSession

from .conftest import FAKE_CSRF, FAKE_EMAIL, FAKE_PASSWORD, load_fixture, sent, signin_response

STATUS = load_fixture("get_accounts_status.json")["response"]
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
REDIRECT = httpx.Response(302, headers={"Location": "/sign-in"})
runner = CliRunner()


# --- redaction -----------------------------------------------------------------------------------
def test_headers_are_redacted_by_pattern_not_by_list() -> None:
    headers = {"X-Custom-CSRF": "s1", "X-Auth-Thing": "s2", "Cookie": "s3", "Accept": "application/json"}
    assert redact_headers(headers) == {
        "X-Custom-CSRF": "[REDACTED]",
        "X-Auth-Thing": "[REDACTED]",
        "Cookie": "[REDACTED]",
        "Accept": "application/json",
    }


def test_text_redaction_catches_prefixed_names_but_not_lookalikes() -> None:
    text = redact_text("authenticity_token=abc&bypass=1&passes=2&_session_id=zzz&password=pw")
    assert "abc" not in text and "zzz" not in text and "=pw" not in text
    assert "bypass=1" in text and "passes=2" in text
    kept = redact_json({"compass": 1, "bypass": 2, "password": "x", "passwd": "y", "_seq_session": "z"})
    assert kept == {
        "compass": 1,
        "bypass": 2,
        "password": "[REDACTED]",
        "passwd": "[REDACTED]",
        "_seq_session": "[REDACTED]",
    }


def test_session_as_a_plain_training_word_is_not_redacted() -> None:
    body = {"session": "Tuesday boulder session", "session_type": "gym", "sessions": [{"session": 1}]}
    assert redact_json(body) == body
    assert redact_json({"session_id": "a", "sessionId": "b", "session_token": "c"}) == {
        "session_id": "[REDACTED]",
        "sessionId": "[REDACTED]",
        "session_token": "[REDACTED]",
    }
    assert redact_text("session=2&_session_id=zzz&session_id=yyy") == (
        "session=2&_session_id=[REDACTED]&session_id=[REDACTED]"
    )


def test_a_configured_csrf_header_name_is_redacted_even_if_it_matches_no_pattern() -> None:
    assert redact_headers({"X-Foo": "s", "Accept": "a"}, ["x-foo"]) == {"X-Foo": "[REDACTED]", "Accept": "a"}


def test_logs_hide_a_custom_csrf_header(
    mock: respx.MockRouter, make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, json={}))
    with caplog.at_level(logging.DEBUG, logger="sequence_unofficial"):
        make_client(allow_writes=True, csrf_header="X-Custom-CSRF").request(WRITE, body={"a": 1})
    assert "x-custom-csrf" in caplog.text.lower()  # the header is mentioned, its value is not
    assert FAKE_CSRF not in caplog.text


def test_logs_hide_a_csrf_header_name_that_matches_no_pattern(
    mock: respx.MockRouter, make_client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, json={}))
    with caplog.at_level(logging.DEBUG, logger="sequence_unofficial"):
        make_client(allow_writes=True, csrf_header="X-Nonce").request(WRITE, body={"a": 1})
    assert "x-nonce" in caplog.text.lower()
    assert FAKE_CSRF not in caplog.text


def test_signin_shape_error_does_not_leak_into_the_traceback(
    mock: respx.MockRouter, make_client: Any
) -> None:
    mock.post("/signin").mock(
        return_value=httpx.Response(200, json={"user": "leak@example.org", "csrf": "csrf-leak-123"})
    )
    with pytest.raises(AuthError) as ei:
        make_client().login()
    text = "".join(traceback.format_exception(ei.value))
    assert "leak@example.org" not in text and "csrf-leak-123" not in text
    assert ei.value.__suppress_context__


def test_model_validation_errors_do_not_echo_the_input() -> None:
    with pytest.raises(ValueError) as ei:
        SignIn.model_validate({"user": "leak@example.org", "csrf": "csrf-leak-123"})
    assert "leak@example.org" not in str(ei.value) and "csrf-leak-123" not in str(ei.value)


def test_unparseable_data_response_does_not_leak_either(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    mock.get("/api/v1/dashboard").mock(
        return_value=httpx.Response(200, json={"upcoming_workouts": "leak@example.org"})
    )
    with pytest.raises(UnexpectedResponse) as ei:
        make_client().dashboard.get()
    assert "leak@example.org" not in "".join(traceback.format_exception(ei.value))


# --- path parameters and the registry --------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", ".", ".."])
def test_dangerous_path_ids_are_rejected_before_anything_is_sent(
    bad: str, mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    with pytest.raises(InvalidArgument):
        make_client().activities.get(bad)
    assert not signin.called


def test_prepare_raises_a_library_error_for_wrong_path_parameters(make_client: Any) -> None:
    from sequence_unofficial import endpoints as ep

    client = make_client()
    with pytest.raises(InvalidArgument):
        client.prepare(ep.ACTIVITY_GET)  # missing {id}
    with pytest.raises(InvalidArgument):
        client.prepare(ep.ACTIVITY_GET, path_params={"id": "1", "other": "2"})
    with pytest.raises(InvalidArgument):
        client.prepare(ep.DASHBOARD, path_params={"id": "1"})


def test_destructive_endpoints_must_name_a_path_placeholder() -> None:
    with pytest.raises(ValueError, match="confirm_param"):
        Endpoint("x", "DELETE", "/api/v1/x/{id}", "tests", destructive=True)
    with pytest.raises(ValueError, match="confirm_param"):
        Endpoint("x", "DELETE", "/api/v1/x/{id}", "tests", destructive=True, confirm_param="ident")
    with pytest.raises(ValueError, match="confirm_param"):
        Endpoint("x", "DELETE", "/api/v1/x", "tests", destructive=True, confirm_param="id")
    with pytest.raises(ValueError, match="GET"):
        Endpoint("x", "GET", "/api/v1/x/{id}", "tests", destructive=True, confirm_param="id")


def test_destructive_calls_fail_closed_without_the_test_switch(
    mock: respx.MockRouter, make_client: Any
) -> None:
    signin = mock.post("/signin").mock(return_value=signin_response())
    route = mock.delete("/api/v1/fake/42").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(NotImplementedError, match="backup"):
        make_client(allow_writes=True).request(DELETE, path_params={"id": "42"}, confirm="42")
    assert not route.called and not signin.called


# --- CSRF on writes ----------------------------------------------------------------------------------
def _store_session(path: Path, *, csrf: str | None) -> None:
    cookie = {"name": "_seq_session", "value": "stored", "domain": "", "path": "/"}
    SessionStore(path).save(StoredSession(email=FAKE_EMAIL, csrf=csrf, cookies=[cookie]))


def test_write_with_a_stored_session_lacking_csrf_logs_in_again_first(
    mock: respx.MockRouter, make_client: Any, session_path: Path
) -> None:
    _store_session(session_path, csrf=None)
    signin = mock.post("/signin").mock(return_value=signin_response(csrf="fresh"))
    write = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, json={}))
    make_client(allow_writes=True).request(WRITE, body={})
    assert signin.call_count == 1
    assert sent(write)[0].headers["x-csrf-token"] == "fresh"


def test_write_without_csrf_and_without_credentials_is_refused(
    mock: respx.MockRouter, make_client: Any, session_path: Path
) -> None:
    _store_session(session_path, csrf=None)
    write = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AuthenticationRequired):
        make_client(allow_writes=True, email=None, password=None).request(WRITE, body={})
    assert not write.called


# --- failed writes: OutcomeUnknown -----------------------------------------------------------------------
def _transport(sleeps: list[float]) -> Transport:
    return Transport(
        base_url="https://dashboard.sequence-app.com",
        user_agent="x",
        requests_per_second=None,
        sleep=sleeps.append,
    )


@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout("t"), httpx.WriteTimeout("t"), httpx.RemoteProtocolError("p")]
)
def test_a_write_that_may_have_been_sent_raises_outcome_unknown(
    exc: Exception, mock: respx.MockRouter, sleeps: list[float]
) -> None:
    route = mock.post("/api/v1/x").mock(side_effect=exc)
    t = _transport(sleeps)
    with pytest.raises(OutcomeUnknown) as ei:
        t.send("POST", "/api/v1/x", json={})
    assert (ei.value.method, ei.value.path) == ("POST", "/api/v1/x")
    assert route.call_count == 1 and sleeps == []  # never retried
    assert not isinstance(ei.value, ServerError)
    t.close()


@pytest.mark.parametrize("exc", [httpx.ConnectError("c"), httpx.ConnectTimeout("c")])
def test_a_write_that_provably_never_left_is_a_plain_connection_error(
    exc: Exception, mock: respx.MockRouter, sleeps: list[float]
) -> None:
    route = mock.post("/api/v1/x").mock(side_effect=exc)
    t = _transport(sleeps)
    with pytest.raises(ServerError):
        t.send("POST", "/api/v1/x", json={})
    assert route.call_count == 1  # and still not retried
    t.close()


def test_get_timeouts_are_retried_then_a_server_error(mock: respx.MockRouter, sleeps: list[float]) -> None:
    route = mock.get("/x").mock(side_effect=httpx.ReadTimeout("t"))
    t = Transport(
        base_url="https://dashboard.sequence-app.com",
        user_agent="x",
        requests_per_second=None,
        max_retries=2,
        sleep=sleeps.append,
    )
    with pytest.raises(ServerError):
        t.send("GET", "/x")
    assert route.call_count == 3 and len(sleeps) == 2
    t.close()


def test_gateway_errors_on_a_write_are_unknown_but_503_is_not(
    mock: respx.MockRouter, make_client: Any
) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    client = make_client(allow_writes=True)
    for status in (502, 504):
        mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(status))
        with pytest.raises(OutcomeUnknown):
            client.request(WRITE, body={})
    mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(503))
    with pytest.raises(ServerError):
        client.request(WRITE, body={})


def test_a_write_is_not_retried_on_503(mock: respx.MockRouter, make_client: Any, sleeps: list[float]) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    route = mock.post("/api/v1/fake_write").mock(return_value=httpx.Response(503))
    with pytest.raises(ServerError):
        make_client(allow_writes=True).request(WRITE, body={})
    assert route.call_count == 1 and sleeps == []


# --- Retry-After and login mapping ---------------------------------------------------------------
def test_retry_after_parses_seconds_and_http_dates() -> None:
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after(None) is None and parse_retry_after("soon") is None
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(future) == pytest.approx(30, abs=2)
    assert parse_retry_after(format_datetime(datetime(2001, 1, 1, tzinfo=timezone.utc), usegmt=True)) == 0.0


def test_http_date_retry_after_is_used_for_the_wait_and_for_the_error(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, sleeps: list[float]
) -> None:
    date_header = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=10), usegmt=True)
    mock.get("/accounts/status").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": date_header}),
            httpx.Response(200, json=STATUS),
        ]
    )
    make_client().account.status()
    assert sleeps and sleeps[0] == pytest.approx(10, abs=2)
    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(429, headers={"Retry-After": date_header}))
    with pytest.raises(RateLimited) as ei:
        make_client(max_retries=0).dashboard.get()
    assert ei.value.retry_after == pytest.approx(10, abs=2)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429, headers={"Retry-After": "5"}), RateLimited),
        (httpx.Response(503), ServerError),
        (httpx.Response(500), ServerError),
        (httpx.Response(403), AuthError),
    ],
)
def test_login_failures_map_to_specific_errors(
    response: httpx.Response, error: type[Exception], mock: respx.MockRouter, make_client: Any
) -> None:
    mock.post("/signin").mock(return_value=response)
    with pytest.raises(error) as ei:
        make_client().login()
    assert (type(ei.value) is AuthError) == (error is AuthError)  # only 403 is a plain AuthError


def test_login_timeout_is_a_server_error_not_outcome_unknown(
    mock: respx.MockRouter, make_client: Any
) -> None:
    mock.post("/signin").mock(side_effect=httpx.ReadTimeout("t"))
    with pytest.raises(ServerError):
        make_client().login()


# --- expiry detection and concurrency ---------------------------------------------------------------------
def test_redirect_to_a_nested_sign_in_path_counts_as_expiry(mock: respx.MockRouter, make_client: Any) -> None:
    signin = mock.post("/signin").mock(return_value=signin_response())
    mock.get("/accounts/status").mock(
        side_effect=[
            httpx.Response(302, headers={"Location": "https://dashboard.sequence-app.com/users/sign_in"}),
            httpx.Response(200, json=STATUS),
        ]
    )
    make_client().account.status()
    assert signin.call_count == 2


def test_two_threads_hitting_expiry_cause_exactly_one_relogin(
    mock: respx.MockRouter, make_client: Any
) -> None:
    signin = mock.post("/signin").mock(side_effect=[signin_response(cookie="a"), signin_response(cookie="b")])
    barrier = threading.Barrier(2, timeout=5)
    calls = [0]
    lock = threading.Lock()

    def status(request: httpx.Request) -> httpx.Response:
        with lock:
            calls[0] += 1
            first_round = calls[0] <= 2
        if first_round:
            barrier.wait()  # both threads have been told "expired" before either logs in again
            return REDIRECT
        return httpx.Response(200, json=STATUS)

    mock.get("/accounts/status").mock(side_effect=status)
    client = make_client()
    client.login()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            client.account.status()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(10)
    assert not errors
    assert signin.call_count == 2  # the explicit login + exactly one re-login


# --- session store --------------------------------------------------------------------------------------
def test_cookie_flags_survive_the_store(mock: respx.MockRouter, make_client: Any, session_path: Path) -> None:
    mock.post("/signin").mock(
        return_value=httpx.Response(
            200,
            json=dict(load_fixture("post_signin.json")["response"], csrf=FAKE_CSRF),
            headers={"Set-Cookie": "_seq_session=abc; Path=/; HttpOnly; Secure; Max-Age=3600"},
        )
    )
    make_client().login()
    saved = json.loads(session_path.read_text())["cookies"][0]
    assert saved["secure"] is True and isinstance(saved["expires"], int)
    reloaded = make_client()
    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    reloaded.account.status()
    cookie = next(iter(reloaded.auth._t.cookies.jar))  # pyright: ignore[reportPrivateUsage]
    assert cookie.secure is True and cookie.expires == saved["expires"]


def test_expired_stored_cookies_are_not_sent(
    mock: respx.MockRouter, make_client: Any, session_path: Path
) -> None:
    cookie = {
        "name": "_seq_session",
        "value": "old",
        "domain": "",
        "path": "/",
        "secure": False,
        "expires": 1,
    }
    SessionStore(session_path).save(StoredSession(email=FAKE_EMAIL, csrf="c", cookies=[cookie]))
    status = mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    make_client().account.status()
    assert "cookie" not in sent(status)[0].headers


def test_a_rotated_session_cookie_is_saved_right_after_the_response(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, session_path: Path
) -> None:
    mock.get("/accounts/status").mock(
        return_value=httpx.Response(200, json=STATUS, headers={"Set-Cookie": "_seq_session=rotated; Path=/"})
    )
    client = make_client()  # close() is never called in this test body
    client.account.status()
    assert "rotated" in session_path.read_text()
    assert signin.call_count == 1


def test_a_failing_session_store_never_masks_the_error_in_flight(
    mock: respx.MockRouter,
    signin: respx.Route,
    make_client: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock.get("/accounts/status").mock(
        return_value=httpx.Response(200, json=STATUS, headers={"Set-Cookie": "_seq_session=rotated; Path=/"})
    )
    client = make_client()
    client.login()

    def broken(self: SessionStore, session: StoredSession) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(SessionStore, "save", broken)
    with (
        caplog.at_level(logging.WARNING, logger="sequence_unofficial"),
        pytest.raises(OutcomeUnknown),
        client,
    ):
        client.account.status()  # the save after this response fails: logged, not raised
        client.auth._saved = []  # pyright: ignore[reportPrivateUsage]  # so that close() tries again
        raise OutcomeUnknown("write may have been applied", "POST", "/x")
    assert "could not save the session" in caplog.text


def test_corrupt_or_foreign_files_are_never_overwritten_or_deleted(tmp_path: Path) -> None:
    for content in ("not json{", "[1, 2]", '{"hello": "world"}', ""):
        path = tmp_path / "precious.txt"
        path.write_text(content)
        store = SessionStore(path)
        assert store.load() is None
        store.save(StoredSession(email="a@example.com", csrf="c", cookies=[]))
        store.clear()
        assert path.read_text() == content


def test_version_mismatch_loads_as_no_session(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    newer = json.dumps(
        {"kind": "sequence-unofficial-session", "version": 99, "cookies": [{"name": "a", "value": "b"}]}
    )
    path.write_text(newer)
    store = SessionStore(path)
    assert store.load() is None
    store.save(StoredSession(email="a@example.com"))  # never downgrade a newer file
    assert path.read_text() == newer
    store.clear()  # it is a (newer) session file of ours, so logout may remove it
    assert not path.exists()


def test_only_files_with_our_marker_or_the_exact_old_layout_count_as_ours(tmp_path: Path) -> None:
    store_path = tmp_path / "s.json"
    store = SessionStore(store_path)
    store.save(StoredSession(email="a@example.com", csrf="c", cookies=[{"name": "n", "value": "v"}]))
    assert json.loads(store_path.read_text())["kind"] == "sequence-unofficial-session"
    assert store.load() is not None
    # an old v1 file without the marker is still read, and replaced by a marked one
    legacy: dict[str, Any] = {
        "version": 1,
        "email": "a@example.com",
        "csrf": "c",
        "cookies": [],
        "saved_at": "",
    }
    store_path.write_text(json.dumps(legacy))
    assert store.load() is not None
    store.save(StoredSession(email="b@example.com"))
    assert json.loads(store_path.read_text())["kind"] == "sequence-unofficial-session"
    # anything else with a version key is somebody else's file (package.json, a lockfile, ...)
    foreign_files: list[dict[str, Any]] = [
        {"version": 1, "name": "my-package", "dependencies": {}},
        {**legacy, "extra": 1},
        {k: v for k, v in legacy.items() if k != "csrf"},
        {"kind": "something-else", "version": 1},
        {"kind": "sequence-unofficial-session", "version": "1"},
        {"version": 2, **{k: v for k, v in legacy.items() if k != "version"}},
    ]
    for foreign in foreign_files:
        content = json.dumps(foreign)
        store_path.write_text(content)
        assert store.load() is None
        store.save(StoredSession(email="a@example.com"))
        store.clear()
        assert store_path.read_text() == content


def test_existing_parent_directory_keeps_its_permissions(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)
    SessionStore(shared / "session.json").save(StoredSession(email="a@example.com"))
    assert stat.S_IMODE(shared.stat().st_mode) == 0o755
    SessionStore(tmp_path / "new" / "session.json").save(StoredSession(email="a@example.com"))
    assert stat.S_IMODE((tmp_path / "new").stat().st_mode) == 0o700


def test_loading_a_world_readable_session_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    store = SessionStore(tmp_path / "s.json")
    store.save(StoredSession(email="a@example.com", cookies=[]))
    store.path.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="sequence_unofficial"):
        assert store.load() is not None
    assert "chmod 600" in caplog.text


# --- export -------------------------------------------------------------------------------------
def test_export_refuses_a_non_empty_directory_and_leaves_it_alone(make_client: Any, tmp_path: Path) -> None:
    out = tmp_path / "home"
    out.mkdir()
    (out / "mine.txt").write_text("keep")
    out.chmod(0o755)
    with pytest.raises(InvalidArgument, match="--force"):
        export_all(make_client(), out)
    assert (out / "mine.txt").read_text() == "keep" and stat.S_IMODE(out.stat().st_mode) == 0o755
    file_target = tmp_path / "afile"
    file_target.write_text("x")
    with pytest.raises(InvalidArgument):
        export_all(make_client(), file_target)


def _mock_export_endpoints(mock: respx.MockRouter, planner: Callable[[str], list[Any]] | None = None) -> None:
    """Every GET answers 404 (recorded as an error) except the account status and, optionally, the planner."""

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts/status":
            return httpx.Response(200, json=STATUS)
        if request.url.path == "/api/v1/schedules/user_month" and planner is not None:
            return httpx.Response(200, json=planner(request.url.params["start_date_of_period"]))
        return httpx.Response(404, json={})

    mock.get(url__regex=r".*").mock(side_effect=answer)


def test_export_into_an_empty_existing_directory_keeps_its_mode_and_force_overwrites_only_its_files(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    _mock_export_endpoints(mock)
    out = tmp_path / "out"
    out.mkdir()
    out.chmod(0o755)
    export_all(make_client(), out, months_back=0, months_ahead=0)
    assert stat.S_IMODE(out.stat().st_mode) == 0o755  # not ours: untouched
    assert stat.S_IMODE((out / "account/status.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((out / "account").stat().st_mode) == 0o700
    with pytest.raises(InvalidArgument):  # no longer empty
        export_all(make_client(), out, months_back=0, months_ahead=0)
    (out / "manifest.json").write_text("old")
    (out / "mine.txt").write_text("keep")
    export_all(make_client(), out, months_back=0, months_ahead=0, force=True)
    assert json.loads((out / "manifest.json").read_text())["counts"]
    assert (out / "mine.txt").read_text() == "keep"


def test_export_all_walks_the_planner_back_until_it_stays_empty(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    day = dict(load_fixture("get_api_v1_schedules_user_month.json")["response"][0], notes=[{"synthetic": 1}])
    _mock_export_endpoints(mock, planner=lambda start: [day] if start == "2026-10-26" else [])
    manifest = export_all(
        make_client(), tmp_path / "all", months_ahead=1, everything=True, today=date(2026, 11, 25)
    )
    # 2026-11 has a note; the six months before it are empty; plus one month ahead
    assert manifest["planner_months"] == [f"2026-{m:02d}" for m in range(5, 13)]


def test_an_authentication_problem_aborts_the_export(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    mock.get("/accounts/status").mock(return_value=httpx.Response(401))
    out = tmp_path / "out"
    with pytest.raises(AuthError):
        export_all(make_client(), out)
    assert not (out / "manifest.json").exists()


def test_unsafe_ids_become_safe_distinct_file_names() -> None:
    assert _safe_name("abc-123_x.y") == "abc-123_x.y"
    names = {_safe_name(i) for i in ("../../etc/passwd", "a/b", "a_b", "..", "", ".")}
    assert len(names) == 6
    assert all("/" not in n and n not in ("", ".", "..") and not n.startswith("..") for n in names)


def test_export_never_writes_through_a_symlink_or_over_a_file(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("precious")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    for overwrite in (False, True):
        with pytest.raises(OSError):
            _write(link, {"a": 1}, overwrite=overwrite)
    assert target.read_text() == "precious"
    existing = tmp_path / "e.json"
    existing.write_text("old")
    with pytest.raises(FileExistsError):
        _write(existing, {}, overwrite=False)
    assert os.path.getsize(existing) == 3


# --- CLI ----------------------------------------------------------------------------------------------------
@pytest.fixture
def cli_client(monkeypatch: pytest.MonkeyPatch, make_client: Any) -> None:
    monkeypatch.setattr(cli_module, "_client", lambda: make_client())


def test_exit_codes_for_unknown_outcome_and_usage_errors(
    mock: respx.MockRouter, signin: respx.Route, cli_client: None
) -> None:
    mock.get("/api/v1/dashboard").mock(side_effect=httpx.ReadTimeout("t"))
    assert runner.invoke(app, ["dashboard"]).exit_code == 1  # a GET: plain server error
    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(404))
    assert runner.invoke(app, ["dashboard"]).exit_code == 1
    assert runner.invoke(app, ["raw", "POST", "/api/v1/dashboard"]).exit_code == 2
    assert runner.invoke(app, ["raw", "GET", "//evil.example/x"]).exit_code == 2


def test_the_cli_maps_outcome_unknown_to_exit_code_3(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise OutcomeUnknown("POST /x: no answer", "POST", "/x")

    monkeypatch.setattr(cli_module, "_client", boom)
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code == 3 and "may have been applied" in result.output


def test_no_prompt_when_stdin_is_not_a_tty(
    mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, session_path: Path
) -> None:
    from sequence_unofficial.cli import _prompt_credentials  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setenv("SEQUENCE_SESSION_FILE", str(session_path))
    assert _prompt_credentials() is None  # CliRunner/pytest: stdin is not a TTY
    mock.post("/signin").mock(return_value=signin_response())
    result = runner.invoke(app, ["dashboard"])  # real _client(): no credentials, no TTY
    assert result.exit_code == 2 and "No valid session" in result.output


def test_json_output_is_the_original_payload(
    mock: respx.MockRouter, signin: respx.Route, cli_client: None
) -> None:
    payload = {**load_fixture("get_api_v1_dashboard.json")["response"], "unknown_future_field": 1}
    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(200, json=payload))
    result = runner.invoke(app, ["dashboard", "--json"])
    assert json.loads(result.output) == payload


def test_export_command_has_force_and_all_flags(
    mock: respx.MockRouter, signin: respx.Route, cli_client: None, tmp_path: Path
) -> None:
    _mock_export_endpoints(mock, planner=lambda start: [])
    out = tmp_path / "e"
    assert runner.invoke(app, ["export", str(out), "--all", "--json"]).exit_code == 0
    again = runner.invoke(app, ["export", str(out)])
    assert again.exit_code == 1 and "--force" in again.output
    assert runner.invoke(app, ["export", str(out), "--force"]).exit_code == 0


def test_cli_login_uses_the_password_from_the_environment_without_prompting(
    mock: respx.MockRouter, signin: respx.Route, monkeypatch: pytest.MonkeyPatch, session_path: Path
) -> None:
    monkeypatch.setenv("SEQUENCE_SESSION_FILE", str(session_path))
    monkeypatch.setenv("SEQUENCE_PASSWORD", FAKE_PASSWORD)
    result = runner.invoke(app, ["login", "--email", FAKE_EMAIL], input="")  # no password on stdin
    assert result.exit_code == 0, result.output
    assert json.loads(sent(signin)[0].content)["password"] == FAKE_PASSWORD


# --- OutcomeUnknown path, NotImplementedError docs, login ---------------------------------------------
def test_a_gateway_error_reports_the_real_path_not_the_template(
    mock: respx.MockRouter, make_client: Any, allow_unbacked_destructive: None
) -> None:
    mock.post("/signin").mock(return_value=signin_response())
    mock.delete("/api/v1/fake/abc").mock(return_value=httpx.Response(504))
    with pytest.raises(OutcomeUnknown) as ei:
        make_client(allow_writes=True).request(DELETE, path_params={"id": "abc"}, confirm="abc")
    assert (ei.value.method, ei.value.path) == ("DELETE", "/api/v1/fake/abc")


def test_not_implemented_error_for_destructive_calls_is_documented_as_intentional() -> None:
    from sequence_unofficial import Sequence, SequenceError

    assert not issubclass(NotImplementedError, SequenceError)
    assert "NotImplementedError" in (Sequence.request.__doc__ or "")
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    assert "NotImplementedError" in readme and "not* a `SequenceError`" in readme


def test_login_uses_the_password_from_the_environment_with_only_an_email(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEQUENCE_PASSWORD", FAKE_PASSWORD)

    def provider() -> Any:
        raise AssertionError("the provider must not be asked when the environment has the password")

    make_client(password=None, credential_provider=provider).login()
    assert json.loads(sent(signin)[0].content) == {"email": FAKE_EMAIL, "password": FAKE_PASSWORD}


def test_explicit_login_signs_in_fresh_even_with_a_saved_session(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, session_path: Path
) -> None:
    _store_session(session_path, csrf="stored-csrf")
    client = make_client()
    client.login()
    assert signin.call_count == 1
    assert json.loads(session_path.read_text())["csrf"] == FAKE_CSRF  # replaced, not the stored one
    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    client.account.status()
    assert signin.call_count == 1  # and the new session is used afterwards


# --- export: failures per step, collisions, symlinks, --all -------------------------------------------
def _export_with_activities(mock: respx.MockRouter, ids: list[str]) -> None:
    mock.get("/api/v1/activities").mock(return_value=httpx.Response(200, json=[{"id": i} for i in ids]))

    def one(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[-1]})

    mock.get(url__regex=r".*/api/v1/activities/.+").mock(side_effect=one)


def test_export_skips_duplicate_ids_and_gives_case_only_collisions_distinct_names(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    _export_with_activities(mock, ["abc", "abc", "ABC"])
    mock.get(url__regex=r".*").mock(return_value=httpx.Response(404, json={}))  # after: first match wins
    manifest = export_all(make_client(), tmp_path / "o", months_back=0, months_ahead=0)
    files = sorted(f.name.lower() for f in (tmp_path / "o" / "activities").iterdir())
    assert len(files) == 2 and len(set(files)) == 2
    assert manifest["counts"]["activity abc"] == 1 and manifest["counts"]["activity ABC"] == 1
    assert not [e for e in manifest["errors"] if e.startswith("activity")]


def test_export_records_a_file_that_cannot_be_written_and_carries_on(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    _mock_export_endpoints(mock)
    out = tmp_path / "o"
    out.mkdir()
    (out / "account").write_text("a file where the account/ directory should go")
    manifest = export_all(make_client(), out, months_back=0, months_ahead=0, force=True)
    assert "status" in manifest["errors"] and "account/status.json" in manifest["errors"]["status"]
    assert (out / "manifest.json").exists()


def test_export_refuses_symlinked_subdirectories(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    _mock_export_endpoints(mock)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = tmp_path / "o"
    out.mkdir()
    (out / "account").symlink_to(elsewhere, target_is_directory=True)
    manifest = export_all(make_client(), out, months_back=0, months_ahead=0, force=True)
    assert list(elsewhere.iterdir()) == []
    assert "symlink" in manifest["errors"]["status"]


def test_export_directory_that_appears_during_start_is_a_usage_error(
    make_client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "race"
    real_mkdir = Path.mkdir

    def racing_mkdir(self: Path, *a: Any, **kw: Any) -> None:
        real_mkdir(self)  # somebody else creates it first
        real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)
    with pytest.raises(InvalidArgument, match="appeared"):
        export_all(make_client(), out)
    monkeypatch.undo()
    blocked = tmp_path / "file"
    blocked.write_text("x")
    with pytest.raises(InvalidArgument, match="cannot create"):
        export_all(make_client(), blocked / "sub")


def test_export_all_does_not_count_failed_months_as_empty(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    day = dict(load_fixture("get_api_v1_schedules_user_month.json")["response"][0], notes=[{"synthetic": 1}])
    failing = {
        "2026-10-26",
        "2026-09-28",
    }  # the grids of Nov and Oct: two failures in a row do not end the walk

    def planner(request: httpx.Request) -> httpx.Response:
        start = request.url.params["start_date_of_period"]
        if start in failing:
            return httpx.Response(503)
        return httpx.Response(200, json=[day] if start == "2026-08-31" else [])  # the September grid

    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    mock.get("/api/v1/schedules/user_month").mock(side_effect=planner)
    mock.get(url__regex=r".*").mock(return_value=httpx.Response(404, json={}))
    manifest = export_all(
        make_client(max_retries=0), tmp_path / "a", months_ahead=0, everything=True, today=date(2026, 11, 25)
    )
    # nov and oct failed (not "empty"), sep has content, then six empty months: aug..mar
    assert manifest["planner_stop_reason"] == "empty_months"
    assert manifest["planner_complete"] is False  # months failed along the way
    assert min(manifest["planner_months"]) == "2026-03"
    assert not {"2026-11", "2026-10"} & set(manifest["planner_months"])


def test_export_all_stops_after_repeated_failures_and_says_so(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=STATUS))
    route = mock.get("/api/v1/schedules/user_month").mock(return_value=httpx.Response(503))
    mock.get(url__regex=r".*").mock(return_value=httpx.Response(404, json={}))
    manifest = export_all(
        make_client(max_retries=0), tmp_path / "f", months_ahead=0, everything=True, today=date(2026, 11, 25)
    )
    assert route.call_count == 3
    assert manifest["planner_stop_reason"] == "errors" and manifest["planner_complete"] is False


def test_export_manifest_records_how_the_planner_walk_ended(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    _mock_export_endpoints(mock, planner=lambda start: [])
    walked = export_all(
        make_client(), tmp_path / "w", months_ahead=0, everything=True, today=date(2026, 11, 25)
    )
    assert (walked["planner_complete"], walked["planner_stop_reason"]) == (True, "empty_months")
    window = export_all(make_client(), tmp_path / "x", months_back=0, months_ahead=0)
    assert (window["planner_complete"], window["planner_stop_reason"]) == (False, "window")
    on_disk = json.loads((tmp_path / "x" / "manifest.json").read_text())
    assert on_disk["planner_stop_reason"] == "window"
