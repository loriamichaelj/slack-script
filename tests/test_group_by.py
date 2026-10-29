"""Metrics split by group_by: one GCP query, one series and one alert per group."""
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS

from anomaly_alerts import config, pipeline, routine
from anomaly_alerts.config import Config, SlackConfig
from anomaly_alerts.providers import ProviderPool
from anomaly_alerts.providers.gcp import GcpProvider
from anomaly_alerts.state import StateStore
from helpers import BASE, NOW, make_series, make_spec

QUIET_72 = (BASE + [12] * 12)[:72]
SPIKE_72 = (BASE + [12] * 12)[:69] + [60, 60, 60]
GROUP = ["resource.labels.project_id"]


class FakeClient:
    def __init__(self, series_list):
        self.series_list, self.request = series_list, None

    def list_time_series(self, request):
        self.request = request
        return iter(self.series_list)


def ts(project, values=(1.0,), metric_labels=None):
    points = [
        NS(interval=NS(end_time=datetime(2026, 10, 28, 11, 5 * (i + 1), tzinfo=UTC)),
           value=NS(double_value=v, int64_value=0))
        for i, v in enumerate(values)
    ]
    return NS(
        resource=NS(type="global", labels={"project_id": project} if project else {}),
        metric=NS(labels=metric_labels or {}),
        points=points,
    )


def gcp_spec(**selector):
    base = {"project": "scoping", "metric_type": "logging.googleapis.com/log_entry_count", "group_by": GROUP}
    base.update(selector)
    return make_spec(name="errors", provider="gcp", selector=base)


class GcpGroupByTests(unittest.TestCase):
    def fetch(self, series_list, **selector):
        fake = FakeClient(series_list)
        return GcpProvider(client=fake).fetch(gcp_spec(**selector), NOW, NOW), fake

    def test_request_groups_and_defaults_to_a_sum(self):
        _, fake = self.fetch([])
        aggregation = fake.request["aggregation"]
        self.assertEqual(fake.request["name"], "projects/scoping")
        self.assertEqual(aggregation["group_by_fields"], GROUP)
        self.assertEqual(aggregation["cross_series_reducer"], "REDUCE_SUM")

    def test_explicit_reducer_is_kept(self):
        _, fake = self.fetch([], reducer="REDUCE_MAX")
        self.assertEqual(fake.request["aggregation"]["cross_series_reducer"], "REDUCE_MAX")

    def test_one_series_per_project_scoped_to_that_project(self):
        result, _ = self.fetch([ts("proj-a", (1.0, 2.0)), ts("proj-b", (5.0,))])
        self.assertEqual([(s.group, s.scope, s.resource) for s in result],
                         [("proj-a", "proj-a", "proj-a"), ("proj-b", "proj-b", "proj-b")])
        self.assertEqual([p.value for p in result[0].points], [1.0, 2.0])
        self.assertIn("project=proj-a", result[0].console_url)

    def test_resource_types_in_one_group_are_summed(self):
        a = ts("proj-a", (1.0, 2.0))
        b = ts("proj-a", (10.0,))
        b.resource.type = "audited_resource"
        [series] = self.fetch([a, b])[0]
        self.assertEqual([p.value for p in series.points], [11.0, 2.0])

    def test_max_reducer_merges_with_max(self):
        [series] = self.fetch([ts("proj-a", (1.0, 7.0)), ts("proj-a", (4.0, 2.0))], reducer="REDUCE_MAX")[0]
        self.assertEqual([p.value for p in series.points], [4.0, 7.0])

    def test_mean_reducer_keeps_resource_types_apart(self):
        a, b = ts("proj-a"), ts("proj-a")
        b.resource.type = "audited_resource"
        result, _ = self.fetch([a, b], reducer="REDUCE_MEAN")
        self.assertEqual([s.group for s in result], ["proj-a, global", "proj-a, audited_resource"])
        self.assertEqual({s.scope for s in result}, {"proj-a"})

    def test_no_series_is_an_empty_list(self):
        result, _ = self.fetch([])
        self.assertEqual(result, [])

    def test_metric_labels_and_missing_values(self):
        fields = ["resource.labels.project_id", "metric.label.severity"]
        result, _ = self.fetch([ts(None, metric_labels={"severity": "ERROR"})], group_by=fields)
        [series] = result
        self.assertEqual(series.group, "(none), ERROR")
        self.assertEqual(series.scope, "scoping")  # no project label: falls back to the queried project

    def test_without_group_by_several_series_is_still_an_error(self):
        fake = FakeClient([ts("a"), ts("b")])
        spec = make_spec(provider="gcp", selector={"project": "p", "metric_type": "m"})
        with self.assertRaisesRegex(RuntimeError, "set `group_by`"):
            GcpProvider(client=fake).fetch(spec, NOW, NOW)


