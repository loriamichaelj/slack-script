import unittest
from datetime import UTC, datetime

from anomaly_alerts.providers.aws import AwsProvider
from helpers import NOW, make_spec


class FakePaginator:
    def __init__(self, pages):
        self.pages, self.kwargs = pages, None

    def paginate(self, **kwargs):
        self.kwargs = kwargs
        return iter(self.pages)


class FakeCloudWatch:
    def __init__(self, pages):
        self.paginator = FakePaginator(pages)
        self.operation = None

    def get_paginator(self, operation):
        self.operation = operation
        return self.paginator


def ts(minute):
    return datetime(2026, 10, 28, 11, minute, tzinfo=UTC)


class AwsProviderTests(unittest.TestCase):
    def spec(self, **selector):
        base = {
            "region": "us-east-1",
            "namespace": "AWS/ApplicationELB",
            "metric": "HTTPCode_Target_5XX_Count",
            "dimensions": {"LoadBalancer": "app/prod-api/abc"},
            "stat": "Sum",
        }
        base.update(selector)
        return make_spec(provider="aws", selector=base)

    def test_builds_the_query_and_sorts_points(self):
        pages = [
            {"MetricDataResults": [{"Timestamps": [ts(10), ts(0)], "Values": [3.0, 1.0]}]},
            {"MetricDataResults": [{"Timestamps": [ts(5)], "Values": [2.0]}]},
        ]
        fake = FakeCloudWatch(pages)
        provider = AwsProvider(client_factory=lambda region: fake)
        start = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)

        series = provider.fetch(self.spec(), start, NOW)

        self.assertEqual(fake.operation, "get_metric_data")
        kwargs = fake.paginator.kwargs
        self.assertEqual(kwargs["ScanBy"], "TimestampAscending")
        self.assertEqual((kwargs["StartTime"], kwargs["EndTime"]), (start, NOW))
        stat = kwargs["MetricDataQueries"][0]["MetricStat"]
        self.assertEqual(stat["Stat"], "Sum")
        self.assertEqual(stat["Period"], 300)
        self.assertEqual(stat["Metric"]["Namespace"], "AWS/ApplicationELB")
        self.assertEqual(stat["Metric"]["Dimensions"], [{"Name": "LoadBalancer", "Value": "app/prod-api/abc"}])
        self.assertEqual([p.value for p in series.points], [1.0, 2.0, 3.0])
        self.assertEqual(series.provider, "aws")
        self.assertEqual(series.scope, "us-east-1")
        self.assertEqual(series.resource, "app/prod-api/abc")
        self.assertIn("us-east-1.console.aws.amazon.com", series.console_url)

    def test_default_stat_is_average(self):
        fake = FakeCloudWatch([{"MetricDataResults": []}])
        provider = AwsProvider(client_factory=lambda region: fake)
        spec = make_spec(provider="aws", selector={"region": "eu-west-1", "namespace": "AWS/EC2", "metric": "CPUUtilization"})
        series = provider.fetch(spec, NOW, NOW)
        self.assertEqual(fake.paginator.kwargs["MetricDataQueries"][0]["MetricStat"]["Stat"], "Average")
        self.assertEqual(series.points, [])
        self.assertEqual(series.resource, "AWS/EC2")  # no dimensions to name it by

    def test_one_client_per_region(self):
        made = []

        def factory(region):
            made.append(region)
            return FakeCloudWatch([{"MetricDataResults": []}])

        provider = AwsProvider(client_factory=factory)
        for _ in range(3):
            provider.fetch(self.spec(), NOW, NOW)
        provider.fetch(self.spec(region="eu-west-1"), NOW, NOW)
        self.assertEqual(made, ["us-east-1", "eu-west-1"])


if __name__ == "__main__":
    unittest.main()
