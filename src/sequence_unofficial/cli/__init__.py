"""Command line interface: ``sequence-unofficial`` (alias ``squ``). Read-only in v0.1.

Exit codes: 0 ok, 1 error, 2 authentication problem (or bad usage), 3 outcome of a write unknown.
``login``, ``logout`` and ``raw`` have no ``--json`` (``raw`` always prints JSON).
"""

import functools
import json
import logging
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated, Any, TypeVar
from urllib.parse import parse_qsl

import typer
from rich.console import Console
from rich.table import Table

from .. import __version__
from ..auth import Credentials
from ..client import Sequence
from ..endpoints import Endpoint
from ..errors import AuthError, OutcomeUnknown, SequenceError
from ..export import export_all, to_plain

app = typer.Typer(
    name="sequence-unofficial",
    help="Unofficial client for the Sequence climbing-training app (not affiliated with Sequence).",
    no_args_is_help=True,
    add_completion=False,
)
workouts = typer.Typer(help="Workouts.", no_args_is_help=True)
exercises = typer.Typer(help="Exercise library.", no_args_is_help=True)
planner = typer.Typer(help="Planner.", no_args_is_help=True)
tests = typer.Typer(help="Custom tests.", no_args_is_help=True)
app.add_typer(workouts, name="workouts")
app.add_typer(exercises, name="exercises")
app.add_typer(planner, name="planner")
app.add_typer(tests, name="tests")

out = Console()
err = Console(stderr=True)
F = TypeVar("F", bound=Callable[..., Any])
JsonOpt = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]


