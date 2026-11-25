"""Every sample must parse into its model, with no unknown fields, through the real client path."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from sequence_unofficial.endpoints import ENDPOINTS, Endpoint
from sequence_unofficial.models import SequenceModel

from .conftest import all_fixtures

BY_KEY = {f"{e.method} {e.path}": e for e in ENDPOINTS}


def extras(obj: Any, path: str = "") -> list[str]:
    """Names of fields the models did not declare, anywhere in the tree."""
    found: list[str] = []
    if isinstance(obj, SequenceModel):
        found += [f"{path}.{k}" for k in (obj.model_extra or {})]
        for name in type(obj).model_fields:
            found += extras(getattr(obj, name), f"{path}.{name}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            found += extras(v, f"{path}[{i}]")
    return found


def test_every_sample_has_a_registry_entry_and_vice_versa() -> None:
    sample_keys = {f"{f['method']} {f['path']}" for f in all_fixtures()}
    assert sample_keys == set(BY_KEY), sample_keys ^ set(BY_KEY)


@pytest.mark.parametrize("fx", all_fixtures(), ids=lambda f: f"{f['method']} {f['path']}")
def test_sample_parses_without_unknown_fields(
    fx: dict[str, Any], mock: respx.MockRouter, signin: respx.Route, make_client: Any
) -> None:
    ep: Endpoint[Any] = BY_KEY[f"{fx['method']} {fx['path']}"]
    if fx["response"] is None:
        pytest.skip("response body was not captured (truncated)")
    path = ep.path.replace("{id}", "1111")
    client = make_client()
    route = mock.route(method=ep.method, path=path).mock(
        return_value=httpx.Response(200, json=fx["response"])
    )
    kwargs: dict[str, Any] = {"path_params": {"id": "1111"}} if "{id}" in ep.path else {}
    if fx["query"]:
        kwargs["params"] = dict(p.split("=", 1) for p in fx["query"].split("&"))
    if ep.method == "POST":
        pytest.skip("login is covered in test_auth.py")
    result = client.request(ep, **kwargs)

    assert route.called
    assert extras(result) == []
    if ep.returns == "list":
        assert len(result) == len(fx["response"])
        assert all(m.raw == r for m, r in zip(result, fx["response"], strict=True))
    elif ep.returns == "one":
        assert result.raw == fx["response"]
    else:
        assert result == fx["response"]


def test_signin_sample_parses() -> None:
    from sequence_unofficial.models import SignIn

    fx = next(f for f in all_fixtures() if f["path"] == "/signin")
    result = SignIn.model_validate(fx["response"])
    assert extras(result) == []
    assert result.user.id
    assert "csrf" not in repr(result)  # secrets stay out of reprs


def test_registry_is_consistent() -> None:
    names = [e.name for e in ENDPOINTS]
    assert len(names) == len(set(names))
    for e in ENDPOINTS:
        assert e.status in ("verified", "experimental")
        if e.status == "experimental":
            assert e.note, f"{e.name}: experimental endpoints must say why"
        if e.returns != "json":
            assert e.model is not None
        assert not e.is_write, "no write endpoints exist yet"
