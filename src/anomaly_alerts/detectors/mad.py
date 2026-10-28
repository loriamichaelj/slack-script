"""Modified z-score: robust to past spikes because it uses the median and MAD.

M = 0.6745 * (x - median) / MAD, which equals (x - median) / (MAD / 0.6745).
"""

from __future__ import annotations

from statistics import mean, median

from ..models import Scored

DEFAULT_THRESHOLD = 3.5
CENTER_LABEL = "median"
SCORE_LABEL = "modified z"

_MAD_TO_SIGMA = 0.6745
_MEAN_AD_TO_SIGMA = 1.253314  # used when more than half the baseline equals the median


def score(baseline: list[float], window: list[float], alpha: float = 0.3) -> Scored:
    med = median(baseline)
    deviations = [abs(v - med) for v in baseline]
    mad = median(deviations)
    if mad > 0:
        scale = mad / _MAD_TO_SIGMA
    else:
        # Mostly constant data (for example counts that are usually zero).
        scale = mean(deviations) * _MEAN_AD_TO_SIGMA
    if scale == 0:
        return Scored(med, 0.0, None)
    return Scored(med, scale, [(x - med) / scale for x in window])
