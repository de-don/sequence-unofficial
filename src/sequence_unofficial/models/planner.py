"""Planner: GET /api/v1/schedules/user_month, GET /api/v1/dashboard."""

from __future__ import annotations

import datetime as dt
from typing import Any

from .base import Num, SequenceModel


class Biometrics(SequenceModel):
    present: bool | None = None


class ScheduleDay(SequenceModel):
    """One day cell of the planner grid. ``date`` is local to the user's time zone."""

    id: str
    num: int | None = None
    title: str | None = None
    date: dt.date | None = None
    total_actual_duration: Num = None
    biometrics: Biometrics | None = None
    events: list[Any] | None = None
    notes: list[Any] | None = None
    tests: list[Any] | None = None
    content: list[Any] | None = None
    color_blocks: list[Any] | None = None


class UpcomingWorkout(SequenceModel):
    id: str
    scheduled_at: dt.date | None = None
    activity_name: str | None = None
    category_name: str | None = None
    category_hex_colour: str | None = None


class GoalInProgress(SequenceModel):
    id: str
    title: str | None = None
    style: str | None = None


class SnapshotStat(SequenceModel):
    # Some stats (e.g. performed, rpe) are numeric; others (felt, motivated) are text.
    value: str | int | float | None = None
    change: str | None = None


class CategoryBreakdown(SequenceModel):
    """One entry in snapshot.session_breakdown.categories: hours by category."""

    id: str | None = None
    name: str | None = None
    hex_colour: str | None = None
    total: int | None = None
    time: int | float | None = None
    total_miss: int | None = None
    time_miss: int | float | None = None


class SnapshotBreakdown(SequenceModel):
    """Snapshot.session_breakdown: climbing hours by category for the period."""

    categories: list[CategoryBreakdown] | None = None
    hours: int | float | None = None
    change: str | None = None


class Snapshot(SequenceModel):
    demo: bool | None = None
    # The server sends an int count here, not a formatted string.
    sessions_completed: int | None = None
    days_on_rock: int | None = None
    rest_days: int | None = None
    # A per-category breakdown object, not a string.
    session_breakdown: SnapshotBreakdown | None = None
    felt: SnapshotStat | None = None
    motivated: SnapshotStat | None = None
    performed: SnapshotStat | None = None
    rpe: SnapshotStat | None = None


class Dashboard(SequenceModel):
    """GET /api/v1/dashboard. The ``recent_*`` lists were empty in the sample: kept untyped."""

    upcoming_workouts: list[UpcomingWorkout] | None = None
    goals_in_progress: list[GoalInProgress] | None = None
    snapshot: Snapshot | None = None
    recent_milestones: list[Any] | None = None
    recent_notes: list[Any] | None = None
    recent_comments: list[Any] | None = None
