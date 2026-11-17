"""The external dead-man's-switch ping: optional, never fatal, and never leaks its URL."""

import contextlib
import io
import os
import unittest
from unittest import mock

from anomaly_alerts import cli, watchdog

URL = "https://hc-ping.com/11111111-2222-3333-4444-555555555555"


class FakeOpener:
    def __init__(self, error=None):
        self.requests, self.error = [], error

    def __call__(self, request, timeout):
        self.requests.append((request.full_url, request.get_method(), timeout))
        if self.error:
            raise self.error
        return mock.Mock()


class PingTests(unittest.TestCase):
    def test_nothing_is_sent_without_a_url(self):
        opener = FakeOpener()
        self.assertFalse(watchdog.ping(True, {}, opener))
        self.assertFalse(watchdog.ping(True, {"HEALTHCHECK_URL": "  "}, opener))
        self.assertEqual(opener.requests, [])

    def test_a_good_run_pings_the_url_with_a_short_timeout(self):
        opener = FakeOpener()
        self.assertTrue(watchdog.ping(True, {"HEALTHCHECK_URL": URL}, opener))
        self.assertEqual(opener.requests, [(URL, "GET", 5)])

    def test_a_failed_run_pings_the_fail_address(self):
        opener = FakeOpener()
        watchdog.ping(False, {"HEALTHCHECK_URL": URL + "/"}, opener)
        self.assertEqual(opener.requests[0][0], URL + "/fail")

    def test_only_https_is_pinged(self):
        opener = FakeOpener()
        self.assertFalse(watchdog.ping(True, {"HEALTHCHECK_URL": "http://hc-ping.com/x"}, opener))
        self.assertEqual(opener.requests, [])

    def test_a_ping_error_is_swallowed_and_never_logs_the_url(self):
        opener = FakeOpener(error=OSError("could not reach " + URL))
        with self.assertLogs("anomaly_alerts.watchdog", level="WARNING") as logs:
            self.assertFalse(watchdog.ping(True, {"HEALTHCHECK_URL": URL}, opener))
        text = "\n".join(logs.output)
        self.assertIn("OSError", text)
        self.assertNotIn("hc-ping.com", text)
        self.assertNotIn("11111111", text)


class CliPingTests(unittest.TestCase):
    CONFIG = "slack:\n  webhook_env: SLACK_WEBHOOK_URL\nmetrics:\n  - {name: m, provider: aws, region: us-east-1, namespace: N, metric: M}\n"

    def run_cli(self, ok, *extra, env=None):
        import base64

        env = {"ANOMALY_CONFIG_B64": base64.b64encode(self.CONFIG.encode()).decode(), "SLACK_WEBHOOK_URL": "x", **(env or {})}
        result = mock.Mock(ok=ok, fetched=1, anomalies=0, posted=0, in_cooldown=0, over_limit=0, fetch_errors=0 if ok else 1, post_errors=0)
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("anomaly_alerts.cli.pipeline.run", return_value=result), \
                mock.patch("anomaly_alerts.cli.ProviderPool"), mock.patch("anomaly_alerts.cli.StateStore"), \
                mock.patch("anomaly_alerts.cli.watchdog.ping") as ping, \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--config", "inline", *extra])
        return code, ping

    def test_a_finished_run_pings_with_its_outcome(self):
        code, ping = self.run_cli(True)
        self.assertEqual((code, ping.call_args.args), (0, (True,)))
        code, ping = self.run_cli(False)
        self.assertEqual((code, ping.call_args.args), (1, (False,)))

    def test_a_dry_run_never_pings(self):
        _, ping = self.run_cli(True, "--dry-run")
        ping.assert_not_called()


if __name__ == "__main__":
    unittest.main()
