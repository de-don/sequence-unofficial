"""The :class:`Sequence` client: registry-driven requests with auth, write guards and parsing."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar, cast
from urllib.parse import quote, urlsplit

import httpx
from pydantic import ValidationError as PydanticValidationError

from . import __version__
from ._transport import Transport, parse_retry_after
from .auth import Auth, CredentialProvider
from .endpoints import SIGNIN, Endpoint
from .errors import (
    AuthError,
    ConfirmationRequired,
    InvalidArgument,
    NotFound,
    OutcomeUnknown,
    RateLimited,
    ServerError,
    SessionExpired,
    UnexpectedResponse,
    ValidationError,
    WritesDisabled,
)
from .models import SequenceModel, SignIn
from .redact import REDACTED, redact_json
from .resources import Account, Activities, Dashboard, Exercises, Metrics, Schedules, Tests
from .session_store import SessionStore

log = logging.getLogger("sequence_unofficial")
DEFAULT_BASE_URL = "https://dashboard.sequence-app.com"
M = TypeVar("M", bound=SequenceModel)
_WRAP_KEYS = ("data", "items", "results")
_SIGN_IN_SEGMENTS = ("sign-in", "signin", "sign_in", "login")  # last path segment: /users/sign_in too
_ALLOW_UNBACKED_DESTRUCTIVE = False
"""Fail-closed switch: destructive endpoints are refused until backup-before-delete exists.

