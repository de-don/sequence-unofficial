"""Base model: tolerant of API drift, keeps the original payload in ``.raw``."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, PrivateAttr, model_validator

M = TypeVar("M", bound="SequenceModel")


class SequenceModel(BaseModel):
    """All API models derive from this.

    * unknown fields are kept (``model_extra``) instead of rejected,
    * every field is optional unless a model says otherwise (only ``id`` is required where it exists),
    * enum-like values are plain ``str`` so a new server value never breaks parsing,
    * ``.raw`` is the untouched dict the server sent.
    """

    # hide_input_in_errors: a ValidationError must not echo the payload (tokens, e-mail) into logs/tracebacks.
    model_config = ConfigDict(extra="allow", populate_by_name=True, hide_input_in_errors=True)

    _hidden: ClassVar[frozenset[str]] = frozenset()
    """Field names left out of ``repr`` (personal data, secrets)."""

    _raw: dict[str, Any] = PrivateAttr(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def _keep_raw(cls: type[M], data: Any, handler: Any) -> M:
        obj: M = handler(data)
        if isinstance(data, dict):
            obj._raw = dict(data)  # pyright: ignore[reportUnknownArgumentType]
        return obj

    @property
    def raw(self) -> dict[str, Any]:
        """The original dict as received (numbers still as strings, unknown fields included)."""
        return self._raw

    def __repr_args__(self) -> Any:
        # Never print personal data (e-mail, names) or secrets in reprs, logs or tracebacks.
        for k, v in super().__repr_args__():
            if k not in self._hidden:
                yield k, v


Num = Decimal | None
"""Numeric values arrive as strings (``"5.0"``); pydantic turns them into :class:`~decimal.Decimal`."""