class FakeProvider:
    def __init__(self, result):
        self.result = result

    def fetch(self, spec, start, end):
        return self.result


def grouped(values, project):
    return make_series(values, provider="gcp", scope=project, resource=project, group=project)


class GroupedPipelineTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state_path = Path(folder.name) / "alerts.json"
        self.posted = []
        self.spec = make_spec(name="errors", provider="gcp")
        self.cfg = Config(SlackConfig("X", 3600, 10), self.state_path, None, [self.spec])
        self.pool = ProviderPool({"gcp": FakeProvider([grouped(QUIET_72, "proj-a"), grouped(SPIKE_72, "proj-b")])})

    def test_each_group_is_detected_on_its_own(self):
        outcomes = pipeline.scan(self.cfg, self.pool, NOW)
        self.assertEqual([(o.series.group, bool(o.anomaly)) for o in outcomes],
                         [("proj-a", False), ("proj-b", True)])

    def test_only_the_spiking_project_alerts_and_is_named(self):
        state = StateStore(self.state_path, 3600)
        result = pipeline.run(self.cfg, self.pool, [], state, self.posted.append, NOW)
        self.assertEqual((result.fetched, result.anomalies, result.posted), (2, 1, 1))
        payload = self.posted[0]
        self.assertIn("errors [proj-b]", payload["text"])
        self.assertIn("Scope: proj-b", json.dumps(payload))

    def test_each_group_has_its_own_fingerprint_and_cooldown(self):
        fingerprints = {o.anomaly.fingerprint for o in pipeline.scan(self.cfg, self.pool, NOW) if o.anomaly}
        self.assertEqual(fingerprints, {"gcp|proj-b|proj-b|CPUUtilization|spike"})
        for _ in range(2):
            state = StateStore(self.state_path, 3600)
            state.load()
            pipeline.run(self.cfg, self.pool, [], state, self.posted.append, NOW)
        self.assertEqual(len(self.posted), 1)  # the second run is inside proj-b's cooldown

    def test_digest_lists_each_group(self):
        routine.run_digest(self.cfg, self.pool, self.posted.append, NOW)
        text = json.dumps(self.posted[0])
        self.assertIn("*errors [proj-b]*", text)
        self.assertIn("*errors [proj-a]*", text)


class GroupByConfigTests(unittest.TestCase):
    YAML = """
metrics:
  - name: errors
    provider: gcp
    project: slack-anomaly-dev
    metric_type: logging.googleapis.com/log_entry_count
    group_by: %s
"""

    def load(self, value):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "config.yaml"
        path.write_text(self.YAML % value)
        return config.load(path)

    def test_list_is_accepted(self):
        cfg = self.load("[resource.labels.project_id]")
        self.assertEqual(cfg.metrics[0].selector["group_by"], GROUP)

    def test_bad_values_are_rejected(self):
        for bad in ("resource.labels.project_id", "[]", "[1]", '[""]'):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError) as ctx:
                self.load(bad)
            self.assertIn("group_by must be a list", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
