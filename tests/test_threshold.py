import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

from anomaly_alerts import config, pipeline, routine
from anomaly_alerts.detectors.guards import evaluate
from anomaly_alerts.models import Anomaly
from anomaly_alerts.providers.azure import AzureProvider
from anomaly_alerts.slack import blocks
from helpers import NOW, make_series, make_spec


def limit_spec(**overrides):
    fields = dict(detector="threshold", threshold=0.0, direction="spike", min_points=0, sustained_points=1)
    fields.update(overrides)
    return make_spec(**fields)


class ThresholdGuardTests(unittest.TestCase):
    def test_any_event_past_the_limit_alerts_without_history(self):
        found = evaluate([0, 0, 1], limit_spec())
        self.assertIsNotNone(found)
        self.assertEqual((found.direction, found.observed, found.center), ("spike", 1, 0.0))
        self.assertIsNone(evaluate([5, 5, 0], limit_spec()))
        self.assertIsNotNone(evaluate([1], limit_spec()))

    def test_value_at_the_limit_is_not_past_it(self):
        self.assertIsNone(evaluate([0, 0, 0], limit_spec()))
        self.assertIsNone(evaluate([85, 85], limit_spec(threshold=85.0)))

    def test_drop_alerts_below_the_limit(self):
        spec = limit_spec(direction="drop", threshold=1.0, sustained_points=2)
        self.assertEqual(evaluate([1, 0, 0], spec).direction, "drop")
        self.assertIsNone(evaluate([1, 1, 0], spec))

    def test_a_learned_baseline_does_not_hide_a_steady_breach(self):
        # A statistical detector would learn 90 as normal; a fixed limit keeps alerting.
        self.assertIsNotNone(evaluate([90.0] * 60, limit_spec(threshold=85.0, sustained_points=3)))

    def test_a_long_breach_escalates_and_severity_can_be_fixed(self):
        spec = limit_spec(sustained_points=2)
        self.assertEqual(evaluate([0, 0, 1, 1], spec).severity, "warning")
        self.assertEqual(evaluate([1, 1, 1, 1], spec).severity, "critical")
        self.assertEqual(evaluate([0, 1], limit_spec(severity="critical")).severity, "critical")

    def test_fixed_severity_applies_to_statistical_detectors_too(self):
        values = [10 + (i % 5) for i in range(60)] + [50, 50, 50]
        self.assertEqual(evaluate(values, make_spec(severity="warning")).severity, "warning")


THRESHOLD_CONFIG = """
defaults: {lookback: 24h, period: 5m, detector: mad, min_points: 30}
metrics:
  - name: root-sign-in
    provider: aws
    region: us-east-1
    namespace: PlatformAudit
    metric: RootSignIn
    detector: threshold
    threshold: 0
    direction: spike
    sustained_points: 1
    severity: critical
"""


class ThresholdConfigTests(unittest.TestCase):
    def load(self, text):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "config.yaml"
        path.write_text(text)
        return config.load(path)

    def assertRejects(self, text, fragment):
        with self.assertRaises(config.ConfigError) as ctx:
            self.load(text)
        self.assertIn(fragment, str(ctx.exception))

    def test_threshold_metric_loads(self):
        spec = self.load(THRESHOLD_CONFIG).metrics[0]
        self.assertEqual((spec.detector, spec.threshold, spec.min_points), ("threshold", 0.0, 0))
        self.assertEqual(spec.severity, "critical")

    def test_limit_may_be_zero_or_negative_and_lookback_may_be_short(self):
        spec = self.load(THRESHOLD_CONFIG.replace("threshold: 0", "threshold: -1").replace(
            "lookback: 24h", "lookback: 15m")).metrics[0]
        self.assertEqual(spec.threshold, -1.0)

    def test_threshold_rules(self):
        self.assertRejects(THRESHOLD_CONFIG.replace("    threshold: 0\n", ""), "needs threshold")
        self.assertRejects(THRESHOLD_CONFIG.replace("direction: spike", "direction: both"), "needs direction")
        self.assertRejects(THRESHOLD_CONFIG.replace("severity: critical", "severity: loud"), "severity must be one of")


AZURE_LOGS = """
metrics:
  - name: role-assignments
    provider: azure
    workspace_id: 00000000-0000-0000-0000-000000000000
    query: AzureActivity | where OperationNameValue =~ "Microsoft.Authorization/roleAssignments/write"
    detector: threshold
    threshold: 0
    direction: spike
    sustained_points: 1
"""


class AzureLogConfigTests(ThresholdConfigTests):
    def test_threshold_metric_loads(self):
        spec = self.load(AZURE_LOGS).metrics[0]
        self.assertEqual(set(spec.selector), {"workspace_id", "query"})

    def test_limit_may_be_zero_or_negative_and_lookback_may_be_short(self):
        pass

    def test_threshold_rules(self):
        self.assertRejects(AZURE_LOGS.replace("    query: ", "    q: "), "unknown key(s) ['q']")
        self.assertRejects(AZURE_LOGS + "    metric: x\n", "unknown key(s) ['metric']")
        self.assertRejects(AZURE_LOGS.replace("query: AzureActivity", "query: ''\n    x_: AzureActivity"),
                           "unknown key")


class FakeLogs:
    def __init__(self, rows, partial=None):
        self.rows, self.partial, self.call = rows, partial, None

    def query_workspace(self, workspace_id, query, timespan):
        self.call = (workspace_id, query, timespan)
        return self._result()

    def query_resource(self, resource_id, query, timespan):
        self.call = ("resource", resource_id, query, timespan)
        return self._result()

    def _result(self):
        if self.partial:
            return NS(partial_error=self.partial, partial_data=[])
        return NS(tables=[NS(columns=["TimeGenerated", "value"], rows=self.rows)])


