"""GCP Cloud Monitoring via google-cloud-monitoring list_time_series."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..models import MetricSpec, Point, Series


def _default_client():
    try:
        from google.cloud import monitoring_v3
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-monitoring is not installed; run: pip install 'anomaly-alerts[gcp]'"
        ) from exc
    return monitoring_v3.MetricServiceClient()


def _label(item, field: str) -> str:
    """Read a grouped label such as resource.labels.project_id from a returned series."""
    parts = field.split(".")
    if len(parts) == 3 and parts[0] in ("resource", "metric") and parts[1] in ("label", "labels"):
        return str(getattr(item, parts[0]).labels.get(parts[2], ""))
    if field == "resource.type":
        return str(item.resource.type)
    return ""


def _points(item, period_seconds: int) -> list[Point]:
    period = timedelta(seconds=period_seconds)
    points = []
    for p in item.points:
        end_time = p.interval.end_time
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=UTC)
        value = p.value
        # GCP stamps each aligned point with the END of its period; we use the start.
        points.append(Point(end_time - period, float(value.double_value or value.int64_value)))
    points.sort(key=lambda p: p.ts)  # GCP returns newest first
    return points


# Cloud Monitoring keeps different resource types apart even when grouping, so one
# group can come back as several series. These reducers combine them exactly.
_MERGE = {"REDUCE_SUM": sum, "REDUCE_COUNT": sum, "REDUCE_COUNT_TRUE": sum, "REDUCE_MAX": max, "REDUCE_MIN": min}


def _merge(point_lists: list[list[Point]], combine) -> list[Point]:
    by_ts: dict[datetime, list[float]] = {}
    for points in point_lists:
        for p in points:
            by_ts.setdefault(p.ts, []).append(p.value)
    return [Point(ts, combine(values)) for ts, values in sorted(by_ts.items())]


class GcpProvider:
    def __init__(self, client=None):
        self._client = client

    def fetch(self, spec: MetricSpec, start: datetime, end: datetime) -> Series | list[Series]:
        """One Series, or one per group when the metric sets group_by."""
        if self._client is None:
            self._client = _default_client()
        sel = spec.selector
        project = sel["project"]
        group_by = sel.get("group_by") or []
        flt = f'metric.type = "{sel["metric_type"]}"'
        if sel.get("filter"):
            flt += f" AND {sel['filter']}"

        # Delta and cumulative metrics need a rate or delta aligner; set `aligner` in the config.
        aggregation = {
            "alignment_period": {"seconds": spec.period_seconds},
            "per_series_aligner": sel.get("aligner", "ALIGN_MEAN"),
            "cross_series_reducer": sel.get("reducer", "REDUCE_SUM" if group_by else "REDUCE_NONE"),
        }
        if group_by:
            aggregation["group_by_fields"] = list(group_by)
        request = {
            "name": f"projects/{project}",
            "filter": flt,
            "interval": {"start_time": start, "end_time": end},
            "aggregation": aggregation,
            "view": "FULL",
        }
        series_list = list(self._client.list_time_series(request=request))

        if group_by:
            return self._grouped(spec, series_list, group_by, aggregation["cross_series_reducer"])
        if len(series_list) > 1:
            raise RuntimeError(
                f"{len(series_list)} time series matched; narrow `filter`, set `reducer` "
                "(for example REDUCE_SUM) so exactly one series remains, or set `group_by`"
            )
        points = _points(series_list[0], spec.period_seconds) if series_list else []
        return Series(
            provider="gcp",
            resource=sel.get("filter") or sel["metric_type"],
            metric=sel["metric_type"],
            unit="",
            scope=project,
            points=points,
            console_url=f"https://console.cloud.google.com/monitoring/metrics-explorer?project={project}",
        )

    def _grouped(self, spec: MetricSpec, series_list, group_by: list[str], reducer: str) -> list[Series]:
        groups: dict[tuple, list] = {}
        for item in series_list:
            key = tuple(_label(item, field) for field in group_by)
            groups.setdefault(key, []).append(item)

        result = []
        for key, items in groups.items():
            labels = dict(zip(group_by, key))
            if len(items) == 1 or reducer in _MERGE:
                points = _merge([_points(i, spec.period_seconds) for i in items], _MERGE.get(reducer, sum))
                result.append(self._series(spec, labels, points))
            else:
                # Averages cannot be combined after the fact: keep each resource type apart.
                for item in items:
                    result.append(self._series(
                        spec, {**labels, "resource.type": str(item.resource.type)},
                        _points(item, spec.period_seconds),
                    ))
        return result

    def _series(self, spec: MetricSpec, labels: dict[str, str], points: list[Point]) -> Series:
        sel = spec.selector
        group = ", ".join(v or "(none)" for v in labels.values())
        # Grouping by project makes each project its own scope, for dedup and the console link.
        scope = next((v for f, v in labels.items() if f.endswith(".project_id") and v), sel["project"])
        return Series(
            provider="gcp",
            resource=group,
            metric=sel["metric_type"],
            unit="",
            scope=scope,
            points=points,
            console_url=f"https://console.cloud.google.com/monitoring/metrics-explorer?project={scope}",
            group=group,
        )
