"""Detector registry. Each detector module exposes score(), DEFAULT_THRESHOLD and labels."""

from . import ewma, iqr, mad, zscore

DETECTORS = {
    "zscore": zscore,
    "mad": mad,
    "ewma": ewma,
    "iqr": iqr,
}
