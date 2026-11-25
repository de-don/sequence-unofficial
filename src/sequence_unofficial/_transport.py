"""Low-level HTTP: throttling, GET-only retries with backoff, honest User-Agent, redacted logging."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable, Collection, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .errors import OutcomeUnknown, ServerError
from .redact import redact_headers, redact_json, redact_text

log = logging.getLogger("sequence_unofficial")

RETRY_STATUS = frozenset({429, 502, 503, 504})
# Failures that prove the request never reached the server (safe to report as a plain connection error).
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def parse_retry_after(value: str | None) -> float | None:
    """``Retry-After`` as seconds: either delta-seconds or an HTTP date. ``None`` if absent/unparsable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


class Transport:
    """Thin wrapper over :class:`httpx.Client`. Knows nothing about auth or models.

    It always builds its own client, so base URL, no-redirects, User-Agent and timeout cannot be bypassed.
    """

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        secret_headers: Collection[str] = (),
        timeout: float = 30.0,
        max_retries: int = 3,
        requests_per_second: float | None = 2.0,
        backoff_base: float = 0.5,
        backoff_cap: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            follow_redirects=False,  # a redirect to /sign-in is how we notice an expired session
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        self._secret_headers = tuple(secret_headers)
        self.max_retries = max_retries
        self._min_interval = 1.0 / requests_per_second if requests_per_second else 0.0
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self._clock = clock
        self._last = float("-inf")
        self._lock = threading.Lock()

    @property
    def cookies(self) -> httpx.Cookies:
        return self.http.cookies

    def close(self) -> None:
        self.http.close()

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = parse_retry_after(response.headers.get("retry-after"))
            if retry_after is not None:
                return min(retry_after, self._backoff_cap)
        return min(self._backoff_base * 2**attempt, self._backoff_cap) * (0.5 + random.random() / 2)

    def send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Send one request. Only GETs are retried (429/502/503/504 and connection errors).

        A non-GET that fails after it may have left the machine raises :class:`OutcomeUnknown`.
        """
        attempts = 1 + (self.max_retries if method == "GET" else 0)
        for attempt in range(attempts):
            last = attempt + 1 == attempts
            self._throttle()
            log.debug(
                "%s %s params=%s headers=%s body=%s",
                method,
                path,
                redact_text(str(dict(params or {}))),
                redact_headers(headers or {}, self._secret_headers),
                redact_json(json),
            )
            try:
                response = self.http.request(method, path, params=params, json=json, headers=headers)
            except httpx.TransportError as exc:
                if method != "GET" and not isinstance(exc, _NEVER_SENT):
                    raise OutcomeUnknown(
                        f"{method} {path}: no answer ({type(exc).__name__}); the server may have handled it",
                        method,
                        path,
                    ) from exc
                if last:
                    raise ServerError(f"{method} {path}: connection failed ({type(exc).__name__})") from exc
                self._sleep(self._delay(attempt, None))
                continue
            log.debug("%s %s -> %s", method, path, response.status_code)
            if method == "GET" and response.status_code in RETRY_STATUS and not last:
                self._sleep(self._delay(attempt, response))
                continue
            return response
        raise AssertionError("unreachable")  # pragma: no cover
