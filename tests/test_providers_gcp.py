import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from anomaly_alerts.providers.gcp import GcpProvider
from helpers import NOW, make_spec


class FakeClient:
    def __init__(self, series_list):
        self.series_list, self.request = series_list, None

    def list_time_series(self, request):
        self.request = request
        return iter(self.series_list)


def point(minute, value):
    # GCP stamps an aligned point with the END of its period.
    end = datetime(2026, 10, 28, 11, minute, tzinfo=UTC)
    return NS(interval=NS(end_time=end), value=NS(double_value=value, int64_value=0))


class GcpProviderTests(unittest.TestCase):
    def spec(self, **selector):
        base = {"project": "my-proj", "metric_type": "compute.googleapis.com/instance/cpu/utilization"}
        base.update(selector)
        return make_spec(provider="gcp", selector=base)

    def test_request_shape(self):
        fake = FakeClient([])
        GcpProvider(client=fake).fetch(
            self.spec(filter='resource.labels.instance_id = "1"', aligner="ALIGN_RATE", reducer="REDUCE_SUM"),
            NOW - timedelta(hours=6),
            NOW,
        )
        request = fake.request
        self.assertEqual(request["name"], "projects/my-proj")
        self.assertEqual(
            request["filter"],
            'metric.type = "compute.googleapis.com/instance/cpu/utilization" '
            'AND resource.labels.instance_id = "1"',
        )
        self.assertEqual(request["aggregation"]["alignment_period"], {"seconds": 300})
        self.assertEqual(request["aggregation"]["per_series_aligner"], "ALIGN_RATE")
        self.assertEqual(request["aggregation"]["cross_series_reducer"], "REDUCE_SUM")
        self.assertEqual(request["interval"], {"start_time": NOW - timedelta(hours=6), "end_time": NOW})

    def test_defaults(self):
        fake = FakeClient([])
        GcpProvider(client=fake).fetch(self.spec(), NOW, NOW)
        self.assertEqual(fake.request["aggregation"]["per_series_aligner"], "ALIGN_MEAN")
        self.assertEqual(fake.request["aggregation"]["cross_series_reducer"], "REDUCE_NONE")
        self.assertTrue(fake.request["filter"].startswith('metric.type = "'))
        self.assertNotIn("AND", fake.request["filter"])

    def test_points_are_reversed_and_re_stamped_to_period_start(self):
        # newest first, end-of-period timestamps
        fake = FakeClient([NS(points=[point(10, 3.0), point(5, 2.0)])])
        series = GcpProvider(client=fake).fetch(self.spec(), NOW, NOW)
        self.assertEqual([p.value for p in series.points], [2.0, 3.0])
        self.assertEqual(series.points[0].ts, datetime(2026, 10, 28, 11, 0, tzinfo=UTC))  # 11:05 minus 5m
        self.assertEqual(series.points[1].ts, datetime(2026, 10, 28, 11, 5, tzinfo=UTC))

    def test_integer_values_are_read(self):
        item = NS(interval=NS(end_time=datetime(2026, 10, 28, 11, 5, tzinfo=UTC)),
                  value=NS(double_value=0.0, int64_value=42))
        series = GcpProvider(client=FakeClient([NS(points=[item])])).fetch(self.spec(), NOW, NOW)
        self.assertEqual(series.points[0].value, 42.0)

    def test_several_matching_series_is_an_error(self):
        fake = FakeClient([NS(points=[]), NS(points=[])])
        with self.assertRaisesRegex(RuntimeError, "2 time series matched"):
            GcpProvider(client=fake).fetch(self.spec(), NOW, NOW)

    def test_no_series_gives_empty_points(self):
        series = GcpProvider(client=FakeClient([])).fetch(self.spec(), NOW, NOW)
        self.assertEqual(series.points, [])
        self.assertEqual(series.scope, "my-proj")


if __name__ == "__main__":
    unittest.main()
