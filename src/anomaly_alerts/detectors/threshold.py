"""Fixed limit: alert when values go past a set number, however normal that has become.

For events that matter every time (a root sign-in, a failed uptime check) and for slow creep
that a statistical baseline would learn as normal. `threshold` is the limit itself, and
`direction` says which side is bad: spike alerts above it, drop alerts below it. No baseline
is needed, so it alerts from the first points.
"""

from __future__ import annotations

from ..models import Scored

DEFAULT_THRESHOLD = 0.0
CENTER_LABEL = "limit"
SCORE_LABEL = "past limit"
NEEDS_BASELINE = False


def score(baseline: list[float], window: list[float], alpha: float = 0.3, limit: float = 0.0) -> Scored:
    return Scored(limit, 0.0, [x - limit for x in window])
