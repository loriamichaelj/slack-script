import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anomaly_alerts import cli, config, routine
from anomaly_alerts.config import Config, SlackConfig
from anomaly_alerts.providers import ProviderPool
from anomaly_alerts.slack import blocks
from anomaly_alerts.slack.client import SlackError
from helpers import BASE, NOW, make_series, make_spec

QUIET_72 = (BASE + [12] * 12)[:72]
SPIKE_72 = (BASE + [12] * 12)[:69] + [60, 60, 60]


class FakeProvider:
    def __init__(self, by_name):
        self.by_name = by_name

    def fetch(self, spec, start, end):
        result = self.by_name[spec.name]
        if isinstance(result, Exception):
            raise result
        return result


def make_config(specs, **slack):
    return Config(SlackConfig("X", 3600, 10, **slack), Path("unused.json"), None, specs)


def all_text(payload):
    return json.dumps(payload)


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.posted = []

    def heartbeat(self, by_name, specs, post=None, **kwargs):
        return routine.run_heartbeat(
            make_config(specs),
            ProviderPool({"aws": FakeProvider(by_name)}),
            post or self.posted.append,
            NOW,
            **kwargs,
        )

    def test_healthy_run_posts_ok(self):
        result = self.heartbeat({"cpu": make_series(QUIET_72)}, [make_spec()])
        self.assertEqual((result.checked, result.total, result.anomalies, result.fetch_errors), (1, 1, 0, 0))
        self.assertTrue(result.ok)
        payload = self.posted[0]
        self.assertIn("Heartbeat OK: 1/1 metrics checked, 0 anomalies, 0 fetch errors", payload["text"])
        self.assertEqual(payload["attachments"][0]["color"], blocks.COLORS["ok"])

    def test_counts_current_anomalies(self):
        specs = [make_spec(name="cpu"), make_spec(name="mem")]
        data = {"cpu": make_series(SPIKE_72), "mem": make_series(QUIET_72)}
        result = self.heartbeat(data, specs)
        self.assertEqual((result.checked, result.anomalies), (2, 1))
        self.assertIn("1 anomaly", self.posted[0]["text"])

    def test_fetch_error_marks_degraded_without_leaking_error_text(self):
        specs = [make_spec(name="cpu"), make_spec(name="mem")]
        data = {
            "cpu": make_series(QUIET_72),
            "mem": RuntimeError("AccessDenied for arn:aws:iam::123456789012:role/secret-name"),
        }
        result = self.heartbeat(data, specs)
        self.assertEqual((result.checked, result.total, result.fetch_errors), (1, 2, 1))
        self.assertTrue(result.ok)  # a fetch error is reported, not a failed run
        payload = self.posted[0]
        self.assertIn("Heartbeat DEGRADED", payload["text"])
        self.assertEqual(payload["attachments"][0]["color"], blocks.COLORS["warning"])
        text = all_text(payload)
        self.assertIn("mem", text)
        self.assertNotIn("AccessDenied", text)
        self.assertNotIn("123456789012", text)

    def test_failed_post_fails_the_run(self):
        def boom(payload):
            raise SlackError("Slack returned HTTP 500")

        result = self.heartbeat({"cpu": make_series(QUIET_72)}, [make_spec()], post=boom)
        self.assertFalse(result.ok)
        self.assertEqual((result.posted, result.post_errors), (0, 1))

    def test_only_limits_to_one_cloud(self):
        specs = [make_spec(name="cpu"), make_spec(name="vm", provider="azure")]
        result = self.heartbeat({"cpu": make_series(QUIET_72)}, specs, only="aws")
        self.assertEqual(result.total, 1)

    def test_long_failure_list_is_truncated(self):
        payload = blocks.build_heartbeat_payload(
            NOW, checked=0, total=15, anomalies=0, failed=[f"m{i}" for i in range(15)]
        )
        text = all_text(payload)
        self.assertIn("and 5 more", text)
        self.assertNotIn("m14", text)

    def test_metric_names_are_escaped(self):
        payload = blocks.build_heartbeat_payload(
            NOW, checked=0, total=1, anomalies=0, failed=["a<b>&c"]
        )
        self.assertIn("a&lt;b&gt;&amp;c", all_text(payload))

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            routine.run("digest")


class RoutineConfigTests(unittest.TestCase):
    BASE_YAML = """
slack: {%s}
metrics:
  - name: cpu
    provider: aws
    region: us-east-1
    namespace: AWS/EC2
    metric: CPUUtilization
"""

    def load(self, slack_inline):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "config.yaml"
        path.write_text(self.BASE_YAML % slack_inline)
        return config.load(path)

    def test_routine_webhook_is_optional(self):
        self.assertIsNone(self.load("cooldown_minutes: 30").slack.routine_webhook_env)

    def test_routine_webhook_env_is_read(self):
        cfg = self.load("routine_webhook_env: SLACK_ROUTINE_WEBHOOK_URL")
        self.assertEqual(cfg.slack.routine_webhook_env, "SLACK_ROUTINE_WEBHOOK_URL")

    def test_blank_routine_webhook_env_is_rejected(self):
        with self.assertRaises(config.ConfigError) as ctx:
            self.load('routine_webhook_env: ""')
        self.assertIn("routine_webhook_env", str(ctx.exception))


class WebhookChoiceTests(unittest.TestCase):
    def cfg(self, routine_env):
        return make_config([make_spec()], routine_webhook_env=routine_env)

    def test_anomaly_run_always_uses_main_webhook(self):
        with mock.patch.dict(os.environ, {"R": "https://routine.example"}):
            self.assertEqual(cli._webhook_env(self.cfg("R"), False), "X")

    def test_routine_uses_its_own_webhook_when_set(self):
        with mock.patch.dict(os.environ, {"R": "https://routine.example"}):
            self.assertEqual(cli._webhook_env(self.cfg("R"), True), "R")

    def test_routine_falls_back_when_its_variable_is_empty(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cli._webhook_env(self.cfg("R"), True), "X")

    def test_routine_without_its_own_webhook_uses_main(self):
        self.assertEqual(cli._webhook_env(self.cfg(None), True), "X")


class RoutineCliTests(unittest.TestCase):
    YAML = """
metrics:
  - name: cpu
    provider: aws
    region: us-east-1
    namespace: AWS/EC2
    metric: CPUUtilization
"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "config.yaml"
        self.path.write_text(self.YAML)

    def run_cli(self, *argv):
        out = io.StringIO()
        pool = ProviderPool({"aws": FakeProvider({"cpu": make_series(QUIET_72)})})
        with mock.patch.object(cli, "ProviderPool", return_value=pool), \
                mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_routine_dry_run_prints_the_heartbeat(self):
        code, out = self.run_cli("routine", "--config", str(self.path), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Heartbeat OK", json.loads(out)["text"])

    def test_routine_without_a_webhook_is_a_setup_error(self):
        code, _ = self.run_cli("routine", "--config", str(self.path))
        self.assertEqual(code, 2)

    def test_bare_invocation_still_runs_anomaly_detection(self):
        code, out = self.run_cli("--config", str(self.path), "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")  # a quiet metric posts nothing

    def test_unknown_kind_is_rejected_by_the_parser(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["routine", "--config", str(self.path), "--kind", "nope"])


if __name__ == "__main__":
    unittest.main()
