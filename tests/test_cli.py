from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from sequence_unofficial import cli
from sequence_unofficial.cli import app
from sequence_unofficial.export import export_all

from .conftest import FAKE_EMAIL, FAKE_PASSWORD, load_fixture, sent, signin_response

runner = CliRunner()
ACTIVITY = load_fixture("get_api_v1_activities_id.json")["response"]


@pytest.fixture(autouse=True)
def _cli_client(monkeypatch: pytest.MonkeyPatch, make_client: Any, session_path: Path) -> None:
    monkeypatch.setattr(cli, "_client", lambda: make_client())
    monkeypatch.setenv("SEQUENCE_SESSION_FILE", str(session_path))


def fx(name: str) -> Any:
    return load_fixture(name)["response"]


def test_whoami_json(mock: respx.MockRouter, signin: respx.Route) -> None:
    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=fx("get_accounts_status.json")))
    mock.get("/accounts/get_preferences").mock(
        return_value=httpx.Response(200, json=fx("get_accounts_get_preferences.json"))
    )
    result = runner.invoke(app, ["whoami", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"]["plan"] == "text" and data["preferences"]["weight_unit"] == "kg"


def test_workouts_show_table_and_json(mock: respx.MockRouter, signin: respx.Route) -> None:
    mock.get(f"/api/v1/activities/{ACTIVITY['id']}").mock(return_value=httpx.Response(200, json=ACTIVITY))
    shown = runner.invoke(app, ["workouts", "show", ACTIVITY["id"]])
    assert shown.exit_code == 0 and "set 1" in shown.output
    as_json = runner.invoke(app, ["workouts", "show", ACTIVITY["id"], "--json"])
    assert json.loads(as_json.output) == ACTIVITY  # --json prints the original payload


def test_list_commands_render(mock: respx.MockRouter, signin: respx.Route) -> None:
    mock.get("/api/v1/activities").mock(return_value=httpx.Response(200, json=[ACTIVITY]))
    mock.get("/api/v1/exercise_library_items").mock(
        return_value=httpx.Response(200, json=[e["exercise_library_item"] for e in ACTIVITY["exercises"]])
    )
    mock.get("/api/v1/custom_test_progress").mock(
        return_value=httpx.Response(200, json=fx("get_api_v1_custom_test_progress.json"))
    )
    mock.get("/api/v1/schedules/user_month").mock(
        return_value=httpx.Response(200, json=fx("get_api_v1_schedules_user_month.json"))
    )
    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(200, json=fx("get_api_v1_dashboard.json")))
    mock.get("/api/v1/custom_test_templates/abc/progress").mock(
        return_value=httpx.Response(200, json=fx("get_api_v1_custom_test_templates_id_progress.json"))
    )
    for args in (
        ["workouts", "list"],
        ["exercises", "list", "--custom"],
        ["tests", "list"],
        ["tests", "show", "abc"],
        ["planner", "month", "2026-09", "--grid"],
        ["dashboard"],
    ):
        result = runner.invoke(app, [*args])
        assert result.exit_code == 0, (args, result.output)
        as_json = runner.invoke(app, [*args, "--json"])
        assert as_json.exit_code == 0 and json.loads(as_json.output) is not None, args


def test_planner_month_validates_input() -> None:
    assert runner.invoke(app, ["planner", "month", "2026-13"]).exit_code == 2


def test_errors_become_exit_codes(mock: respx.MockRouter) -> None:
    mock.post("/signin").mock(return_value=httpx.Response(401))
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code == 2 and "wrong e-mail or password" in result.output
    mock.post("/signin").mock(return_value=signin_response())
    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(404))
    assert runner.invoke(app, ["dashboard"]).exit_code == 1


def test_raw_is_get_only_and_host_is_fixed(mock: respx.MockRouter, signin: respx.Route) -> None:
    assert runner.invoke(app, ["raw", "POST", "/api/v1/dashboard"]).exit_code == 2
    assert runner.invoke(app, ["raw", "GET", "https://evil.example/x"]).exit_code == 2
    assert runner.invoke(app, ["raw", "GET", "//evil.example/x"]).exit_code == 2
    route = mock.get("/api/v1/strava/status").mock(
        return_value=httpx.Response(200, json={"connected": False})
    )
    result = runner.invoke(app, ["raw", "GET", "/api/v1/strava/status?a=1"])
    assert result.exit_code == 0 and json.loads(result.output) == {"connected": False}
    assert sent(route)[0].url.params["a"] == "1"


def test_login_and_logout(
    mock: respx.MockRouter, signin: respx.Route, monkeypatch: pytest.MonkeyPatch, session_path: Path
) -> None:
    monkeypatch.setenv("SEQUENCE_EMAIL", FAKE_EMAIL)
    monkeypatch.setenv("SEQUENCE_PASSWORD", FAKE_PASSWORD)
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 0, result.output
    assert signin.called and stat.S_IMODE(session_path.stat().st_mode) == 0o600
    assert FAKE_PASSWORD not in result.output
    assert runner.invoke(app, ["logout"]).exit_code == 0
    assert not session_path.exists()


def test_export_writes_private_files_and_survives_a_failing_endpoint(
    mock: respx.MockRouter, signin: respx.Route, make_client: Any, tmp_path: Path
) -> None:
    from datetime import date

    mock.get("/accounts/status").mock(return_value=httpx.Response(200, json=fx("get_accounts_status.json")))
    mock.get("/accounts/get_preferences").mock(
        return_value=httpx.Response(200, json=fx("get_accounts_get_preferences.json"))
    )
    mock.get("/accounts/get_settings").mock(
        return_value=httpx.Response(200, json=fx("get_accounts_get_settings.json"))
    )
    mock.get("/api/v1/categories").mock(
        return_value=httpx.Response(200, json=fx("get_api_v1_categories.json"))
    )
    mock.get("/api/v1/exercise_library_items").mock(return_value=httpx.Response(404))  # a failing endpoint
    mock.get("/api/v1/dashboard").mock(return_value=httpx.Response(200, json=fx("get_api_v1_dashboard.json")))
    mock.get("/api/v1/activities").mock(return_value=httpx.Response(200, json=[ACTIVITY]))
    mock.get(f"/api/v1/activities/{ACTIVITY['id']}").mock(return_value=httpx.Response(200, json=ACTIVITY))
    mock.get("/api/v1/custom_test_progress").mock(
        return_value=httpx.Response(200, json=fx("get_api_v1_custom_test_progress.json"))
    )
    mock.get(url__regex=r".*/custom_test_templates/.*/progress").mock(
        return_value=httpx.Response(200, json=fx("get_api_v1_custom_test_templates_id_progress.json"))
    )
    mock.get("/api/v1/schedules/user_month").mock(
        return_value=httpx.Response(200, json=fx("get_api_v1_schedules_user_month.json"))
    )
    out = tmp_path / "backup"
    manifest = export_all(make_client(), out, months_back=0, months_ahead=1, today=date(2026, 11, 25))
    assert "exercises" in manifest["errors"] and "exercises" not in manifest["counts"]
    assert json.loads((out / f"activities/{ACTIVITY['id']}.json").read_text()) == ACTIVITY
    assert (out / "planner/2026-11.json").exists() and (out / "planner/2026-12.json").exists()
    assert stat.S_IMODE((out / "manifest.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
