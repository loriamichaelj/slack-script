"""Data types shared by every stage of the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

SPIKE, DROP, BOTH = "spike", "drop", "both"
WARNING, CRITICAL = "warning", "critical"
SEVERITY_RANK = {WARNING: 1, CRITICAL: 2}


@dataclass(frozen=True)
class MetricSpec:
    """One metric from the config, with defaults already merged in."""

    name: str
    provider: str
    selector: dict  # cloud-specific keys, validated in config.py
    category: str = "generic"
    direction: str = BOTH
    lookback_seconds: int = 86400
    period_seconds: int = 300
    detector: str = "mad"
    threshold: float = 3.5
    min_points: int = 30
    sustained_points: int = 3
    min_abs_change: float = 0.0
    alpha: float = 0.3  # EWMA smoothing factor
    fill_missing: str = "drop"  # "drop" or "zero"
    runbook: str | None = None


@dataclass(frozen=True)
class Point:
    ts: datetime  # start of the period the value covers
    value: float


@dataclass
class Series:
    provider: str
    resource: str
    metric: str
    unit: str
    scope: str  # region, subscription or project: part of the dedup fingerprint
    points: list[Point]  # oldest first
    console_url: str | None = None


@dataclass(frozen=True)
class Scored:
    """A detector's verdict on a window, as signed scores (positive = above baseline)."""

    center: float
    spread: float
    scores: list[float] | None  # None when the baseline has no spread


@dataclass(frozen=True)
class Detection:
    direction: str
    severity: str
    score: float  # the weakest score in the breaching window
    observed: float  # latest value
    center: float
    spread: float
    breaching: int  # consecutive breaching points


@dataclass
class Anomaly:
    spec: MetricSpec
    series: Series
    detection: Detection
    window_start: datetime
    window_end: datetime
    recent: list[float] = field(default_factory=list)

    @property
    def severity(self) -> str:
        return self.detection.severity

    @property
    def direction(self) -> str:
        return self.detection.direction

    @property
    def fingerprint(self) -> str:
        s = self.series
        return "|".join((s.provider, s.scope, s.resource, s.metric, self.direction))


@dataclass(frozen=True)
class CostSpec:
    """One billing account, subscription or project to report spend for."""

    name: str
    provider: str
    selector: dict  # cloud-specific keys, validated in config.py


@dataclass(frozen=True)
class DailyCost:
    day: date
    service: str
    amount: float


@dataclass
class CostData:
    provider: str
    scope: str  # account, subscription or billing table, for display
    currency: str
    rows: list[DailyCost]  # any order; days with no spend may be missing
