import io
import json
import unittest
import urllib.error
from datetime import date
from email.message import Message
from unittest import mock

from anomaly_alerts.cost import CostProviderPool
from anomaly_alerts.cost import azure
from anomaly_alerts.cost.azure import AzureCostProvider
from anomaly_alerts.models import CostSpec, DailyCost

COLUMNS = [
    {"name": "Cost", "type": "Number"},
    {"name": "UsageDate", "type": "Number"},
    {"name": "ServiceName", "type": "String"},
    {"name": "Currency", "type": "String"},
]


def page(rows, columns=COLUMNS, next_link=None):
    return {"properties": {"columns": columns, "rows": rows, "nextLink": next_link}}


class FakeApi:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, url, body):
        self.calls.append((url, body))
        return self.pages.pop(0)


def spec(scope="/subscriptions/0000"):
    return CostSpec("azure-prod", "azure", {"scope": scope})


class AzureCostProviderTests(unittest.TestCase):
    def fetch(self, pages, **kwargs):
        api = FakeApi(pages)
        provider = AzureCostProvider(post=api)
        return provider.fetch(spec(**kwargs), date(2026, 10, 1), date(2026, 10, 29)), api

    def test_builds_a_daily_per_service_query(self):
        _, api = self.fetch([page([])])
        [(url, body)] = api.calls
        self.assertEqual(
            url,
            "https://management.azure.com/subscriptions/0000/providers/Microsoft.CostManagement/query"
            "?api-version=2023-03-01",
        )
        self.assertEqual(body["type"], "ActualCost")
        self.assertEqual(body["timeframe"], "Custom")
        # Our end date is exclusive; the API's "to" is inclusive.
        self.assertEqual(body["timePeriod"], {"from": "2026-10-01T00:00:00Z", "to": "2026-10-28T23:59:59Z"})
        self.assertEqual(body["dataset"]["granularity"], "Daily")
        self.assertEqual(body["dataset"]["grouping"], [{"type": "Dimension", "name": "ServiceName"}])

    def test_scope_slashes_are_normalised(self):
        data, api = self.fetch([page([])], scope="subscriptions/0000/")
        self.assertIn("azure.com/subscriptions/0000/providers", api.calls[0][0])
        self.assertEqual(data.scope, "/subscriptions/0000")

    def test_parses_rows_and_currency(self):
        rows = [
            [12.5, 20261027, "Virtual Machines", "EUR"],
            [0.25, 20261027, "Storage", "EUR"],
            [13, 20261028, "Virtual Machines", "EUR"],
        ]
        data, _ = self.fetch([page(rows)])
        self.assertEqual((data.provider, data.currency), ("azure", "EUR"))
        self.assertEqual(data.rows, [
            DailyCost(date(2026, 10, 27), "Virtual Machines", 12.5),
            DailyCost(date(2026, 10, 27), "Storage", 0.25),
            DailyCost(date(2026, 10, 28), "Virtual Machines", 13.0),
        ])

    def test_columns_are_found_by_name_in_any_order(self):
        columns = [
            {"name": "ServiceName"}, {"name": "Currency"}, {"name": "UsageDate"}, {"name": "PreTaxCost"},
        ]
        data, _ = self.fetch([page([["Functions", "USD", "2026-10-28T00:00:00", 4.0]], columns=columns)])
        self.assertEqual(data.rows, [DailyCost(date(2026, 10, 28), "Functions", 4.0)])

    def test_blank_service_is_grouped_as_other(self):
        data, _ = self.fetch([page([[1.0, 20261028, "", "USD"]])])
        self.assertEqual(data.rows[0].service, "Other")

    def test_follows_next_links_with_the_same_query(self):
        pages = [
            page([[1.0, 20261027, "VM", "USD"]], next_link="https://management.azure.com/next?skiptoken=x"),
            page([[2.0, 20261028, "VM", "USD"]]),
        ]
        data, api = self.fetch(pages)
        self.assertEqual(api.calls[1][0], "https://management.azure.com/next?skiptoken=x")
        self.assertEqual(api.calls[0][1], api.calls[1][1])
        self.assertEqual([r.amount for r in data.rows], [1.0, 2.0])

    def test_missing_cost_column_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.fetch([page([[20261028, "VM", "USD"]], columns=COLUMNS[1:])])

    def test_token_is_fetched_once_and_lazily(self):
        calls = []

        def token():
            calls.append(1)
            return "t"

        provider = AzureCostProvider(token=token)
        self.assertEqual(calls, [])
        sent = []
        fake_post = lambda tok, url, body: sent.append(tok) or page([])  # noqa: E731
        with mock.patch.object(azure, "_http_post", fake_post):
            provider.fetch(spec(), date(2026, 10, 1), date(2026, 10, 29))
            provider.fetch(spec(), date(2026, 10, 1), date(2026, 10, 29))
        self.assertEqual(calls, [1])
        self.assertEqual(sent, ["t", "t"])

    def test_pool_loads_the_azure_adapter(self):
        self.assertIsInstance(CostProviderPool().get("azure"), AzureCostProvider)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, headers=None):
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("https://x", code, "err", msg, io.BytesIO(b'{"error": "sub 0000"}'))


class HttpPostTests(unittest.TestCase):
    def post(self, outcomes):
        outcomes = list(outcomes)
        requests, waits = [], []

        def opener(request, timeout):
            requests.append(request)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return Response(json.dumps(outcome).encode())

        result = azure._http_post("tok", "https://x", {"a": 1}, opener=opener, sleep=waits.append)
        return result, requests, waits

    def test_sends_a_bearer_token_and_json(self):
        result, [request], _ = self.post([{"ok": True}])
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.get_header("Authorization"), "Bearer tok")
        self.assertEqual(json.loads(request.data), {"a": 1})

    def test_retries_throttling_using_the_cost_management_header(self):
        throttled = http_error(429, {"x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after": "7"})
        result, requests, waits = self.post([throttled, {"ok": True}])
        self.assertEqual((result, len(requests), waits), ({"ok": True}, 2, [7.0]))

    def test_retry_wait_is_capped(self):
        throttled = http_error(429, {"Retry-After": "600"})
        _, _, waits = self.post([throttled, {"ok": True}])
        self.assertEqual(waits, [azure.MAX_RETRY_WAIT])

    def test_gives_up_after_the_retries(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.post([http_error(503)] * (azure.MAX_RETRIES + 1))
        self.assertIn("HTTP 503", str(ctx.exception))

    def test_client_error_fails_fast_without_the_body(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.post([http_error(403)])
        self.assertEqual(str(ctx.exception), "Cost Management returned HTTP 403")


if __name__ == "__main__":
    unittest.main()
