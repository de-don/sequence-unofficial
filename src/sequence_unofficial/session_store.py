"""Persist the session (cookies + CSRF token) between runs. The password is never stored."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from platformdirs import user_state_dir

log = logging.getLogger("sequence_unofficial")
APP_NAME = "sequence-unofficial"
_VERSION = 1
_KIND = "sequence-unofficial-session"
# Files written before the marker existed: recognised only if their keys match exactly.
_LEGACY_KEYS = frozenset({"version", "email", "csrf", "cookies", "saved_at"})


def default_session_path() -> Path:
    """``$SEQUENCE_SESSION_FILE`` if set, else ``<user state dir>/sequence-unofficial/session.json``."""
    override = os.environ.get("SEQUENCE_SESSION_FILE")
    return Path(override) if override else Path(user_state_dir(APP_NAME)) / "session.json"


@dataclass
class StoredSession:
    email: str | None = None  # lowercased; lets us ignore a session that belongs to another account
    csrf: str | None = None
    # one dict per cookie: name, value, domain, path, secure, expires (epoch seconds or null)
    cookies: list[dict[str, Any]] = field(default_factory=lambda: [])
    saved_at: str = ""

    def __repr__(self) -> str:  # never show cookie/CSRF values
        return f"StoredSession(cookies={len(self.cookies)}, saved_at={self.saved_at!r})"


class SessionStore:
    """JSON file with mode 0600; writes are atomic.

    It only ever replaces or deletes a file that is provably its own, because ``SEQUENCE_SESSION_FILE``
    may point at anything: a JSON object with ``"kind": "sequence-unofficial-session"`` and an integer
    ``version``, or an older version-1 file without ``kind`` whose keys match exactly. A file with a
    higher version is never overwritten (that would downgrade it), but ``clear`` may remove it.
    Directories are only restricted to 0700 when this class created them.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_session_path()

    def _read(self) -> dict[str, Any] | None:
        """The parsed file if it is one of ours, else ``None`` (missing, corrupt or foreign)."""
        try:
            data: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        d = cast("dict[str, Any]", data)
        if d.get("kind") == _KIND:
            return d if type(d.get("version")) is int else None
        return (
            d
            if d.get("version") == _VERSION and type(d["version"]) is int and d.keys() == _LEGACY_KEYS
            else None
        )

    def load(self) -> StoredSession | None:
        data = self._read()
        if data is None or data.get("version") != _VERSION:
            return None
        with contextlib.suppress(OSError):
            if self.path.stat().st_mode & 0o077:
                log.warning("%s is readable by other users; run: chmod 600 %s", self.path, self.path)
        cookies: list[dict[str, Any]] = []
        for c in cast("list[Any]", data.get("cookies") or []):
            if isinstance(c, dict):
                d = cast("dict[str, Any]", c)
                if isinstance(d.get("name"), str) and isinstance(d.get("value"), str):
                    cookies.append(dict(d))
        return StoredSession(
            email=data.get("email"),
            csrf=data.get("csrf"),
            cookies=cookies,
            saved_at=str(data.get("saved_at", "")),
        )

    def save(self, session: StoredSession) -> None:
        if self.path.exists():
            existing = self._read()
            if existing is None:
                log.warning(
                    "%s exists but is not a session file; not overwriting it (session not saved)", self.path
                )
                return
            if existing["version"] != _VERSION:
                log.warning(
                    "%s has session format version %s (this release writes %s); not overwriting it",
                    self.path,
                    existing["version"],
                    _VERSION,
                )
                return
        session.saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        parent = self.path.parent
        created = not parent.exists()
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if created:
            with contextlib.suppress(OSError):
                parent.chmod(0o700)  # mkdir's mode is masked by the umask
        payload = json.dumps({"kind": _KIND, "version": _VERSION, **asdict(session)}, indent=1)
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=".session-")  # created 0600
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def clear(self) -> None:
        """Delete the session file, but only if it is one."""
        if self.path.exists() and self._read() is None:
            log.warning("%s is not a session file; leaving it alone", self.path)
            return
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
