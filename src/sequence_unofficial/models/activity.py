"""Workouts ("activities"): GET /api/v1/activities[/{id}], /api/v1/categories."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import field_validator

from .base import Num, SequenceModel

# Known values (informational; fields stay `str` so new server values still parse).
EXERCISE_CATEGORIES = ("interval", "duration_weight")
SET_KINDS = ("normal",)
EFFORT_SCALES = ("rir",)


class ExerciseUsage(SequenceModel):
    total: int | None = None
    workout_exercises: int | None = None
    workout_alternates: int | None = None
    coaching_workout_exercises: int | None = None
    coaching_workout_alternates: int | None = None


class ExerciseLibraryItem(SequenceModel):
    """Entry of the exercise library (built-in or custom). Also nested inside workouts.

    ``GET /api/v1/exercise_library_items`` is expected to return a list of these, but the body
    was not captured yet: items may be partial there.
    """

    id: str
    name: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    category: str | None = None
    default_weight_unit: str | None = None
    default_distance_unit: str | None = None
    custom: bool | None = None
    user_id: str | None = None
    source_exercise_library_item_id: str | None = None
    usage_count: int | None = None
    usage: ExerciseUsage | None = None
    progression_options: list[Any] | None = None


class ActivitySet(SequenceModel):
    id: str
    activity_exercise_id: str | None = None
    position: int | None = None
    weight: Num = None
    reps: int | None = None
    duration_seconds: int | None = None
    distance_meters: Num = None
    rest_seconds: int | None = None
    kind: str | None = None
    completed: bool | None = None
    cycle_rest_seconds: int | None = None
    target_rir: Num = None
    actual_rir: Num = None
    rir_enabled: bool | None = None
    effort_scale: str | None = None
    target_rpe: Num = None
    actual_rpe: Num = None
    progression_option_id: str | None = None


class ActivityExercise(SequenceModel):
    id: str
    activity_id: str | None = None
    exercise_library_item_id: str | None = None
    name: str | None = None
    position: int | None = None
    category: str | None = None
    rest_seconds: int | None = None
    weight_unit: str | None = None
    distance_unit: str | None = None
    default_rest_between_sets_seconds: int | None = None
    notes: str | None = None
    scheduled_activity_id: str | None = None
    superset_id: str | None = None
    rounds: int | None = None
    round_based: bool | None = None
    exercise_library_item: ExerciseLibraryItem | None = None
    sets: list[ActivitySet] | None = None
    alternates: list[Any] | None = None
    previous_sets: list[Any] | None = None


class Activity(SequenceModel):
    """A workout. ``duration`` is in milliseconds (see :attr:`duration_timedelta`)."""

    id: str
    user_id: str | None = None
    category_id: str | None = None
    archived: bool | None = None
    templated_activity_id: str | None = None
    templated_category_id: str | None = None
    templated_schedule_id: str | None = None
    duration: Num = None
    outdoor: bool | None = None
    shared: bool | None = None
    linked: bool | None = None
    user_notes: str | None = None
    strava_sync: bool | None = None
    activity_name: str | None = None
    activity_description: str | None = None
    activity_details: str | None = None
    category_name: str | None = None
    category_hex_colour: str | None = None
    # With ``skip_widgets=1`` the server sends ``{}`` instead of a list: normalised to None.
    widgets: list[Any] | None = None
    exercises: list[ActivityExercise] | None = None
    measures: list[Any] | None = None
    template_update_available: bool | None = None

    @field_validator("widgets", "measures", mode="before")
    @classmethod
    def _empty_dict_means_not_loaded(cls, v: Any) -> Any:
        return None if v == {} else v

    @property
    def duration_timedelta(self) -> timedelta | None:
        return None if self.duration is None else timedelta(milliseconds=float(self.duration))


class Category(SequenceModel):
    """Workout category (GET /api/v1/categories)."""

    id: str
    user_id: str | None = None
    name: str | None = None
    description: str | None = None
    archived: bool | None = None
    templated_category_id: str | None = None
    templated_schedule_id: str | None = None
    hex_colour: str | None = None
