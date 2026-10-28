"""Classic z-score: distance from the mean in standard deviations."""

from __future__ import annotations

from statistics import mean, stdev

from ..models import Scored

DEFAULT_THRESHOLD = 3.0
CENTER_LABEL = "mean"
SCORE_LABEL = "z"


def score(baseline: list[float], window: list[float], alpha: float = 0.3) -> Scored:
    mu = mean(baseline)
    sigma = stdev(baseline)
    if sigma == 0:
        return Scored(mu, 0.0, None)
    return Scored(mu, sigma, [(x - mu) / sigma for x in window])
