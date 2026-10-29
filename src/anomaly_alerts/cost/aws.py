"""AWS spend via Cost Explorer get_cost_and_usage, grouped by service.

Cost Explorer charges per request, so one run makes one call per account (plus pages).
"""

from __future__ import annotations

from datetime import date

from ..models import CostData, CostSpec, DailyCost

METRIC = "UnblendedCost"


def _default_factory():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed; run: pip install 'anomaly-alerts[aws]'") from exc
    # Cost Explorer has a single endpoint, in us-east-1.
    return boto3.client("ce", region_name="us-east-1")


class AwsCostProvider:
    def __init__(self, client_factory=_default_factory):
        self._factory = client_factory
        self._client = None

    def fetch(self, spec: CostSpec, start: date, end: date) -> CostData:
        if self._client is None:
            self._client = self._factory()
        linked = spec.selector.get("linked_account")
        request = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},  # End is exclusive
            "Granularity": "DAILY",
            "Metrics": [METRIC],
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        }
        if linked:
            request["Filter"] = {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [str(linked)]}}

        rows: list[DailyCost] = []
        currency = "USD"
        while True:
            page = self._client.get_cost_and_usage(**request)
            for result in page.get("ResultsByTime", []):
                day = date.fromisoformat(result["TimePeriod"]["Start"])
                for group in result.get("Groups", []):
                    cost = group["Metrics"][METRIC]
                    currency = cost.get("Unit") or currency
                    rows.append(DailyCost(day, group["Keys"][0], float(cost["Amount"])))
            token = page.get("NextPageToken")
            if not token:
                break
            request["NextPageToken"] = token

        return CostData(
            provider="aws",
            scope=str(linked) if linked else "all accounts",
            currency=currency,
            rows=rows,
        )