Deliberately not a parameter, an ``Endpoint`` field or public API; only the tests flip it.
"""


@dataclass(frozen=True)
class PreparedRequest:
    """What a call would send (returned by ``dry_run=True``). Secrets are already redacted."""

    method: str
    url: str
    params: dict[str, Any] = field(default_factory=lambda: {})
    json: Any = None
    headers: dict[str, str] = field(default_factory=lambda: {})


def _expired(response: httpx.Response) -> str | None:
    """ "rejected" = the server refused before doing anything; "ambiguous" = HTML where JSON is expected."""
    if response.request.url.path == SIGNIN.path:
        return None  # never treat the login call itself as an expired session
    if response.status_code == 401:
        return "rejected"
    if response.status_code in (301, 302, 303, 307, 308):
        location = urlsplit(str(response.headers.get("location", ""))).path.rstrip("/")
        return "rejected" if location.rsplit("/", 1)[-1] in _SIGN_IN_SEGMENTS else None
    if response.status_code == 200 and response.headers.get("content-type", "").startswith("text/html"):
        return "ambiguous"
    return None


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


class Sequence:
    """Client for one Sequence account. Use one instance per thread (or share it: re-login is locked).

    Writes are off unless ``allow_writes=True``. ``csrf_header`` is **unverified** (no write has been
    captured yet): ``X-CSRF-Token`` is the common Rails default.
    """

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        allow_writes: bool = False,
        session_path: Path | None = None,
        persist_session: bool = True,
        credential_provider: CredentialProvider | None = None,
        csrf_header: str = "X-CSRF-Token",
        requests_per_second: float | None = 2.0,
        max_retries: int = 3,
        timeout: float = 30.0,
        user_agent: str | None = None,
        replay_writes_after_reauth: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.allow_writes = allow_writes
        self.csrf_header = csrf_header
        self.replay_writes_after_reauth = replay_writes_after_reauth
        self._transport = Transport(
            base_url=base_url,
            user_agent=user_agent or f"sequence-unofficial/{__version__} (unofficial client)",
            secret_headers=(csrf_header,),
            timeout=timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            sleep=sleep,
        )
        self.auth = Auth(
            self._transport,
            SessionStore(session_path) if persist_session else None,
            email=email,
            password=password,
            provider=credential_provider,
        )
        self.account = Account(self)
        self.activities = Activities(self)
        self.exercises = Exercises(self)
        self.schedules = Schedules(self)
        self.tests = Tests(self)
        self.dashboard = Dashboard(self)
        self.metrics = Metrics(self)

    def __enter__(self) -> Sequence:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Save a rotated cookie (a failure is only logged) and release the connection pool."""
        try:
            self.auth.save_if_changed()
        finally:
            self._transport.close()

    # --- session ------------------------------------------------------------------------------
    @property
    def session_path(self) -> Path | None:
        """Where the session is persisted (``None`` if persistence is off)."""
        return self.auth.store_path

    def login(self) -> SignIn:
        """Log in now (otherwise the first request logs in lazily) and persist the session."""
        return self.auth.login()

    def logout(self) -> None:
        """Forget the session locally (no sign-out endpoint has been observed)."""
        self.auth.logout()

    # --- requests -----------------------------------------------------------------------------
    def prepare(
        self,
        ep: Endpoint[Any],
        *,
        path_params: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> PreparedRequest:
        given = dict(path_params or {})
        if frozenset(given) != ep.placeholders:
            raise InvalidArgument(f"{ep.name}: path parameters must be exactly {sorted(ep.placeholders)}")
        for key, value in given.items():
            # "", "." and ".." survive quoting and would be resolved as path segments by httpx.
            if str(value) in ("", ".", ".."):
                raise InvalidArgument(f"{ep.name}: invalid value for path parameter {key!r}")
        path = ep.path.format(**{k: quote(str(v), safe="") for k, v in given.items()})
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {"Accept": "application/json"}
        if ep.is_write:
            headers[self.csrf_header] = REDACTED
        return PreparedRequest(ep.method, path, clean, redact_json(body), headers)

    def request(
        self,
        ep: Endpoint[Any],
        *,
        path_params: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        dry_run: bool = False,
        confirm: str | None = None,
    ) -> Any:
        """Call a registered endpoint and parse the answer according to ``ep.returns``.

        ``dry_run=True`` returns the :class:`PreparedRequest` and sends nothing (works even with
        writes disabled). Writes need ``allow_writes=True``; destructive ones also ``confirm=``
        equal to the value of the endpoint's ``confirm_param``.

        Raises :class:`SequenceError` subclasses for everything the server or the caller can cause.
        ``NotImplementedError`` is deliberately **not** one of them: it means "this destructive
        endpoint is refused until backup-before-delete exists" (a programming-time condition), so
        it is not caught by ``except SequenceError`` nor by the CLI's error handler.
        """
        prepared = self.prepare(ep, path_params=path_params, params=params, body=body)
        if dry_run:
            return prepared
        if ep.is_write:
            if not self.allow_writes:
                raise WritesDisabled(
                    f"{ep.name}: writes are disabled; create the client with allow_writes=True "
                    "(use dry_run=True to preview)."
                )
            if ep.destructive:
                if not _ALLOW_UNBACKED_DESTRUCTIVE:
                    raise NotImplementedError(
                        f"{ep.name}: destructive calls are refused until backup-before-delete is implemented"
                    )
                expected = str((path_params or {})[ep.confirm_param or ""])
                if confirm is None or str(confirm) != expected:
                    raise ConfirmationRequired(
                        f"{ep.name} is destructive: pass confirm={expected!r} to proceed."
                    )
        if ep.status == "experimental":
            log.warning("endpoint %s is experimental: %s", ep.name, ep.note or "not fully verified")
        response = self._send(ep, prepared, json_body=body)
        return self._parse(ep, response)

    def _send(self, ep: Endpoint[Any], prepared: PreparedRequest, json_body: Any) -> httpx.Response:
        self.auth.ensure()
        generation = self.auth.generation
        if ep.is_write and not self.auth.csrf:  # e.g. an old session file without a token
            self.auth.relogin(generation)
            if not self.auth.csrf:
                raise AuthError(f"{ep.name}: no CSRF token available; refusing to send a write without it.")
            generation = self.auth.generation
        response = self._send_once(ep, prepared, json_body)
        signal = _expired(response)
        if signal is None:
            return response
        # The session is gone. A write is replayed only if the server provably did not handle it.
        if ep.is_write and (signal != "rejected" or not self.replay_writes_after_reauth):
            raise SessionExpired(f"{ep.name}: session expired; the write was not replayed.")
        self.auth.relogin(generation)  # may raise AuthenticationRequired / InvalidCredentials
        response = self._send_once(ep, prepared, json_body)
        if _expired(response):
            raise SessionExpired(f"{ep.name}: still not authenticated after logging in again.")
        return response

    def _send_once(self, ep: Endpoint[Any], prepared: PreparedRequest, json_body: Any) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if ep.is_write and self.auth.csrf:
            headers[self.csrf_header] = self.auth.csrf
        response = self._transport.send(
            ep.method, prepared.url, params=prepared.params or None, json=json_body, headers=headers
        )
        self.auth.save_if_changed()  # a rotated cookie must survive even if close() is never called
        return response

    def _parse(self, ep: Endpoint[Any], response: httpx.Response) -> Any:
        code = response.status_code
        where = f"{ep.method} {ep.path}"
        if code == 404:
            raise NotFound(f"{where}: not found")
        if code == 422:
            raise ValidationError(f"{where}: rejected (422)", _body(response))
        if code == 429:
            raise RateLimited(
                f"{where}: rate limited", parse_retry_after(response.headers.get("retry-after"))
            )
        if ep.is_write and code in (502, 504):  # a gateway failure says nothing about the backend
            raise OutcomeUnknown(
                f"{where}: gateway error {code}; the server may have handled it",
                ep.method,
                response.request.url.path,  # the real path (ids filled in), not the template
            )
        if code >= 500:
            raise ServerError(f"{where}: server error {code}")
        if not 200 <= code < 300:
            raise UnexpectedResponse(f"{where}: unexpected HTTP {code}", code, _body(response))
        if not response.content:
            return None
        if "json" not in response.headers.get("content-type", "json"):
            raise UnexpectedResponse(f"{where}: expected JSON, got {response.headers['content-type']}", code)
        try:
            data = response.json()
        except ValueError as exc:
            raise UnexpectedResponse(f"{where}: invalid JSON", code) from exc
        if ep.returns == "json" or ep.model is None:
            return data
        try:
            if ep.returns == "one":
                return ep.model.model_validate(data)
            return self._parse_list(ep, data)
        except PydanticValidationError:
            # ``from None``: the pydantic error would otherwise chain into tracebacks and logs.
            raise UnexpectedResponse(
                f"{where}: response does not match {ep.model.__name__}", code, data
            ) from None

    @staticmethod
    def _parse_list(ep: Endpoint[Any], data: Any) -> list[Any]:
        """A bare list, or a dict wrapping exactly one list under a known key (logged as a warning)."""
        if isinstance(data, dict):
            d = cast(dict[str, Any], data)
            keys = [k for k in (*_WRAP_KEYS, ep.resource) if isinstance(d.get(k), list)]
            if len(keys) != 1:
                raise UnexpectedResponse(f"{ep.method} {ep.path}: expected a list", None, data)
            log.warning("%s: list wrapped in key %r; please report this shape", ep.name, keys[0])
            data = d[keys[0]]
        if not isinstance(data, list):
            raise UnexpectedResponse(f"{ep.method} {ep.path}: expected a list", None, data)
        assert ep.model is not None
        return [ep.model.model_validate(item) for item in cast(list[Any], data)]

    # --- typed helpers used by the resources -----------------------------------------------------
    def fetch(self, ep: Endpoint[M], **kw: Any) -> M:
        return cast(M, self.request(ep, **kw))

    def fetch_list(self, ep: Endpoint[M], **kw: Any) -> list[M]:
        return cast("list[M]", self.request(ep, **kw))

    def fetch_json(self, ep: Endpoint[Any], **kw: Any) -> Any:
        return self.request(ep, **kw)
