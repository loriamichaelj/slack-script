"""EWMA: compare each point to a smoothed baseline, scaled by one-step forecast error.

Good for slow drift. The baseline is frozen at its last value, so the window under
test cannot pull its own reference along with it.
"""

from __future__ import annotations

from statistics import stdev

from ..models import Scored

DEFAULT_THRESHOLD = 3.0
CENTER_LABEL = "EWMA"
SCORE_LABEL = "deviation"


def score(baseline: list[float], window: list[float], alpha: float = 0.3) -> Scored:
    smooth = baseline[0]
    residuals = []
    for x in baseline[1:]:
        residuals.append(x - smooth)
        smooth = alpha * x + (1 - alpha) * smooth
    sigma = stdev(residuals)
    if sigma == 0:
        return Scored(smooth, 0.0, None)
    return Scored(smooth, sigma, [(x - smooth) / sigma for x in window])
