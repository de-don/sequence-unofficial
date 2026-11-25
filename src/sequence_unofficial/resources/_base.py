from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import Sequence


class Resource:
    def __init__(self, client: Sequence) -> None:
        self._c = client
