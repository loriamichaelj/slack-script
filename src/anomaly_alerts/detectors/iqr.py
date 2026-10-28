"""IQR fence: flag points beyond Q1 - k*IQR or Q3 + k*IQR.

The score is the distance past the nearest quartile in IQR units, so a score above k
means the point is outside the fence. Inside the quartiles the score is zero.
"""

from __future__ import annotations

from statistics import quantiles

from ..models import Scored

DEFAULT_THRESHOLD = 1.5
CENTER_LABEL = "median"
SCORE_LABEL = "IQR"


def score(baseline: list[float], window: list[float], alpha: float = 0.3) -> Scored:
    q1, q2, q3 = quantiles(baseline, n=4, method="inclusive")
    iqr = q3 - q1
    if iqr == 0:
        return Scored(q2, 0.0, None)

    def one(x: float) -> float:
        if x > q3:
            return (x - q3) / iqr
        if x < q1:
            return (x - q1) / iqr
        return 0.0

    return Scored(q2, iqr, [one(x) for x in window])
