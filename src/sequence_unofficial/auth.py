"""Credentials, login, session persistence and re-login (serialised by a lock)."""

from __future__ import annotations

import importlib
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError

from ._transport import Transport, parse_retry_after
from .endpoints import SIGNIN
from .errors import (
    AuthenticationRequired,
    AuthError,
    InvalidCredentials,
    OutcomeUnknown,
    RateLimited,
    ServerError,
)
from .models import SignIn
from .session_store import SessionStore, StoredSession

log = logging.getLogger("sequence_unofficial")
KEYRING_SERVICE = "sequence-unofficial"


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str = field(repr=False)


CredentialProvider = Callable[[], Credentials | None]


def _from_macos_security(email: str) -> str | None:
    """Read the password with Apple's ``security`` tool.

    Entries created with ``security add-generic-password`` trust that signed tool, so reading them
    this way never shows a Keychain prompt (a Python process with an ad-hoc signature would be asked
    again after every interpreter update).
    """
    try:
        done = subprocess.run(  # noqa: S603
            ["/usr/bin/security", "find-generic-password", "-s", KEYRING_SERVICE, "-a", email, "-w"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    password = done.stdout.rstrip("\n")
    return password if done.returncode == 0 and password else None


def _from_keyring(email: str | None) -> Credentials | None:
    if not email:
        return None
    password: str | None = None
    if sys.platform == "darwin":
        password = _from_macos_security(email)
    if not password:
        try:
            keyring: Any = importlib.import_module("keyring")
            password = keyring.get_password(KEYRING_SERVICE, email)
        except Exception:  # keyring not installed, or no usable backend
            return None
    return Credentials(email, password) if password else None


class Auth:
    """Owns the session state. ``generation`` increases on every successful login."""

    def __init__(
        self,
        transport: Transport,
        store: SessionStore | None,
        *,
        email: str | None,
        password: str | None,
        provider: CredentialProvider | None,
    ) -> None:
        self._t = transport
        self._store = store
        self._email = email
        self._password = password
        self._provider = provider
        self._lock = threading.Lock()
        self._ready = False
        self._session_email: str | None = None
        self._saved: list[dict[str, Any]] = []  # cookies as last written to / read from the store
        self.csrf: str | None = None
        self.generation = 0

    @property
    def store_path(self) -> Path | None:
        return self._store.path if self._store else None

    # --- credentials ------------------------------------------------------------------------
    def configured_email(self) -> str | None:
        """E-mail from arguments or environment only (never prompts)."""
        return self._email or os.environ.get("SEQUENCE_EMAIL") or None

    def credentials(self) -> Credentials | None:
        """arguments -> SEQUENCE_EMAIL/SEQUENCE_PASSWORD -> keyring -> provider (CLI prompt)."""
        email = self.configured_email()
        password = self._password or os.environ.get("SEQUENCE_PASSWORD")
        if email and password:
            return Credentials(email, password)
        found = _from_keyring(email)
        if found:
            return found
        return self._provider() if self._provider else None

    # --- session ----------------------------------------------------------------------------
    def _jar(self) -> list[dict[str, Any]]:
        return [
            {
                "name": c.name,
                "value": c.value or "",
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "expires": c.expires,
            }
            for c in self._t.cookies.jar
        ]

    def _apply(self, stored: StoredSession) -> None:
        now = time.time()
        for c in stored.cookies:
            expires = c.get("expires")
            if isinstance(expires, int) and expires < now:
                continue  # already expired: do not send it
            domain = str(c.get("domain", ""))
            self._t.cookies.jar.set_cookie(
                Cookie(
                    version=0,
                    name=c["name"],
                    value=c["value"],
                    port=None,
                    port_specified=False,
                    domain=domain,
                    domain_specified=bool(domain),
                    domain_initial_dot=domain.startswith("."),
                    path=str(c.get("path", "/")),
                    path_specified=True,
                    secure=bool(c.get("secure", False)),
                    expires=expires if isinstance(expires, int) else None,
                    discard=not isinstance(expires, int),
                    comment=None,
                    comment_url=None,
                    rest={},
                )
            )
        self.csrf = stored.csrf
        self._session_email = stored.email
        self._saved = self._jar()

    def _persist(self, email: str) -> None:
        if self._store is None:
            return
        self._session_email = email.lower()
        self._saved = self._jar()
        self._store.save(StoredSession(email=self._session_email, csrf=self.csrf, cookies=self._saved))

    def save_if_changed(self) -> None:
        """Write the session again if the server rotated a cookie since it was last saved.

        Persistence is best effort here: an ``OSError`` is logged, never raised, so that a read-only
        state directory cannot break a request or hide the error that ``close()`` runs under.
        """
        with self._lock:
            jar = self._jar()
            if not (self._store and self._ready and jar and jar != self._saved):
                return
            self._saved = jar  # also on failure: do not retry (and warn) on every request
            try:
                self._store.save(StoredSession(email=self._session_email, csrf=self.csrf, cookies=jar))
            except OSError as exc:
                log.warning("could not save the session to %s: %s", self._store.path, exc.strerror or exc)

    def ensure(self) -> None:
        """Make sure there is a session before the first request (lazy; nothing is sent if one is stored)."""
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            stored = self._store.load() if self._store else None
            wanted = self.configured_email()
            if stored and stored.cookies and not (wanted and stored.email and stored.email != wanted.lower()):
                self._apply(stored)
                self.generation += 1
            else:
                self._login_locked()
            self._ready = True

    def login(self) -> SignIn:
        """Explicit login (used by ``sequence-unofficial login``); replaces any current session."""
        with self._lock:
            result = self._login_locked()
            self._ready = True
            return result

    def relogin(self, seen_generation: int) -> None:
        """Log in again after an expiry response, unless another thread already did."""
        with self._lock:
            if self.generation != seen_generation:
                return
            self._login_locked()

    def logout(self) -> None:
        with self._lock:
            self._t.cookies.clear()
            self.csrf = None
            self._ready = False
            if self._store:
                self._store.clear()

    def _login_locked(self) -> SignIn:
        creds = self.credentials()
        self._t.cookies.clear()
        self.csrf = None
        if creds is None:
            if self._store:
                self._store.clear()
            raise AuthenticationRequired(
                "No valid session and no credentials: set SEQUENCE_EMAIL/SEQUENCE_PASSWORD, "
                "use the keyring, or run `sequence-unofficial login`."
            )
        try:
            response = self._t.send(
                SIGNIN.method, SIGNIN.path, json={"email": creds.email, "password": creds.password}
            )
        except OutcomeUnknown as exc:  # logging in again is harmless: report it as a plain connection failure
            raise ServerError("Login failed: no answer from the server.") from exc
        result = self._parse_signin(response)
        self.csrf = result.csrf
        self.generation += 1
        self._persist(creds.email)
        log.info("logged in")
        return result

    @staticmethod
    def _parse_signin(response: httpx.Response) -> SignIn:
        if response.status_code in (401, 422):
            raise InvalidCredentials("Login rejected: wrong e-mail or password.")
        if response.status_code == 429:
            raise RateLimited("Login rate limited.", parse_retry_after(response.headers.get("retry-after")))
        if response.status_code >= 500:
            raise ServerError(f"Login failed: server error {response.status_code}.")
        if response.status_code != 200:
            raise AuthError(f"Login failed with HTTP {response.status_code}.")
        try:
            result = SignIn.model_validate(response.json())
        except (ValueError, PydanticValidationError):
            # ``from None``: the validation error would carry the response body (CSRF token, e-mail).
            raise AuthError("Unexpected sign-in response (2FA or a changed login flow?).") from None
        if not result.csrf:
            raise AuthError("Unexpected sign-in response: no CSRF token.")
        return result
