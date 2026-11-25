"""GET /api/v1/metrics/*. Only ``activity_magic_number`` has a populated sample."""

from __future__ import annotations

from .base import SequenceModel


class WeeklyMetric(SequenceModel):
    """One week of ``activity_magic_number`` (``date_value`` is epoch milliseconds)."""

    week_start_date: str | None = None
    week_end_date: str | None = None
    date_value: int | None = None
    date_text: str | None = None
    week: int | None = None
    total: int | None = None
    completed: int | None = None
    cumulative: int | None = None
