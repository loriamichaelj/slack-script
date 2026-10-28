"""AWS CloudWatch via boto3 get_metric_data."""

from __future__ import annotations

from datetime import datetime

from ..models import MetricSpec, Point, Series


def _default_factory(region: str):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed; run: pip install 'anomaly-alerts[aws]'") from exc
    return boto3.client("cloudwatch", region_name=region)


class AwsProvider:
    def __init__(self, client_factory=_default_factory):
        self._factory = client_factory
        self._clients: dict[str, object] = {}

    def _client(self, region: str):
        if region not in self._clients:
            self._clients[region] = self._factory(region)
        return self._clients[region]

    def fetch(self, spec: MetricSpec, start: datetime, end: datetime) -> Series:
        sel = spec.selector
        region = sel["region"]
        dimensions = [
            {"Name": name, "Value": str(value)} for name, value in (sel.get("dimensions") or {}).items()
        ]
        query = {
            "Id": "m0",
            "MetricStat": {
                "Metric": {
                    "Namespace": sel["namespace"],
                    "MetricName": sel["metric"],
                    "Dimensions": dimensions,
                },
                "Period": spec.period_seconds,
                "Stat": sel.get("stat", "Average"),
            },
            "ReturnData": True,
        }
        paginator = self._client(region).get_paginator("get_metric_data")
        points: list[Point] = []
        # Ascending order, because CloudWatch returns newest first by default.
        for page in paginator.paginate(
            MetricDataQueries=[query], StartTime=start, EndTime=end, ScanBy="TimestampAscending"
        ):
            for result in page.get("MetricDataResults", []):
                points.extend(
                    Point(ts, float(value)) for ts, value in zip(result["Timestamps"], result["Values"])
                )
        points.sort(key=lambda p: p.ts)
        return Series(
            provider="aws",
            resource=",".join(d["Value"] for d in dimensions) or sel["namespace"],
            metric=sel["metric"],
            unit="",
            scope=region,
            points=points,
            console_url=f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#metricsV2:",
        )
