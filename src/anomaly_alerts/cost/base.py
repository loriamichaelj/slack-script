"""The one interface every cloud's cost adapter implements."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from ..models import CostData, CostSpec


class CostProvider(Protocol):
    def fetch(self, spec: CostSpec, start: date, end: date) -> CostData:
        """Return spend per day and service from start up to, not including, end."""
        ...
