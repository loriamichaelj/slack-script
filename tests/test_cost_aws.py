import unittest
from datetime import date
from unittest import mock

from anomaly_alerts.cost import CostProviderPool
from anomaly_alerts.cost.aws import AwsCostProvider
from anomaly_alerts.models import CostSpec, DailyCost


def group(service, amount, unit="USD"):
    return {"Keys": [service], "Metrics": {"UnblendedCost": {"Amount": str(amount), "Unit": unit}}}


def day_result(start, *groups):
    return {"TimePeriod": {"Start": start, "End": "unused"}, "Groups": list(groups), "Estimated": True}


class FakeCostExplorer:
    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []

    def get_cost_and_usage(self, **request):
        self.requests.append(dict(request))
        return self.pages.pop(0)


def spec(**selector):
    return CostSpec("aws-main", "aws", selector)


class AwsCostProviderTests(unittest.TestCase):
    def fetch(self, pages, **selector):
        fake = FakeCostExplorer(pages)
        provider = AwsCostProvider(client_factory=lambda: fake)
        return provider.fetch(spec(**selector), date(2026, 10, 1), date(2026, 10, 29)), fake

    def test_builds_a_daily_per_service_request(self):
        _, fake = self.fetch([{"ResultsByTime": []}])
        [request] = fake.requests
        self.assertEqual(request["TimePeriod"], {"Start": "2026-10-01", "End": "2026-10-29"})
        self.assertEqual(request["Granularity"], "DAILY")
        self.assertEqual(request["Metrics"], ["UnblendedCost"])
        self.assertEqual(request["GroupBy"], [{"Type": "DIMENSION", "Key": "SERVICE"}])
        self.assertNotIn("Filter", request)

    def test_parses_rows_currency_and_scope(self):
        pages = [{"ResultsByTime": [
            day_result("2026-10-27", group("Amazon EC2", "12.5"), group("Amazon S3", "0.25")),
            day_result("2026-10-28", group("Amazon EC2", "13")),
        ]}]
        data, _ = self.fetch(pages)
        self.assertEqual((data.provider, data.scope, data.currency), ("aws", "all accounts", "USD"))
        self.assertEqual(data.rows, [
            DailyCost(date(2026, 10, 27), "Amazon EC2", 12.5),
            DailyCost(date(2026, 10, 27), "Amazon S3", 0.25),
            DailyCost(date(2026, 10, 28), "Amazon EC2", 13.0),
        ])

    def test_linked_account_filters_the_request(self):
        data, fake = self.fetch([{"ResultsByTime": []}], linked_account=123456789012)
        self.assertEqual(
            fake.requests[0]["Filter"],
            {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": ["123456789012"]}},
        )
        self.assertEqual(data.scope, "123456789012")

    def test_follows_page_tokens(self):
        pages = [
            {"ResultsByTime": [day_result("2026-10-27", group("Amazon EC2", 1))], "NextPageToken": "t1"},
            {"ResultsByTime": [day_result("2026-10-28", group("Amazon EC2", 2))]},
        ]
        data, fake = self.fetch(pages)
        self.assertEqual(len(fake.requests), 2)
        self.assertNotIn("NextPageToken", fake.requests[0])
        self.assertEqual(fake.requests[1]["NextPageToken"], "t1")
        self.assertEqual([r.amount for r in data.rows], [1.0, 2.0])

    def test_currency_comes_from_the_response(self):
        data, _ = self.fetch([{"ResultsByTime": [day_result("2026-10-28", group("EC2", 1, unit="EUR"))]}])
        self.assertEqual(data.currency, "EUR")

    def test_day_with_no_groups_adds_no_rows(self):
        data, _ = self.fetch([{"ResultsByTime": [day_result("2026-10-28")]}])
        self.assertEqual(data.rows, [])

    def test_client_is_created_once(self):
        calls = []
        fake = FakeCostExplorer([{"ResultsByTime": []}, {"ResultsByTime": []}])

        def factory():
            calls.append(1)
            return fake

        provider = AwsCostProvider(client_factory=factory)
        provider.fetch(spec(), date(2026, 10, 1), date(2026, 10, 29))
        provider.fetch(spec(), date(2026, 10, 1), date(2026, 10, 29))
        self.assertEqual(len(calls), 1)

    def test_missing_boto3_names_the_extra(self):
        with mock.patch.dict("sys.modules", {"boto3": None}):
            with self.assertRaises(RuntimeError) as ctx:
                AwsCostProvider().fetch(spec(), date(2026, 10, 1), date(2026, 10, 29))
        self.assertIn("anomaly-alerts[aws]", str(ctx.exception))

    def test_pool_loads_the_aws_adapter(self):
        self.assertIsInstance(CostProviderPool().get("aws"), AwsCostProvider)


if __name__ == "__main__":
    unittest.main()