class AzureLogProviderTests(unittest.TestCase):
    def spec(self):
        selector = {"workspace_id": "ws-1", "query": "AzureActivity | where Level == 'Error'  "}
        return make_spec(name="activity-errors", provider="azure", selector=selector, period_seconds=300)

    def test_counts_rows_per_period(self):
        t = datetime(2026, 10, 28, 11, 0)
        fake = FakeLogs([[t + timedelta(minutes=5), 2], [t, 1]])
        series = AzureProvider(logs_client=fake).fetch(self.spec(), NOW - timedelta(hours=1), NOW)
        workspace, query, timespan = fake.call
        self.assertEqual(workspace, "ws-1")
        self.assertTrue(query.endswith("| summarize value = count() by bin(TimeGenerated, 300s)"))
        self.assertIn("AzureActivity | where Level == 'Error'\n|", query)
        self.assertEqual(timespan, (NOW - timedelta(hours=1), NOW))
        self.assertEqual([p.value for p in series.points], [1.0, 2.0])
        self.assertEqual(series.points[0].ts.tzinfo, UTC)
        self.assertEqual((series.resource, series.metric, series.scope), ("activity-errors", "log query", "ws-1"))

    def test_a_resource_id_is_queried_as_a_resource(self):
        rid = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w"
        spec = make_spec(name="x", provider="azure", selector={"workspace_id": rid, "query": "AzureActivity"})
        fake = FakeLogs([[datetime(2026, 10, 28, 11, 0), 1]])
        series = AzureProvider(logs_client=fake).fetch(spec, NOW - timedelta(hours=1), NOW)
        self.assertEqual(fake.call[:2], ("resource", rid))
        self.assertEqual(series.scope, "sub-1")

    def test_partial_result_is_an_error(self):
        with self.assertRaises(RuntimeError):
            AzureProvider(logs_client=FakeLogs([], partial="timeout")).fetch(self.spec(), NOW, NOW)


class ThresholdMessageTests(unittest.TestCase):
    def test_alert_says_limit_not_baseline(self):
        spec = limit_spec()
        series = make_series([0, 0, 2])
        det = evaluate([0, 0, 2], spec)
        anomaly = Anomaly(spec, series, det, NOW - timedelta(minutes=5), NOW, [0, 0, 2])
        payload = blocks.build_payload(anomaly, ["look"])
        text = str(payload)
        self.assertIn("*Limit*\\n0", text)
        self.assertIn("2 above the limit", text)
        self.assertIn("vs limit 0", payload["text"])
        self.assertNotIn("baseline", text)
        self.assertNotIn("Usual", text)

    def test_digest_row_shows_the_limit_and_never_waits_for_a_baseline(self):
        spec = limit_spec(threshold=85.0)
        outcome = pipeline.MetricOutcome(spec, series=make_series([10.0]), values=[10.0])
        row = routine._row(outcome)
        self.assertEqual((row.status, row.center, row.center_label), (routine.OK, 85.0, "limit"))


if __name__ == "__main__":
    unittest.main()


class ReadLessTests(unittest.TestCase):
    def test_within_catches_a_breach_in_an_earlier_period(self):
        spec = limit_spec(within=2)
        found = evaluate([0, 0, 3, 0], spec)  # the event's period is no longer the newest
        self.assertIsNotNone(found)
        self.assertEqual((found.observed, found.ago), (3, 1))
        self.assertIsNone(evaluate([3, 0, 0], spec))  # older than `within`
        self.assertEqual(evaluate([0, 3, 5], spec).ago, 0)  # the newest wins

    def test_window_points_at_the_period_that_breached(self):
        spec = limit_spec(within=2)
        values = [0, 0, 3, 0]
        from helpers import make_points
        points = make_points(values)
        anomaly = pipeline._detect(spec, make_series(values), points, points[0].ts, NOW)
        self.assertEqual(anomaly.window_start, points[2].ts)

    def test_due_reads_once_per_boundary(self):
        spec = limit_spec(every_seconds=1800)
        at = lambda h, m, s=0: datetime(2026, 11, 23, h, m, s, tzinfo=UTC)
        self.assertTrue(pipeline.due(spec, at(19, 0, 46), 300))
        self.assertFalse(pipeline.due(spec, at(19, 5, 46), 300))
        self.assertFalse(pipeline.due(spec, at(19, 25, 46), 300))
        self.assertTrue(pipeline.due(spec, at(19, 30, 40), 300))
        self.assertTrue(pipeline.due(limit_spec(), at(19, 5, 46), 300))  # no `every`: every run

    def load(self, text):
        return ThresholdConfigTests.load(self, text)

    def test_config_rules_for_every_and_within(self):
        loader = self
        cfg = loader.load(THRESHOLD_CONFIG + "    every: 30m\n    within: 2\n    period: 30m\n    lookback: 3h\n")
        spec = cfg.metrics[0]
        self.assertEqual((spec.every_seconds, spec.within, cfg.run_every_seconds), (1800, 2, 300))
        with self.assertRaises(config.ConfigError):
            loader.load(THRESHOLD_CONFIG + "    every: 7m\n")  # not a whole number of 5m periods
        with self.assertRaises(config.ConfigError):
            loader.load(THRESHOLD_CONFIG.replace("    detector: threshold\n", "") + "    within: 2\n")
