"""Azure Monitor via azure-monitor-query (MetricsQueryClient, version 1.x)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from ..models import MetricSpec, Point, Series

# Config value -> (name the API expects, attribute on each returned data point)
_AGGREGATIONS = {
    "average": ("Average", "average"),
    "total": ("Total", "total"),
    "maximum": ("Maximum", "maximum"),
    "minimum": ("Minimum", "minimum"),
    "count": ("Count", "count"),
}


def _default_client():
    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.query import MetricsQueryClient
    except ImportError as exc:
        raise RuntimeError(
            "azure-monitor-query and azure-identity are not installed; "
            "run: pip install 'anomaly-alerts[azure]'"
        ) from exc
    return MetricsQueryClient(DefaultAzureCredential())


class AzureProvider:
    def __init__(self, client=None):
        self._client = client

    def fetch(self, spec: MetricSpec, start: datetime, end: datetime) -> Series:
        if self._client is None:
            self._client = _default_client()
        sel = spec.selector
        resource_id = sel["resource_id"]
        api_name, attribute = _AGGREGATIONS[str(sel.get("aggregation", "average")).lower()]

        kwargs = {
            "metric_names": [sel["metric"]],
            "timespan": (start, end),
            "granularity": timedelta(seconds=spec.period_seconds),
            "aggregations": [api_name],
        }
        if sel.get("namespace"):
            kwargs["metric_namespace"] = sel["namespace"]
        response = self._client.query_resource(resource_id, **kwargs)

        points: list[Point] = []
        unit = ""
        for metric in response.metrics:
            unit = str(getattr(metric, "unit", "") or "")
            for timeseries in metric.timeseries[:1]:  # no dimension split, so one series
                for item in timeseries.data:
                    value = getattr(item, attribute, None)
                    if value is None:
                        continue  # gap
                    ts = item.timestamp if item.timestamp.tzinfo else item.timestamp.replace(tzinfo=UTC)
                    points.append(Point(ts, float(value)))
        points.sort(key=lambda p: p.ts)

        subscription = re.search(r"/subscriptions/([^/]+)", resource_id, re.IGNORECASE)
        return Series(
            provider="azure",
            resource=resource_id.rstrip("/").rsplit("/", 1)[-1],
            metric=sel["metric"],
            unit="" if unit.lower() == "unspecified" else unit,
            scope=subscription.group(1) if subscription else "azure",
            points=points,
            console_url=f"https://portal.azure.com/#@/resource{resource_id}/metrics",
        )
