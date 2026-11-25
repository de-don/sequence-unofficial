"""Exception hierarchy. Everything the library raises derives from :class:`SequenceError`."""

from __future__ import annotations

from typing import Any


class SequenceError(Exception):
    """Base class for all errors raised by this library."""


class AuthError(SequenceError):
    """Login failed, credentials are missing, or the session could not be renewed."""


class InvalidCredentials(AuthError):
    """POST /signin was rejected (wrong e-mail/password). Never retried."""


class AuthenticationRequired(AuthError):
    """No valid session and no credentials available to log in again."""


class SessionExpired(AuthError):
    """The session expired and the request could not be (safely) replayed after re-login."""


class InvalidArgument(SequenceError):
    """A caller-supplied value was rejected before anything was sent (e.g. a bad path parameter)."""


class NotFound(SequenceError):
    """HTTP 404."""


class ValidationError(SequenceError):
    """HTTP 422: the server rejected the request body. ``body`` holds the parsed response."""

    def __init__(self, message: str, body: Any = None) -> None:
        super().__init__(message)
        self.body = body


class RateLimited(SequenceError):
    """HTTP 429 that survived all retries."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(SequenceError):
    """HTTP 5xx (or a connection failure) that survived all retries."""


class OutcomeUnknown(SequenceError):
    """A write was sent but no usable answer came back (timeout, dropped connection, 502/504).

    The server may or may not have applied it. Check the state before retrying; the library never
    retries it. Not a :class:`ServerError` on purpose, so ``except ServerError: retry`` cannot catch it.
    """

    def __init__(self, message: str, method: str | None = None, path: str | None = None) -> None:
        super().__init__(message)
        self.method = method
        self.path = path


class UnexpectedResponse(SequenceError):
    """The response had an unexpected status, content type (e.g. HTML) or shape."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class WritesDisabled(SequenceError):
    """A write was attempted but the client was created with ``allow_writes=False`` (the default)."""


class ConfirmationRequired(SequenceError):
    """A destructive endpoint was called without a matching ``confirm=`` value."""
