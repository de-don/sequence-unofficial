"""Custom tests: GET /api/v1/custom_test_progress, /api/v1/custom_test_templates/{id}/progress."""

from __future__ import annotations

from typing import Any

from .base import SequenceModel


class CustomTestField(SequenceModel):
    """One measured field of a test template. ``key`` identifies it when submitting results."""

    key: str | None = None
    type: str | None = None
    unit: str | None = None
    label: str | None = None
    options: list[Any] | None = None
    ordered: bool | None = None
    headline: bool | None = None
    position: int | None = None
    required: bool | None = None
    direction: str | None = None
    percentage: bool | None = None
    description: str | None = None


class CustomTestTemplate(SequenceModel):
    id: str
    user_id: str | None = None
    name: str | None = None
    description: str | None = None
    fields: list[CustomTestField] | None = None
    fields_version: int | None = None
    coaching: bool | None = None
    source_template_id: str | None = None


class CustomTestSummary(SequenceModel):
    """One row of GET /api/v1/custom_test_progress (no ``id``: it wraps a template)."""

    template: CustomTestTemplate
    count: int | None = None
    latest_date: str | None = None


class CustomTestMetric(SequenceModel):
    id: str
    field: CustomTestField | None = None
    retired: bool | None = None
    count: int | None = None
    first: Any = None
    latest: Any = None
    previous: Any = None
    best: Any = None
    change: Any = None
    previous_change: Any = None


class CustomTestProgress(SequenceModel):
    """GET /api/v1/custom_test_templates/{id}/progress. Result entries were empty in the sample."""

    template: CustomTestTemplate
    count: int | None = None
    metrics: list[CustomTestMetric] | None = None
    history: list[Any] | None = None
    attempts: list[Any] | None = None
    metric_id: str | None = None
    points: list[Any] | None = None
    history_points: list[Any] | None = None
    selected: Any = None
    comparison: Any = None
    comparison_rows: list[Any] | None = None
    feedback: list[Any] | None = None
