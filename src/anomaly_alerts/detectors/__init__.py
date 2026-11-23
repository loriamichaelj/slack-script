"""Detector registry. Each detector module exposes score(), DEFAULT_THRESHOLD and labels."""

from . import ewma, iqr, mad, threshold, zscore

DETECTORS = {
    "zscore": zscore,
    "mad": mad,
    "ewma": ewma,
    "iqr": iqr,
    "threshold": threshold,
}


def needs_baseline(name: str) -> bool:
    """False for detectors that compare to a fixed limit, which alert without any history."""
    return getattr(DETECTORS[name], "NEEDS_BASELINE", True)
