"""The helper scripts in tools/: docs generation, sample lint, sanitizer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
REAL_LOOKING_UUID = "123e4567-e89b-42d3-a456-426614174000"  # valid v4, but not on the fake list


def load_tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = load_tool("lint_samples")
gen_docs = load_tool("gen_docs")
sanitize = load_tool("sanitize_captures")
FAKE = {u.lower() for u in (TOOLS / "fake_uuids.txt").read_text().split()}


def test_committed_samples_and_fixtures_pass_the_lint() -> None:
    assert lint.main([]) == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f'{{"id": "{REAL_LOOKING_UUID}"}}', "UUID not in fake_uuids.txt"),
        ('{"query": "activity_id=123e4567-e89b-42d3-a456-426614174000"}', "UUID not in fake_uuids.txt"),
        ('{"query": "activity_id%3D123e4567-e89b-42d3-a456-426614174000"}', "UUID not in fake_uuids.txt"),
        ('{"who": "jane.doe@gmail.com"}', "e-mail"),
        ('{"t": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEFghi"}', "JWT"),
        ('{"t": "' + "a1" * 20 + '"}', "long hex"),
        ('{"t": "' + "Ab3dE" * 10 + '"}', "base64"),
        ('{"headers": {"Set-Cookie": "x=1"}}', "header name"),
        ('{"csrf": "Zm9vYmFy"}', "non-placeholder"),
        ('{"nested": [{"user_password": "hunter2"}]}', "non-placeholder"),
    ],
)
def test_lint_flags_leaks(text: str, expected: str) -> None:
    problems = lint.lint_text(text, FAKE, set())
    assert any(expected in p for p in problems), problems


def test_lint_accepts_placeholders_and_example_addresses() -> None:
    ok = json.dumps(
        {
            "email": "user@example.com",
            "password": "[REDACTED]",
            "csrf": "[REDACTED]",
            "session_breakdown": "text",
        }
    )
    assert lint.lint_text(ok, FAKE, set()) == []


def test_lint_allowlist_is_exact() -> None:
    text = f'{{"id": "{REAL_LOOKING_UUID}"}}'
    assert lint.lint_text(text, FAKE | {REAL_LOOKING_UUID}, set()) == []


def test_api_docs_are_in_sync_with_registry_and_samples() -> None:
    assert gen_docs.main(["--check"]) == 0


def test_api_docs_list_every_endpoint() -> None:
    from sequence_unofficial.endpoints import ENDPOINTS

    text = gen_docs.render()
    for ep in ENDPOINTS:
        assert f"## `{ep.method} {ep.path}`" in text


def test_sanitizer_cleans_query_strings_and_bodies(tmp_path: Path) -> None:
    """Regression: activity_id in a query string used to survive sanitizing."""
    capture = tmp_path / "capture.jsonl"
    record = {
        "url": f"https://dashboard.sequence-app.com/api/v1/metrics/activity_list?activity_id={REAL_LOOKING_UUID}&token=abc",
        "method": "GET",
        "status": 200,
        "resBody": json.dumps(
            {"id": REAL_LOOKING_UUID, "name": "My Secret Workout", "owner": "jane@gmail.com"}
        ),
    }
    capture.write_text(json.dumps(record) + "\n")
    allow = tmp_path / "fake_uuids.txt"
    sanitize.main(str(capture), str(tmp_path / "out"), str(allow))

    produced = (tmp_path / "out" / "samples.json").read_text()
    assert REAL_LOOKING_UUID not in produced and "jane@" not in produced and "Secret" not in produced
    sample = json.loads(produced)[0]
    assert "abc" not in sample["query"] and "REDACTED" in sample["query"]
    fake_ids = set(allow.read_text().split())
    assert fake_ids and sample["response"]["id"] in fake_ids
    assert lint.lint_text(produced, fake_ids, set()) == []  # sanitizer output passes the lint
