"""JSON export of everything this client can read. Files are written exactly as received (``.raw``).

This is a best-effort export, not a guaranteed full backup: experimental endpoints may return partial
data, and the planner is limited to a window of months (or, with ``everything=True``, as far back as
there is anything in it). ``manifest.json`` records what was written and what failed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, TypeVar, cast

from . import __version__
from .client import Sequence
from .errors import AuthError, InvalidArgument, SequenceError
from .models import ScheduleDay, SequenceModel

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
_EMPTY_MONTHS_TO_STOP = 6  # everything=True stops walking back after this many consecutive empty months
_MAX_MONTHS_BACK = 240
_FAILED_MONTHS_TO_STOP = 3  # ...or after this many consecutive months that could not be fetched
T = TypeVar("T")


def to_plain(obj: Any) -> Any:
    """Models -> their original dicts (recursing into lists and dicts); anything else unchanged."""
    if isinstance(obj, SequenceModel):
        return obj.raw
    if isinstance(obj, list):
        return [to_plain(i) for i in cast("list[Any]", obj)]
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in cast("dict[str, Any]", obj).items()}
    return obj


def _count(data: object) -> int:
    return len(cast("list[Any]", data)) if isinstance(data, list) else 1


def _write(path: Path, data: Any, *, overwrite: bool, root: Path | None = None) -> None:
    if root is not None:  # O_NOFOLLOW only covers the last component: check the subdirectories too
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise OSError(f"refusing to write through the symlinked directory {parent}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # O_EXCL: never clobber an existing file; O_NOFOLLOW: never write through a symlink.
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | (os.O_TRUNC if overwrite else os.O_EXCL)
    fd = os.open(path, flags, 0o600)  # personal data: owner only
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(to_plain(data), f, indent=1, ensure_ascii=False)
        f.write("\n")


def _safe_name(identifier: str) -> str:
    """A file-name stem for an API id; a short hash keeps names distinct when characters were replaced."""
    safe = _SAFE.sub("_", identifier)
    if safe != identifier or safe in ("", ".", ".."):
        digest = hashlib.sha256(identifier.encode()).hexdigest()[:8]
        safe = f"{safe.strip('.')}-{digest}"
    return safe


def _month_offset(today: date, offset: int) -> tuple[int, int]:
    """(year, month) ``offset`` months from ``today``'s month (negative = earlier)."""
    year, month0 = divmod(today.year * 12 + today.month - 1 + offset, 12)
    return year, month0 + 1


def _has_content(days: list[ScheduleDay]) -> bool:
    return any(d.content or d.notes or d.tests for d in days)


def export_all(
    client: Sequence,
    out: Path,
    *,
    months_back: int = 1,
    months_ahead: int = 2,
    everything: bool = False,
    force: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    """Write the export into ``out`` and return the manifest (also saved as ``manifest.json``).

    ``out`` must not exist or must be empty unless ``force=True`` (which overwrites the files this
    export writes, and nothing else). ``everything=True`` walks the planner back until it has been
    *successfully* empty for six months in a row (``months_back`` is then ignored); months that fail
    to load do not count as empty, and three failures in a row stop the walk. One failing endpoint
    (or a file that cannot be written) is recorded in ``errors`` and does not stop the rest; an
    authentication problem does.

    The manifest says how the planner walk ended: ``planner_complete`` is true only if ``everything``
    ran into six empty months without any failed month; ``planner_stop_reason`` is one of
    ``window`` (not ``everything``), ``empty_months``, ``max_months`` or ``errors``.
    """
    today = today or date.today()
    if out.exists() and (not out.is_dir() or (any(out.iterdir()) and not force)):
        raise InvalidArgument(
            f"{out} exists and is not an empty directory; choose another one or use --force"
        )
    if not out.exists():
        try:
            out.mkdir(mode=0o700, parents=True)
        except FileExistsError:  # created by someone else since the check above
            raise InvalidArgument(f"{out} appeared while starting; choose another directory") from None
        except OSError as exc:
            raise InvalidArgument(f"cannot create {out}: {exc.strerror or exc}") from exc
        out.chmod(0o700)  # mkdir's mode is masked by the umask; an existing directory is left untouched
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    planner_months: list[str] = []
    taken: set[str] = set()  # lower-cased targets: ids differing only by case collide on macOS/Windows

    def target_for(folder: str, identifier: str) -> str:
        name = _safe_name(identifier)
        if f"{folder}/{name}".lower() in taken:
            name = f"{name}-{hashlib.sha256(identifier.encode()).hexdigest()[:8]}"
        taken.add(f"{folder}/{name}".lower())
        return f"{folder}/{name}.json"

    def step(name: str, fn: Callable[[], T], target: str) -> T | None:
        try:
            data = fn()
            _write(out / target, data, overwrite=force, root=out)
        except AuthError:
            raise
        except SequenceError as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            return None
        except OSError as exc:
            errors[name] = f"{type(exc).__name__}: {target}: {exc.strerror or exc}"
            return None
        counts[name] = _count(data)
        return data

    def planner(year: int, month: int) -> list[ScheduleDay] | None:
        label = f"{year}-{month:02d}"
        days = step(f"planner {label}", partial(client.schedules.month, year, month), f"planner/{label}.json")
        if days is not None:
            planner_months.append(label)
        return days

    step("status", client.account.status, "account/status.json")
    step("preferences", client.account.preferences, "account/preferences.json")
    step("settings", client.account.settings, "account/settings.json")
    step("categories", client.activities.categories, "categories.json")
    step("exercises", client.exercises.list, "exercises.json")
    step("dashboard", client.dashboard.get, "dashboard.json")
    for a in {a.id: a for a in step("activities", client.activities.list, "activities.json") or []}.values():
        step(f"activity {a.id}", partial(client.activities.get, a.id), target_for("activities", a.id))
    for t in {t.template.id: t for t in step("tests", client.tests.list, "tests.json") or []}.values():
        tid = t.template.id
        step(f"test {tid}", partial(client.tests.progress, tid), target_for("tests", tid))

    stop_reason, walk_failures = "window", 0
    if everything:
        empty, failed_in_a_row, back = 0, 0, 0
        stop_reason = "max_months"
        while back <= _MAX_MONTHS_BACK:
            days = planner(*_month_offset(today, -back))
            back += 1
            if days is None:  # a failed month says nothing about whether the month is empty
                walk_failures += 1
                failed_in_a_row += 1
                if failed_in_a_row >= _FAILED_MONTHS_TO_STOP:
                    stop_reason = "errors"
                    break
                continue
            failed_in_a_row = 0
            empty = 0 if _has_content(days) else empty + 1
            if empty >= _EMPTY_MONTHS_TO_STOP:
                stop_reason = "empty_months"
                break
        offsets = range(1, months_ahead + 1)  # this month and the past were walked above
    else:
        offsets = range(-months_back, months_ahead + 1)
    for offset in offsets:
        planner(*_month_offset(today, offset))

    manifest: dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": f"sequence-unofficial {__version__}",
        "planner_months": sorted(planner_months),
        "planner_complete": everything and stop_reason == "empty_months" and walk_failures == 0,
        "planner_stop_reason": stop_reason,
        "counts": counts,
        "errors": errors,
    }
    _write(out / "manifest.json", manifest, overwrite=force, root=out)
    return manifest
