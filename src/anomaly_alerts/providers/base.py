"""The one interface every cloud implements."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import MetricSpec, Series


class Provider(Protocol):
    def fetch(self, spec: MetricSpec, start: datetime, end: datetime) -> Series:
        """Return the metric between start and end as a Series.

        Points are (period start, value), oldest first, with missing periods left out.
        Timestamps must be timezone-aware.
        """
        ...
