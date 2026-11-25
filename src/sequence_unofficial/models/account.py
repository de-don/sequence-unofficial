"""/signin, /accounts/*, integration status and experimental features."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from .base import SequenceModel


class Preferences(SequenceModel):
    """GET /accounts/get_preferences. ``user_email`` / ``user_name`` are hidden from ``repr``."""

    _hidden: ClassVar[frozenset[str]] = frozenset({"user_email", "user_name"})

    theme: str | None = None
    time_zone: str | None = None
    weight_unit: str | None = None
    distance_unit: str | None = None
    compact_view: bool | None = None
    planner_view: str | None = None
    emoji_skin_tone: str | None = None
    daily_email_time: str | None = None
    weekly_email_day: str | None = None
    weekly_email_time: str | None = None
    send_daily_emails: bool | None = None
    send_weekly_emails: bool | None = None
    initial_template: str | None = None
    assistant_enabled: bool | None = None
    show_total_duration: bool | None = None
    chart_prefs_biometrics: list[str] | None = None
    chart_prefs_custom_measures: list[str] | None = None
    has_seen_onboarding_tour: bool | None = None
    manual_timer_prep_enabled: bool | None = None
    created_from_plan_purchase: bool | None = None
    # The sanitized sample has a string here; the real type is unverified (likely bool).
    password_set_from_plan_purchase: bool | str | None = None
    default_timer_continues_to_rest: bool | None = None
    default_timer_continues_through_exercise: bool | None = None
    default_rest_between_sets_seconds: int | None = None
    default_rest_between_exercises_seconds: int | None = None
    user_email: str | None = None
    user_name: str | None = None
    email_verified: bool | None = None
    strava_connected: bool | None = None


class Settings(SequenceModel):
    """GET /accounts/get_settings (camelCase on the wire)."""

    show_admin: bool | None = Field(default=None, alias="showAdmin")
    show_coaching: bool | None = Field(default=None, alias="showCoaching")
    is_coach: bool | None = Field(default=None, alias="isCoach")
    is_client: bool | None = Field(default=None, alias="isClient")


class AccountStatus(SequenceModel):
    """GET /accounts/status (subscription / trial state)."""

    valid: bool | None = None
    valid_trial: bool | None = None
    trial: bool | None = None
    subscribed: bool | None = None
    plan: str | None = None
    platform: str | None = None
    trial_ended: bool | None = None
    trial_start_date: str | None = None
    trial_end_date: str | None = None
    trial_count: int | None = None


class UserSettings(SequenceModel):
    """The ``settings`` object inside the sign-in user (a subset of :class:`Preferences`)."""

    theme: str | None = None
    time_zone: str | None = None
    weight_unit: str | None = None
    distance_unit: str | None = None
    compact_view: bool | None = None
    planner_view: str | None = None
    emoji_skin_tone: str | None = None
    daily_email_time: str | None = None
    weekly_email_day: str | None = None
    weekly_email_time: str | None = None
    send_daily_emails: bool | None = None
    send_weekly_emails: bool | None = None
    initial_template: str | None = None
    assistant_enabled: bool | None = None
    show_total_duration: bool | None = None
    chart_prefs_biometrics: list[str] | None = None
    chart_prefs_custom_measures: list[str] | None = None
    has_seen_onboarding_tour: bool | None = None
    manual_timer_prep_enabled: bool | None = None
    created_from_plan_purchase: bool | None = None
    password_set_from_plan_purchase: bool | str | None = None
    default_timer_continues_to_rest: bool | None = None
    default_timer_continues_through_exercise: bool | None = None
    default_rest_between_sets_seconds: int | None = None
    default_rest_between_exercises_seconds: int | None = None


class User(SequenceModel):
    """The ``user`` object returned by POST /signin (``name``/``email`` hidden from ``repr``)."""

    _hidden: ClassVar[frozenset[str]] = frozenset({"name", "email"})

    id: str
    name: str | None = None
    email: str | None = None
    email_verified: bool | None = None
    subscribed: bool | None = None
    plan: str | None = None
    valid: bool | None = None
    settings: UserSettings | None = None


class SignIn(SequenceModel):
    """POST /signin response. ``csrf`` is a secret: hidden from ``repr``."""

    user: User
    csrf: str | None = None
    _hidden: ClassVar[frozenset[str]] = frozenset({"csrf"})


class AssistantFeature(SequenceModel):
    eligible: bool | None = None
    enabled: bool | None = None


class ExperimentalFeatures(SequenceModel):
    """GET /api/v1/experimental_features."""

    assistant: AssistantFeature | None = None


class StravaStatus(SequenceModel):
    """GET /api/v1/strava/status."""

    connected: bool | None = None
    athlete_id: str | None = None
    connected_at: str | None = None


class TheCragStatus(SequenceModel):
    """GET /api/v1/the_crag/status."""

    connected: bool | None = None
    account_name: str | None = None
    connected_at: str | None = None
    activity_id: str | None = None
    last_synced_at: str | None = None
    last_sync_status: str | None = None
    last_sync_error: str | None = None
    last_sync_summary: dict[str, object] | None = None
    manual_sync_available_at: str | None = None
    next_automatic_sync_at: str | None = None
    sync_queued: bool | None = None
    sync_queued_at: str | None = None
    auto_sync_due: bool | None = None
