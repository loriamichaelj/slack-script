"""Azure spend via the Cost Management query API, grouped by service.

Calls the REST API with the standard library and a token from azure-identity, so the
only Azure package needed is the one the metrics adapter already uses.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Callable

from ..models import CostData, CostSpec, DailyCost

API_VERSION = "2023-03-01"
ENDPOINT = "https://management.azure.com"
MAX_RETRIES = 3
MAX_RETRY_WAIT = 60.0
# Cost Management names its throttling header after the quota it hit.
_RETRY_HEADERS = (
    "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-client-retry-after",
    "Retry-After",
)
_COST_COLUMNS = ("Cost", "PreTaxCost", "totalCost")


def _default_token() -> str:
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(
            "azure-identity is not installed; run: pip install 'anomaly-alerts[azure]'"
        ) from exc
    return DefaultAzureCredential().get_token(f"{ENDPOINT}/.default").token


def _retry_wait(headers, attempt: int) -> float:
    for name in _RETRY_HEADERS:
        value = headers.get(name) if headers else None
        if value:
            try:
                return min(float(value), MAX_RETRY_WAIT)
            except ValueError:
                pass
    return min(2.0 ** (attempt + 1), MAX_RETRY_WAIT)


def _http_post(token: str, url: str, body: dict, *, opener=urllib.request.urlopen, sleep=time.sleep) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(MAX_RETRIES + 1):
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with opener(request, timeout=60) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable or attempt == MAX_RETRIES:
                # The response body is left out: it can echo subscription IDs.
                raise RuntimeError(f"Cost Management returned HTTP {exc.code}") from None
            sleep(_retry_wait(exc.headers, attempt))
    raise AssertionError("unreachable")


def _day(value) -> date:
    """UsageDate arrives as a number like 20261028, or as an ISO timestamp string."""
    text = str(value)
    if "-" in text:
        return date.fromisoformat(text[:10])
    return date.fromisoformat(str(int(value)))


def _column(columns: list[dict], names) -> int:
    lookup = {c["name"].lower(): i for i, c in enumerate(columns)}
    for name in names:
        if name.lower() in lookup:
            return lookup[name.lower()]
    raise RuntimeError(f"Cost Management response has no {names[0]} column")


class AzureCostProvider:
    def __init__(
        self,
        post: Callable[[str, dict], dict] | None = None,
        token: Callable[[], str] = _default_token,
    ):
        self._post = post
        self._token = token

    def _send(self, url: str, body: dict) -> dict:
        if self._post is None:
            access_token = self._token()
            self._post = lambda u, b: _http_post(access_token, u, b)
        return self._post(url, body)

    def fetch(self, spec: CostSpec, start: date, end: date) -> CostData:
        scope = "/" + str(spec.selector["scope"]).strip().strip("/")
        url = f"{ENDPOINT}{scope}/providers/Microsoft.CostManagement/query?api-version={API_VERSION}"
        last_day = end - timedelta(days=1)  # the API's "to" is inclusive; ours is not
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {"from": f"{start.isoformat()}T00:00:00Z", "to": f"{last_day.isoformat()}T23:59:59Z"},
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ServiceName"}],
            },
        }

        rows: list[DailyCost] = []
        currency = "USD"
        while url:
            props = self._send(url, body).get("properties", {})
            columns = props.get("columns", [])
            if props.get("rows"):
                cost_i = _column(columns, _COST_COLUMNS)
                date_i = _column(columns, ("UsageDate",))
                service_i = _column(columns, ("ServiceName",))
                currency_i = _column(columns, ("Currency", "BillingCurrency"))
                for row in props["rows"]:
                    day = _day(row[date_i])
                    currency = row[currency_i] or currency
                    rows.append(DailyCost(day, row[service_i] or "Other", float(row[cost_i])))
            url = props.get("nextLink")

        return CostData(provider="azure", scope=scope, currency=currency, rows=rows)
