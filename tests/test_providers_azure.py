import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from anomaly_alerts.providers.azure import AzureProvider
from helpers import NOW, make_spec

RESOURCE = "/subscriptions/sub-123/resourceGroups/prod/providers/Microsoft.Compute/virtualMachines/web-1"


class FakeClient:
    def __init__(self, data, unit="Percent"):
        self.data, self.unit, self.call = data, unit, None

    def query_resource(self, resource_id, **kwargs):
        self.call = (resource_id, kwargs)
        return NS(metrics=[NS(unit=self.unit, timeseries=[NS(data=self.data)])])


def item(minute, **values):
    base = {"average": None, "total": None, "maximum": None, "minimum": None, "count": None}
    base.update(values)
    return NS(timestamp=datetime(2026, 10, 28, 11, minute, tzinfo=UTC), **base)


class AzureProviderTests(unittest.TestCase):
    def spec(self, **selector):
        base = {"resource_id": RESOURCE, "metric": "Percentage CPU"}
        base.update(selector)
        return make_spec(provider="azure", selector=base)

    def test_queries_with_granularity_and_aggregation(self):
        fake = FakeClient([item(0, average=10.0)])
        AzureProvider(client=fake).fetch(self.spec(aggregation="total"), NOW - timedelta(hours=6), NOW)
        resource_id, kwargs = fake.call
        self.assertEqual(resource_id, RESOURCE)
        self.assertEqual(kwargs["metric_names"], ["Percentage CPU"])
        self.assertEqual(kwargs["granularity"], timedelta(seconds=300))
        self.assertEqual(kwargs["aggregations"], ["Total"])
        self.assertEqual(kwargs["timespan"], (NOW - timedelta(hours=6), NOW))
        self.assertNotIn("metric_namespace", kwargs)

    def test_namespace_is_passed_when_set(self):
        fake = FakeClient([])
        AzureProvider(client=fake).fetch(self.spec(namespace="Custom/Ns"), NOW, NOW)
        self.assertEqual(fake.call[1]["metric_namespace"], "Custom/Ns")

    def test_gaps_are_dropped_and_points_sorted(self):
        fake = FakeClient([item(10, average=30.0), item(5, average=None), item(0, average=10.0)])
        series = AzureProvider(client=fake).fetch(self.spec(), NOW, NOW)
        self.assertEqual([p.value for p in series.points], [10.0, 30.0])

    def test_reads_the_attribute_for_the_chosen_aggregation(self):
        fake = FakeClient([item(0, average=1.0, total=99.0)])
        series = AzureProvider(client=fake).fetch(self.spec(aggregation="Total"), NOW, NOW)
        self.assertEqual(series.points[0].value, 99.0)

    def test_series_labels(self):
        series = AzureProvider(client=FakeClient([item(0, average=1.0)])).fetch(self.spec(), NOW, NOW)
        self.assertEqual(series.provider, "azure")
        self.assertEqual(series.resource, "web-1")
        self.assertEqual(series.scope, "sub-123")
        self.assertEqual(series.unit, "Percent")
        self.assertTrue(series.console_url.startswith("https://portal.azure.com/"))

    def test_naive_timestamps_become_utc(self):
        naive = NS(timestamp=datetime(2026, 10, 28, 11, 0), average=1.0)
        series = AzureProvider(client=FakeClient([naive])).fetch(self.spec(), NOW, NOW)
        self.assertEqual(series.points[0].ts.tzinfo, UTC)


if __name__ == "__main__":
    unittest.main()
