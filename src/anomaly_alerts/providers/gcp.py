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


class GcpProvider:
    def __init__(self, client=None):
        self._client = client

    def fetch(self, spec: MetricSpec, start: datetime, end: datetime) -> Series:
        if self._client is None:
            self._client = _default_client()
        sel = spec.selector
        project = sel["project"]
        flt = f'metric.type = "{sel["metric_type"]}"'
        if sel.get("filter"):
            flt += f" AND {sel['filter']}"

        # Delta and cumulative metrics need a rate or delta aligner; set `aligner` in the config.
        request = {
            "name": f"projects/{project}",
            "filter": flt,
            "interval": {"start_time": start, "end_time": end},
            "aggregation": {
                "alignment_period": {"seconds": spec.period_seconds},
                "per_series_aligner": sel.get("aligner", "ALIGN_MEAN"),
                "cross_series_reducer": sel.get("reducer", "REDUCE_NONE"),
            },
            "view": "FULL",
        }
        series_list = list(self._client.list_time_series(request=request))
        if len(series_list) > 1:
            raise RuntimeError(
                f"{len(series_list)} time series matched; narrow `filter` or set `reducer` "
                "(for example REDUCE_SUM) so exactly one series remains"
            )

        points: list[Point] = []
        if series_list:
            period = timedelta(seconds=spec.period_seconds)
            for item in series_list[0].points:
                end_time = item.interval.end_time
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=UTC)
                value = item.value
                # GCP stamps each aligned point with the END of its period; we use the start.
                points.append(Point(end_time - period, float(value.double_value or value.int64_value)))
        points.sort(key=lambda p: p.ts)  # GCP returns newest first

        return Series(
            provider="gcp",
            resource=sel.get("filter") or sel["metric_type"],
            metric=sel["metric_type"],
            unit="",
            scope=project,
            points=points,
            console_url=f"https://console.cloud.google.com/monitoring/metrics-explorer?project={project}",
        )
