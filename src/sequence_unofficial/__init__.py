"""Unofficial client for the Sequence climbing-training web app. Not affiliated with Sequence."""

__version__ = "0.1.0a3"

from .client import PreparedRequest, Sequence  # noqa: E402
from .errors import (  # noqa: E402
    AuthenticationRequired,
    AuthError,
    ConfirmationRequired,
    InvalidArgument,
    InvalidCredentials,
    NotFound,
    OutcomeUnknown,
    RateLimited,
    SequenceError,
    ServerError,
    SessionExpired,
    UnexpectedResponse,
    ValidationError,
    WritesDisabled,
)

__all__ = [
    "AuthError",
    "AuthenticationRequired",
    "ConfirmationRequired",
    "InvalidArgument",
    "InvalidCredentials",
    "NotFound",
    "OutcomeUnknown",
    "PreparedRequest",
    "RateLimited",
    "Sequence",
    "SequenceError",
    "ServerError",
    "SessionExpired",
    "UnexpectedResponse",
    "ValidationError",
    "WritesDisabled",
    "__version__",
]
