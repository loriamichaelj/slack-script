"""Shared builders for tests."""

from datetime import UTC, datetime, timedelta

from anomaly_alerts.models import MetricSpec, Point, Series

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

# 10, 11, 12, 13, 14 repeating: mean and median 12, no outliers.
BASE = [10 + (i % 5) for i in range(60)]


def make_spec(**overrides) -> MetricSpec:
    fields = dict(
        name="cpu",
        provider="aws",
        selector={"region": "us-east-1", "namespace": "AWS/EC2", "metric": "CPUUtilization"},
        category="cpu",
        direction="both",
        lookback_seconds=6 * 3600,
        period_seconds=300,
        detector="mad",
        threshold=3.5,
        min_points=30,
        sustained_points=3,
    )
    fields.update(overrides)
    return MetricSpec(**fields)


def make_points(values, end=NOW, period=300):
    """Points ending with the last complete period before `end`."""
    first = end - timedelta(seconds=period * len(values))
    return [Point(first + timedelta(seconds=period * i), float(v)) for i, v in enumerate(values)]


def make_series(values, **overrides) -> Series:
    fields = dict(
        provider="aws",
        resource="prod-api",
        metric="CPUUtilization",
        unit="",
        scope="us-east-1",
        points=make_points(values),
        console_url="https://console.example.com/metric",
    )
    fields.update(overrides)
    return Series(**fields)