def _version(value: bool) -> None:
    if value:
        typer.echo(f"sequence-unofficial {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    verbose: Annotated[int, typer.Option("--verbose", "-v", count=True, help="-v warnings, -vv debug.")] = 0,
    version: Annotated[
        bool | None, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = None,
) -> None:
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")
    level = [logging.ERROR, logging.WARNING, logging.DEBUG][min(verbose, 2)]
    logging.getLogger("sequence_unofficial").setLevel(level)


def _guard(fn: F) -> F:
    """Library errors -> one-line message + exit code (1 error, 2 authentication, 3 unknown outcome)."""

    @functools.wraps(fn)
    def wrapper(*a: Any, **kw: Any) -> Any:
        try:
            return fn(*a, **kw)
        except OutcomeUnknown as exc:
            err.print(f"[red]error:[/red] {exc}")
            err.print("The request may have been applied: check the current state before trying again.")
            raise typer.Exit(3) from exc
        except SequenceError as exc:
            err.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(2 if isinstance(exc, AuthError) else 1) from exc
        except OSError as exc:  # e.g. an export that cannot write its files
            err.print(f"[red]error:[/red] {type(exc).__name__}: {exc.strerror or exc}")
            raise typer.Exit(1) from exc

    return wrapper  # type: ignore[return-value]


def _prompt_credentials() -> Credentials | None:
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return None
    email = typer.prompt("E-mail", err=True)
    password = typer.prompt("Password", hide_input=True, err=True)
    return Credentials(email, password)


def _client() -> Sequence:
    return Sequence(credential_provider=_prompt_credentials)  # writes stay disabled in the CLI


def _json(data: Any) -> None:
    typer.echo(json.dumps(to_plain(data), indent=2, ensure_ascii=False, default=str))


def _table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    t = Table(title=title)
    for c in columns:
        t.add_column(c)
    for r in rows:
        t.add_row(*r)
    out.print(t)


def _s(value: Any) -> str:
    return "" if value is None else str(value)


@app.command()
@_guard
def login(
    email: Annotated[str | None, typer.Option(envvar="SEQUENCE_EMAIL", help="Account e-mail.")] = None,
) -> None:
    """Log in and save the session (cookies + CSRF; never the password)."""
    address: str = email or typer.prompt("E-mail", err=True)

    def ask_password() -> Credentials:  # only reached if SEQUENCE_PASSWORD and the keyring have nothing
        return Credentials(address, typer.prompt("Password", hide_input=True, err=True))

    with Sequence(address, credential_provider=ask_password) as client:
        client.login()
        out.print(f"Logged in. Session saved to {client.session_path}")


@app.command()
@_guard
def logout() -> None:
    """Delete the saved session (there is no server-side sign-out endpoint known)."""
    with _client() as c:
        c.logout()
    out.print("Local session removed.")


@app.command()
@_guard
def whoami(json_out: JsonOpt = False) -> None:
    """Account status and preferences (also checks that the session works)."""
    with _client() as c:
        status, prefs = c.account.status(), c.account.preferences()
    if json_out:
        return _json({"status": status, "preferences": prefs})
    _table(
        "Account",
        ["field", "value"],
        [
            ["e-mail", _s(prefs.user_email)],
            ["plan", _s(status.plan)],
            ["subscribed", _s(status.subscribed)],
            ["trial", _s(status.trial)],
            ["time zone", _s(prefs.time_zone)],
            ["units", f"{_s(prefs.weight_unit)} / {_s(prefs.distance_unit)}"],
        ],
    )


@workouts.command("list")
@_guard
def workouts_list(json_out: JsonOpt = False) -> None:
    """List workouts (experimental endpoint: the list body has not been captured yet)."""
    with _client() as c:
        items = c.activities.list()
    if json_out:
        return _json(items)
    _table(
        "Workouts",
        ["id", "name", "category", "minutes"],
        [
            [
                a.id,
                _s(a.activity_name),
                _s(a.category_name),
                _s(round(a.duration_timedelta.total_seconds() / 60) if a.duration_timedelta else ""),
            ]
            for a in items
        ],
    )


@workouts.command("show")
@_guard
def workouts_show(workout_id: str, json_out: JsonOpt = False) -> None:
    """Show one workout with its exercises and sets."""
    with _client() as c:
        a = c.activities.get(workout_id)
    if json_out:
        return _json(a)
    mins = round(a.duration_timedelta.total_seconds() / 60) if a.duration_timedelta else "?"
    out.print(f"[bold]{_s(a.activity_name)}[/bold]  ({_s(a.category_name)}, {mins} min)")
    for e in a.exercises or []:
        out.print(f"{_s(e.position)}. {_s(e.name)} [{_s(e.category)}]")
        for s in e.sets or []:
            parts = [
                f"{label} {v}"
                for label, v in (
                    ("reps", s.reps),
                    ("weight", s.weight),
                    ("secs", s.duration_seconds),
                    ("rest", s.rest_seconds),
                )
                if v is not None
            ]
            out.print(f"     set {_s(s.position)}: {', '.join(parts)}")


@exercises.command("list")
@_guard
def exercises_list(
    custom: Annotated[bool, typer.Option("--custom", help="Only your own exercises.")] = False,
    search: Annotated[str | None, typer.Option(help="Case-insensitive name filter.")] = None,
    json_out: JsonOpt = False,
) -> None:
    """List library exercises (experimental endpoint; filters run client-side)."""
    with _client() as c:
        items = c.exercises.list(custom=True if custom else None, search=search)
    if json_out:
        return _json(items)
    _table(
        "Exercises",
        ["id", "name", "category", "custom"],
        [[i.id, _s(i.name), _s(i.category), _s(i.custom)] for i in items],
    )


@planner.command("month")
@_guard
def planner_month(
    month: Annotated[str | None, typer.Argument(help="YYYY-MM (default: this month).")] = None,
    grid: Annotated[bool, typer.Option("--grid", help="Include days of neighbouring months.")] = False,
    json_out: JsonOpt = False,
) -> None:
    """Planner days for a month."""
    today = date.today()
    try:
        year, mon = (int(p) for p in month.split("-")) if month else (today.year, today.month)
        date(year, mon, 1)
    except ValueError:
        raise typer.BadParameter("use YYYY-MM, e.g. 2026-11") from None
    with _client() as c:
        days = c.schedules.month(year, mon)
    if not grid:
        days = [d for d in days if d.date is None or (d.date.year, d.date.month) == (year, mon)]
    if json_out:
        return _json(days)
    _table(
        f"Planner {year}-{mon:02d}",
        ["date", "title", "workouts", "notes", "tests"],
        [
            [
                _s(d.date),
                _s(d.title),
                _s(len(d.content or [])),
                _s(len(d.notes or [])),
                _s(len(d.tests or [])),
            ]
            for d in days
        ],
    )


@tests.command("list")
@_guard
def tests_list(json_out: JsonOpt = False) -> None:
    """List custom tests with their result counts."""
    with _client() as c:
        items = c.tests.list()
    if json_out:
        return _json(items)
    _table(
        "Tests",
        ["id", "name", "results", "latest"],
        [[t.template.id, _s(t.template.name), _s(t.count), _s(t.latest_date)] for t in items],
    )


@tests.command("show")
@_guard
def tests_show(template_id: str, json_out: JsonOpt = False) -> None:
    """Progress for one test template."""
    with _client() as c:
        p = c.tests.progress(template_id)
    if json_out:
        return _json(p)
    out.print(f"[bold]{_s(p.template.name)}[/bold]  results: {_s(p.count)}")
    _table(
        "Metrics",
        ["field", "unit", "direction", "count", "best", "latest"],
        [
            [
                _s(m.field.label if m.field else ""),
                _s(m.field.unit if m.field else ""),
                _s(m.field.direction if m.field else ""),
                _s(m.count),
                _s(m.best),
                _s(m.latest),
            ]
            for m in p.metrics or []
        ],
    )


@app.command()
@_guard
def dashboard(json_out: JsonOpt = False) -> None:
    """Upcoming workouts, goals in progress and the training snapshot."""
    with _client() as c:
        d = c.dashboard.get()
    if json_out:
        return _json(d)
    _table(
        "Upcoming workouts",
        ["date", "workout", "category"],
        [[_s(u.scheduled_at), _s(u.activity_name), _s(u.category_name)] for u in d.upcoming_workouts or []],
    )
    _table(
        "Goals in progress",
        ["title", "style"],
        [[_s(g.title), _s(g.style)] for g in d.goals_in_progress or []],
    )
    s = d.snapshot
    if s:
        out.print(f"sessions: {_s(s.sessions_completed)}  days on rock: {_s(s.days_on_rock)}", end="  ")
        out.print(f"rest days: {_s(s.rest_days)}")


@app.command()
@_guard
def export(
    directory: Annotated[
        Path, typer.Argument(help="Output directory: must not exist or be empty (see --force).")
    ],
    months_back: Annotated[int, typer.Option(help="Planner months before this one.")] = 1,
    months_ahead: Annotated[int, typer.Option(help="Planner months after this one.")] = 2,
    everything: Annotated[
        bool, typer.Option("--all", help="Walk the planner back until it has been empty for 6 months.")
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Use a non-empty directory; overwrite the files this export writes."),
    ] = False,
    json_out: JsonOpt = False,
) -> None:
    """Export everything readable as JSON (best effort, not a guaranteed full backup; keep it private)."""
    with _client() as c:
        manifest = export_all(
            c,
            directory,
            months_back=months_back,
            months_ahead=months_ahead,
            everything=everything,
            force=force,
        )
    if json_out:
        return _json(manifest)
    out.print(f"Exported {sum(manifest['counts'].values())} objects to {directory}")
    for name, msg in manifest["errors"].items():
        err.print(f"[yellow]skipped {name}:[/yellow] {msg}")
    if everything and not manifest["planner_complete"]:
        err.print(
            f"[yellow]planner walk incomplete:[/yellow] stopped because of {manifest['planner_stop_reason']}"
        )


@app.command()
@_guard
def raw(
    method: Annotated[str, typer.Argument(help="Only GET is allowed.")],
    path: Annotated[str, typer.Argument(help="Path on the dashboard host, e.g. /api/v1/dashboard?x=1")],
) -> None:
    """Send a GET to any path and print the JSON answer (for exploring; writes are not possible)."""
    if method.upper() != "GET":
        raise typer.BadParameter("only GET is supported")
    if not path.startswith("/") or path.startswith("//"):
        raise typer.BadParameter("PATH must start with a single '/' (the host is fixed)")
    base, _, query = path.partition("?")
    params = dict(parse_qsl(query, keep_blank_values=True))
    ep: Endpoint[Any] = Endpoint(
        "raw",
        "GET",
        base.replace("{", "{{").replace("}", "}}"),
        "raw",
        returns="json",
        status="experimental",
        note="raw passthrough",
        verified_on=None,
    )
    with _client() as c:
        _json(c.request(ep, params=params))
