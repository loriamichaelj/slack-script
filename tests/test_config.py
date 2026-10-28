import tempfile
import unittest
from pathlib import Path

from anomaly_alerts import config

VALID = """
slack: {cooldown_minutes: 30, max_alerts_per_run: 5}
defaults: {lookback: 24h, period: 5m, detector: mad}
metrics:
  - name: cpu
    provider: aws
    region: us-east-1
    namespace: AWS/EC2
    metric: CPUUtilization
    direction: spike
    min_abs_change: 10
"""


class ConfigTests(unittest.TestCase):
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

    def test_valid_config(self):
        cfg = self.load(VALID)
        self.assertEqual(cfg.slack.cooldown_seconds, 1800)
        self.assertEqual(cfg.slack.max_alerts_per_run, 5)
        spec = cfg.metrics[0]
        self.assertEqual((spec.lookback_seconds, spec.period_seconds), (86400, 300))
        self.assertEqual(spec.selector, {"region": "us-east-1", "namespace": "AWS/EC2", "metric": "CPUUtilization"})
        self.assertEqual(spec.min_abs_change, 10.0)
        self.assertIsNone(cfg.actions_path)

    def test_each_detector_gets_its_own_default_threshold(self):
        for detector, expected in (("mad", 3.5), ("zscore", 3.0), ("ewma", 3.0), ("iqr", 1.5)):
            with self.subTest(detector=detector):
                cfg = self.load(VALID.replace("detector: mad", f"detector: {detector}"))
                self.assertEqual(cfg.metrics[0].threshold, expected)

    def test_metric_overrides_defaults(self):
        cfg = self.load(VALID + "    detector: iqr\n    threshold: 2\n")
        self.assertEqual((cfg.metrics[0].detector, cfg.metrics[0].threshold), ("iqr", 2.0))

    def test_actions_file_is_relative_to_the_config(self):
        cfg = self.load(VALID + "actions_file: actions.yaml\n")
        self.assertEqual(cfg.actions_path.name, "actions.yaml")

    def test_durations(self):
        self.assertEqual(config.parse_duration("90s", "x"), 90)
        self.assertEqual(config.parse_duration("2h", "x"), 7200)
        self.assertEqual(config.parse_duration("7d", "x"), 604800)
        for bad in ("5", "m5", "0m", "5 weeks", ""):
            with self.subTest(value=bad), self.assertRaises(config.ConfigError):
                config.parse_duration(bad, "x")

    def test_rejections_are_specific(self):
        self.assertRejects("metrics: []\n", "at least one metric")
        self.assertRejects("bogus: 1\nmetrics: []\n", "unknown top-level")
        self.assertRejects(VALID.replace("provider: aws", "provider: oracle"), "provider must be one of")
        self.assertRejects(VALID.replace("    region: us-east-1\n", ""), "missing required key(s) ['region']")
        self.assertRejects(VALID + "    nmespace: typo\n", "unknown key(s) ['nmespace']")
        self.assertRejects(VALID.replace("direction: spike", "direction: up"), "direction must be one of")
        self.assertRejects(VALID.replace("detector: mad", "detector: magic"), "detector must be one of")
        self.assertRejects(VALID + "    runbook: not-a-url\n", "runbook must be an http(s) URL")
        self.assertRejects(VALID + "    sustained_points: 0\n", "sustained_points must be at least 1")
        self.assertRejects(VALID.replace("lookback: 24h", "lookback: 1h"), "gives 12 points")
        self.assertRejects(VALID + "  - name: cpu\n    provider: gcp\n    project: p\n    metric_type: m\n",
                           "duplicate name")
        self.assertRejects(VALID.replace("slack: {", "slack: {webhook: x, "), "slack: unknown key")
        self.assertRejects(VALID.replace("defaults: {", "defaults: {color: red, "), "defaults: unknown key")

    def test_the_shipped_example_config_is_valid(self):
        cfg = config.load(Path(__file__).resolve().parent.parent / "config" / "config.example.yaml")
        self.assertEqual({m.provider for m in cfg.metrics}, {"aws", "azure", "gcp"})

    def test_missing_file(self):
        with self.assertRaises(config.ConfigError):
            config.load("/nonexistent/config.yaml")


if __name__ == "__main__":
    unittest.main()
