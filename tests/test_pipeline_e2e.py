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


class FakeThreads:
    """Records what the pipeline asks of Slack's threads; can be told to fail."""

    def __init__(self, fail=False):
        self.calls, self.fail, self.count = [], fail, 0

    def _maybe_fail(self):
        if self.fail:
            raise SlackError("bot down")

    def open(self, fingerprint, payload):
        self._maybe_fail()
        self.count += 1
        self.calls.append(("open", payload["text"]))
        return f"ts-{self.count}"

    def follow_up(self, fingerprint, ts, anomaly, payload, opened, now, escalated, group=None):
        self._maybe_fail()
        self.calls.append(("follow_up", ts, escalated, group))

    def resolve(self, fingerprint, ts, posted, opened, now, group=None):
        self._maybe_fail()
        self.calls.append(("resolve", ts, posted["text"], group))

    def open_group(self, payload):
        self._maybe_fail()
        self.calls.append(("open_group", payload["text"]))
        return "group-1"

    def add_to_group(self, group, payload):
        self._maybe_fail()
        self.count += 1
        self.calls.append(("add_to_group", group, payload["text"]))
        return f"ts-{self.count}"

    def update_group(self, group, payload):
        self.calls.append(("update_group", group, payload["blocks"][0]["text"]["text"]))


QUIET_72 = (BASE + [12] * 12)[:72]


class ThreadTests(unittest.TestCase):
    # The pipeline tests' helpers, without running those tests a second time.
    config = PipelineTests.config
    run_once = PipelineTests.run_once

    def setUp(self):
        PipelineTests.setUp(self)
        self.threads = FakeThreads()

    def run_at(self, minutes, values, **kwargs):
        provider = FakeProvider({"cpu": make_series(values)})
        return self.run_once([make_spec()], provider, now=NOW + timedelta(minutes=minutes), threads=self.threads, **kwargs)

    def test_first_alert_opens_a_thread_not_a_webhook_post(self):
        result = self.run_at(0, SPIKE_72)
        self.assertEqual(result.posted, 1)
        self.assertEqual([c[0] for c in self.threads.calls], ["open"])
        self.assertEqual(self.posted, [])

    def test_a_repeat_after_the_cooldown_goes_in_the_thread(self):
        self.run_at(0, SPIKE_72)
        self.run_at(30, SPIKE_72)  # cooldown: nothing
        self.run_at(61, SPIKE_72)
        self.assertEqual([c[0] for c in self.threads.calls], ["open", "follow_up"])
        self.assertEqual(self.threads.calls[1][1], "ts-1")

    def test_quiet_runs_resolve_the_thread_once(self):
        self.run_at(0, SPIKE_72)
        self.run_at(5, QUIET_72)  # first quiet run: could be a blip
        self.assertEqual([c[0] for c in self.threads.calls], ["open"])
        result = self.run_at(10, QUIET_72)
        self.assertEqual(result.resolved, 1)
        self.assertEqual(self.threads.calls[-1][:2], ("resolve", "ts-1"))
        self.run_at(15, QUIET_72)
        self.assertEqual([c[0] for c in self.threads.calls].count("resolve"), 1)

    def test_firing_again_resets_the_quiet_count(self):
        self.run_at(0, SPIKE_72)
        self.run_at(5, QUIET_72)
        self.run_at(10, SPIKE_72)  # still firing (in cooldown, so no post)
        self.run_at(15, QUIET_72)
        self.assertNotIn("resolve", [c[0] for c in self.threads.calls])

    def test_a_metric_that_cannot_be_read_keeps_its_thread_open(self):
        self.run_at(0, SPIKE_72)
        for minutes in (5, 10, 15):
            self.run_once([make_spec()], FakeProvider({"cpu": RuntimeError("down")}),
                          now=NOW + timedelta(minutes=minutes), threads=self.threads)
        self.assertNotIn("resolve", [c[0] for c in self.threads.calls])

    def test_if_the_bot_fails_the_webhook_still_alerts(self):
        self.threads.fail = True
        result = self.run_at(0, SPIKE_72)
        self.assertEqual((result.posted, len(self.posted)), (1, 1))

    def test_without_threads_nothing_changes(self):
        self.run_once([make_spec()], FakeProvider({"cpu": make_series(SPIKE_72)}))
        self.assertEqual(len(self.posted), 1)


class GroupTests(unittest.TestCase):
    config = PipelineTests.config
    run_once = PipelineTests.run_once

    def setUp(self):
        PipelineTests.setUp(self)
        self.threads = FakeThreads()
        self.specs = [make_spec(name="cpu"), make_spec(name="mem", selector={"region": "us-east-1", "namespace": "AWS/EC2", "metric": "Mem"})]

    def run_at(self, minutes, cpu, mem):
        provider = FakeProvider({"cpu": make_series(cpu), "mem": make_series(mem, metric="Mem")})
        return self.run_once(self.specs, provider, now=NOW + timedelta(minutes=minutes), threads=self.threads)

    def kinds(self):
        return [c[0] for c in self.threads.calls]

    def test_alerts_that_fire_together_arrive_as_one_group(self):
        result = self.run_at(0, SPIKE_72, SPIKE_72)
        self.assertEqual(result.posted, 2)
        self.assertEqual(self.kinds(), ["open_group", "add_to_group", "add_to_group"])
        self.assertEqual(self.threads.calls[0][1], "2 alerts at once")
        self.assertEqual(self.posted, [])

    def test_a_lone_alert_is_not_a_group(self):
        self.run_at(0, SPIKE_72, QUIET_72)
        self.assertEqual(self.kinds(), ["open"])

    def test_members_resolve_in_the_group_thread_and_the_summary_follows(self):
        self.run_at(0, SPIKE_72, SPIKE_72)
        self.run_at(5, QUIET_72, SPIKE_72)
        self.run_at(10, QUIET_72, SPIKE_72)  # cpu resolves
        self.assertIn(("resolve", "ts-1", self.threads.calls[1][2], "group-1"), self.threads.calls)
        updates = [c[2] for c in self.threads.calls if c[0] == "update_group"]
        self.assertEqual(updates[-1], ":red_circle: 2 alerts at once · 1 resolved")
        self.run_at(15, QUIET_72, QUIET_72)
        self.run_at(20, QUIET_72, QUIET_72)  # mem resolves
        updates = [c[2] for c in self.threads.calls if c[0] == "update_group"]
        self.assertEqual(updates[-1], ":white_check_mark: RESOLVED · 2 alerts")

    def test_a_follow_up_goes_to_the_group_thread(self):
        self.run_at(0, SPIKE_72, SPIKE_72)
        self.run_at(61, SPIKE_72, SPIKE_72)
        follow = [c for c in self.threads.calls if c[0] == "follow_up"]
        self.assertEqual({c[3] for c in follow}, {"group-1"})
        self.assertEqual(len(follow), 2)

    def test_if_the_summary_fails_each_alert_goes_to_the_webhook(self):
        self.threads.fail = True
        result = self.run_at(0, SPIKE_72, SPIKE_72)
        self.assertEqual((result.posted, len(self.posted), result.post_errors), (2, 2, 0))

    def test_if_bot_and_webhook_both_fail_it_is_an_error_not_a_crash(self):
        self.threads.fail = True
        def broken(payload):
            raise SlackError("webhook down")
        result = self.run_once(self.specs, FakeProvider({"cpu": make_series(SPIKE_72), "mem": make_series(SPIKE_72, metric="Mem")}),
                               threads=self.threads, post=broken)
        self.assertEqual((result.posted, result.post_errors), (0, 2))
