"""Azure Monitor via azure-monitor-query, version 1.x.

A metric with resource_id reads a platform metric (MetricsQueryClient). A metric with
workspace_id counts the rows a KQL query returns from a Log Analytics workspace, per period
(LogsQueryClient), which is how Activity Log events such as a role assignment become a number.
workspace_id is the workspace's customer ID (a GUID) or its full Azure resource ID.
"""

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


def _default_client(kind: str = "metrics"):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.query import LogsQueryClient, MetricsQueryClient
    except ImportError as exc:
        raise RuntimeError(
            "azure-monitor-query and azure-identity are not installed; "
            "run: pip install 'anomaly-alerts[azure]'"
        ) from exc
    client = LogsQueryClient if kind == "logs" else MetricsQueryClient
    return client(DefaultAzureCredential())


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


class AzureProvider:
    def __init__(self, client=None, logs_client=None):
        self._client = client
        self._logs_client = logs_client

    def fetch(self, spec: MetricSpec, start: datetime, end: datetime) -> Series:
        if "workspace_id" in spec.selector:
            return self._fetch_logs(spec, start, end)
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
        if sel.get("filter"):
            # A dimension filter, such as state eq 'Failed'. It leaves one series to read.
            kwargs["filter"] = sel["filter"]
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
                    points.append(Point(_aware(item.timestamp), float(value)))
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

    def _fetch_logs(self, spec: MetricSpec, start: datetime, end: datetime) -> Series:
        if self._logs_client is None:
            self._logs_client = _default_client("logs")
        sel = spec.selector
        # The config gives the rows to count; the count per period is added here, so every
        # query returns the same two columns.
        query = (
            f"{sel['query'].strip()}\n"
            f"| summarize value = count() by bin(TimeGenerated, {spec.period_seconds}s)"
        )
        workspace = sel["workspace_id"]
        if workspace.startswith("/"):
            # A full resource ID: known before the workspace exists, so the config never waits on it.
            response = self._logs_client.query_resource(workspace, query, timespan=(start, end))
        else:
            response = self._logs_client.query_workspace(workspace, query, timespan=(start, end))
        if getattr(response, "partial_error", None) is not None or not hasattr(response, "tables"):
            raise RuntimeError(f"log query returned an error: {getattr(response, 'partial_error', response)}")

        points: list[Point] = []
        for table in response.tables[:1]:
            columns = [getattr(c, "name", c) for c in table.columns]
            ts_at, value_at = columns.index("TimeGenerated"), columns.index("value")
            for row in table.rows:
                points.append(Point(_aware(row[ts_at]), float(row[value_at])))
        points.sort(key=lambda p: p.ts)
        subscription = re.search(r"/subscriptions/([^/]+)", workspace, re.IGNORECASE)
        return Series(
            provider="azure",
            resource=spec.name,
            metric="log query",
            unit="events",
            scope=subscription.group(1) if subscription else workspace,
            points=points,
            console_url=None,
        )
