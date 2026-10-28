import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from anomaly_alerts import pipeline
from anomaly_alerts.config import Config, SlackConfig
from anomaly_alerts.models import Point
from anomaly_alerts.providers import ProviderPool
from anomaly_alerts.slack.client import SlackError
from anomaly_alerts.state import StateStore
from helpers import BASE, NOW, make_points, make_series, make_spec

SPIKE_72 = (BASE + [12] * 12)[:69] + [60, 60, 60]  # 72 points = 6h at 5m


class FakeProvider:
    def __init__(self, by_name):
        self.by_name, self.calls = by_name, []

    def fetch(self, spec, start, end):
        self.calls.append((spec.name, start, end))
        result = self.by_name[spec.name]
        if isinstance(result, Exception):
            raise result
        return result


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.state_path = Path(self.dir.name) / "alerts.json"
        self.posted = []

    def config(self, specs, cap=10):
        return Config(SlackConfig("X", 3600, cap), self.state_path, None, specs)

    def run_once(self, specs, provider, now=NOW, cap=10, post=None, **kwargs):
        state = StateStore(self.state_path, 3600)
        state.load()
        return pipeline.run(
            self.config(specs, cap),
            ProviderPool({"aws": provider}),
            [],
            state,
            post or self.posted.append,
            now,
            **kwargs,
        )

    def test_spike_reaches_slack_end_to_end(self):
        provider = FakeProvider({"cpu": make_series(SPIKE_72)})
        result = self.run_once([make_spec()], provider)

        self.assertTrue(result.ok)
        self.assertEqual((result.fetched, result.anomalies, result.posted), (1, 1, 1))
        payload = self.posted[0]
        self.assertIn("[CRITICAL] AWS cpu CPUUtilization", payload["text"])
        # the provider was asked for exactly the lookback window, aligned to the period
        _, start, end = provider.calls[0]
        self.assertEqual(end, NOW)
        self.assertEqual(start, NOW - timedelta(hours=6))

    def test_quiet_data_posts_nothing(self):
        provider = FakeProvider({"cpu": make_series((BASE + [12] * 12)[:72])})
        result = self.run_once([make_spec()], provider)
        self.assertEqual((result.anomalies, result.posted), (0, 0))
        self.assertEqual(self.posted, [])

    def test_second_run_is_silenced_by_the_cooldown(self):
        provider = FakeProvider({"cpu": make_series(SPIKE_72)})
        self.run_once([make_spec()], provider)
        later = NOW + timedelta(minutes=5)
        provider2 = FakeProvider({"cpu": make_series(SPIKE_72, points=make_points(SPIKE_72, end=later))})
        result = self.run_once([make_spec()], provider2, now=later)
        self.assertEqual((result.anomalies, result.in_cooldown, result.posted), (1, 1, 0))
        self.assertEqual(len(self.posted), 1)

    def test_newest_incomplete_period_is_ignored(self):
        # The last point's period is still open at NOW, so it must not count.
        points = make_points(SPIKE_72, end=NOW + timedelta(minutes=5))
        provider = FakeProvider({"cpu": make_series(SPIKE_72, points=points)})
        result = self.run_once([make_spec()], provider)
        # With the open period dropped the window is [12, 60, 60]: mixed, so no alert.
        self.assertEqual(result.anomalies, 0)

    def test_zero_fill_turns_missing_periods_into_zeros(self):
        # A count metric that is usually absent: only the final three periods reported.
        quiet = make_points([20, 20, 20])
        spec = make_spec(fill_missing="zero", min_abs_change=5)
        provider = FakeProvider({"cpu": make_series([], points=quiet)})
        result = self.run_once([spec], provider)
        self.assertEqual(result.posted, 1)
        self.assertIn("20", self.posted[0]["text"])

    def test_dropping_gaps_leaves_too_little_history(self):
        provider = FakeProvider({"cpu": make_series([], points=make_points([20, 20, 20]))})
        with self.assertLogs("anomaly_alerts.pipeline", "WARNING") as logs:
            result = self.run_once([make_spec()], provider)
        self.assertEqual(result.anomalies, 0)
        self.assertIn("data gap", logs.output[0])

    def test_a_failing_provider_does_not_stop_the_rest(self):
        provider = FakeProvider({"bad": RuntimeError("boom"), "good": make_series(SPIKE_72)})
        specs = [make_spec(name="bad"), make_spec(name="good", selector={"region": "r"})]
        with self.assertLogs("anomaly_alerts.pipeline", "ERROR"):
            result = self.run_once(specs, provider)
        self.assertFalse(result.ok)
        self.assertEqual((result.fetch_errors, result.fetched, result.posted), (1, 1, 1))

    def test_alert_limit_posts_the_worst_first_and_one_summary(self):
        series = {
            f"m{i}": make_series(BASE + [12] * 9 + [10 + 30 * (i + 1)] * 3, resource=f"r{i}")
            for i in range(3)
        }
        specs = [make_spec(name=name, selector={"region": "r"}) for name in series]
        result = self.run_once(specs, FakeProvider(series), cap=2)

        self.assertEqual((result.anomalies, result.posted, result.over_limit), (3, 2, 1))
        self.assertEqual(len(self.posted), 3)
        self.assertIn("1 more anomaly suppressed", self.posted[2]["text"])
        # the biggest deviation is posted first
        self.assertIn("m2", self.posted[0]["text"])

    def test_failed_post_is_reported_and_retried_next_run(self):
        def failing(payload):
            raise SlackError("down")

        provider = FakeProvider({"cpu": make_series(SPIKE_72)})
        with self.assertLogs("anomaly_alerts.pipeline", "ERROR"):
            result = self.run_once([make_spec()], provider, post=failing)
        self.assertEqual((result.posted, result.post_errors), (0, 1))
        self.assertFalse(result.ok)
        # nothing was recorded, so the next run alerts again
        again = self.run_once([make_spec()], provider)
        self.assertEqual(again.posted, 1)

    def test_dry_run_prints_but_never_saves_state(self):
        provider = FakeProvider({"cpu": make_series(SPIKE_72)})
        result = self.run_once([make_spec()], provider, dry_run=True)
        self.assertEqual(result.posted, 1)
        self.assertFalse(self.state_path.exists())

    def test_only_filters_by_provider(self):
        provider = FakeProvider({"cpu": make_series(SPIKE_72)})
        result = self.run_once([make_spec()], provider, only="gcp")
        self.assertEqual(result.fetched, 0)
        self.assertEqual(provider.calls, [])

    def test_clean_points_aligns_orders_and_dedups(self):
        spec = make_spec()
        start = NOW - timedelta(hours=1)
        raw = [
            Point(NOW - timedelta(minutes=10), 2.0),
            Point(NOW - timedelta(minutes=15), 1.0),
            Point(NOW - timedelta(minutes=10, seconds=-30), 9.0),  # same period as the first
            Point(NOW - timedelta(hours=2), 5.0),  # before the window
        ]
        cleaned = pipeline.clean_points(raw, spec, start, NOW)
        self.assertEqual([p.value for p in cleaned], [1.0, 9.0])


if __name__ == "__main__":
    unittest.main()
