"""Remove secrets from anything that might end up in a log line."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Any

REDACTED = "[REDACTED]"
# Header and JSON-key names are matched by pattern, so a configured CSRF header name
# (unknown until a write is captured) is covered without being listed.
_SENSITIVE_HEADER = re.compile(r"csrf|xsrf|token|auth|cookie|session", re.I)
# "session" alone is a normal word in training data (a "session" is a workout), so JSON keys and query
# parameters are only redacted for session_id / _session / session_token style names.
_SESSION_ID = r"session_?id|_session|session_?token|session_?key"
_SENSITIVE_KEY = re.compile(rf"passw|token|secret|csrf|xsrf|cookie|authorization|{_SESSION_ID}", re.I)
# "authenticity_token=..." and "_session_id=..." too: ``\w*`` on both sides of the keyword.
_QUERY_SECRET = re.compile(rf"(?i)\b(\w*(?:password|passwd|token|csrf|xsrf|{_SESSION_ID})\w*)=[^&\s]+")


def redact_headers(headers: Mapping[str, str], secret_names: Collection[str] = ()) -> dict[str, str]:
    """Copy of ``headers`` with the values of secret-looking headers replaced.

    ``secret_names`` (case-insensitive) are always redacted, whatever they are called: it is how a
    configured CSRF header name is covered even if it matches no pattern.
    """
    names = {n.lower() for n in secret_names}
    return {
        k: (REDACTED if k.lower() in names or _SENSITIVE_HEADER.search(k) else v) for k, v in headers.items()
    }


def redact_json(obj: Any) -> Any:
    """Recursively replace values of secret-looking keys (``password``, ``csrf``, ...)."""
    if isinstance(obj, dict):
        d: dict[str, Any] = obj  # pyright: ignore[reportUnknownVariableType]
        return {k: (REDACTED if _SENSITIVE_KEY.search(str(k)) else redact_json(v)) for k, v in d.items()}
    if isinstance(obj, list):
        items: list[Any] = obj  # pyright: ignore[reportUnknownVariableType]
        return [redact_json(v) for v in items]
    return obj


def redact_text(text: str) -> str:
    """Redact ``password=...``-style fragments in free text such as URLs."""
    return _QUERY_SECRET.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
