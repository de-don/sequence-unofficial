from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx

from sequence_unofficial import Sequence
from sequence_unofficial.client import DEFAULT_BASE_URL

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_EMAIL = "user@example.com"
FAKE_PASSWORD = "not-a-real-password"  # noqa: S105
FAKE_CSRF = "fake-csrf-token-1"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def all_fixtures() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.glob("*.json"))]


@pytest.fixture
def mock() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=DEFAULT_BASE_URL, assert_all_called=False) as router:
        yield router


def sent(route: respx.Route) -> list[httpx.Request]:
    """The requests a mocked route received (typed wrapper for respx' call records)."""
    calls = cast("list[Any]", list(route.calls))  # pyright: ignore[reportUnknownArgumentType]
    return [cast(httpx.Request, call.request) for call in calls]


def signin_response(csrf: str = FAKE_CSRF, cookie: str = "fake-session-1") -> httpx.Response:
    """A successful POST /signin answer built from the sanitized sample (+ fake cookie and CSRF)."""
    body = dict(load_fixture("post_signin.json")["response"], csrf=csrf)
    return httpx.Response(200, json=body, headers={"Set-Cookie": f"_seq_session={cookie}; Path=/; HttpOnly"})


@pytest.fixture
def signin(mock: respx.MockRouter) -> respx.Route:
    return mock.post("/signin").mock(return_value=signin_response())


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def session_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "session.json"


@pytest.fixture
def make_client(session_path: Path, sleeps: list[float]):
    clients: list[Sequence] = []

    def _make(**kw: Any) -> Sequence:
        kw.setdefault("email", FAKE_EMAIL)
        kw.setdefault("password", FAKE_PASSWORD)
        kw.setdefault("session_path", session_path)
        kw.setdefault("requests_per_second", None)
        kw.setdefault("sleep", sleeps.append)
        c = Sequence(**kw)
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def allow_unbacked_destructive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lets the fake DELETE endpoint through the fail-closed guard (no backup-before-delete yet)."""
    monkeypatch.setattr("sequence_unofficial.client._ALLOW_UNBACKED_DESTRUCTIVE", True)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("SEQUENCE_EMAIL", "SEQUENCE_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _reset_logger() -> Iterator[None]:
    import logging

    logger = logging.getLogger("sequence_unofficial")
    level = logger.level
    yield
    logger.setLevel(level)  # the CLI changes the level; keep tests independent
