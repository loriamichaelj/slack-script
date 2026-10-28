"""Guards shared by every detector, and the entry point that applies them.

A point set is an anomaly only when all of these hold:
  * the baseline has at least min_points values (the window under test is excluded);
  * the last sustained_points values all breach, on the same side of the baseline;
  * the side is one the metric alerts on (spike, drop or both);
  * each breaching value is at least min_abs_change away from the baseline centre.
When the baseline has no spread, a percentage-change rule takes over.
"""

from __future__ import annotations

from dataclasses import replace

from ..models import BOTH, CRITICAL, DROP, SPIKE, WARNING, Detection, MetricSpec
from . import DETECTORS

# With a flat baseline, a 50% move from the centre scores exactly the threshold.
FLAT_PCT = 0.5


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _allowed(direction: str, sign: int) -> bool:
    return direction == BOTH or (direction == SPIKE and sign > 0) or (direction == DROP and sign < 0)


def _flat_scores(center: float, window: list[float], threshold: float) -> list[float]:
    denom = max(abs(center), 1e-9)
    return [_sign(x - center) * threshold * (abs(x - center) / denom) / FLAT_PCT for x in window]


def _check(values: list[float], spec: MetricSpec, detector, k: int) -> Detection | None:
    if k < 1 or len(values) < spec.min_points + k:
        return None
    baseline, window = values[:-k], values[-k:]
    scored = detector.score(baseline, window, alpha=spec.alpha)
    scores = scored.scores
    if scores is None:
        scores = _flat_scores(scored.center, window, spec.threshold)

    signs = {_sign(s) for s in scores}
    if len(signs) != 1:
        return None
    sign = signs.pop()
    if sign == 0 or not _allowed(spec.direction, sign):
        return None
    for x, s in zip(window, scores):
        if abs(s) < spec.threshold or abs(x - scored.center) < spec.min_abs_change:
            return None

    weakest = min(scores, key=abs)
    return Detection(
        direction=SPIKE if sign > 0 else DROP,
        severity=CRITICAL if abs(weakest) >= 2 * spec.threshold else WARNING,
        score=weakest,
        observed=window[-1],
        center=scored.center,
        spread=scored.spread,
        breaching=k,
    )


def evaluate(values: list[float], spec: MetricSpec) -> Detection | None:
    """Return a Detection if the tail of values is anomalous for this spec, else None."""
    detector = DETECTORS[spec.detector]
    found = _check(values, spec, detector, spec.sustained_points)
    if found and found.severity == WARNING:
        # A breach that has lasted twice the minimum window escalates to critical.
        longer = _check(values, spec, detector, 2 * spec.sustained_points)
        if longer and longer.direction == found.direction:
            found = replace(found, severity=CRITICAL)
    return found
