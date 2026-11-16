"""The start-up steps every container host shares: config by URL or inline, and the CLI using them."""

import base64
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anomaly_alerts import cli, runtime

CONFIG = """\
slack:
  webhook_env: SLACK_WEBHOOK_URL
metrics:
  - name: cpu
    provider: aws
    region: us-east-1
    namespace: AWS/EC2
    metric: CPUUtilization
"""


def encoded(text=CONFIG):
    return base64.b64encode(text.encode()).decode()


class InlineConfigTests(unittest.TestCase):
    def test_config_is_written_from_the_environment_variable(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = str(Path(folder) / "config.yaml")
            self.assertEqual(runtime.inline_config({"ANOMALY_CONFIG_B64": encoded("a: 1\n")}, destination), destination)
            self.assertEqual(Path(destination).read_text(), "a: 1\n")

    def test_missing_variable_is_a_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            runtime.inline_config({})
        self.assertIn("ANOMALY_CONFIG_B64", str(ctx.exception))

    def test_bad_base64_is_a_clear_error_that_does_not_echo_the_value(self):
        with self.assertRaises(ValueError) as ctx:
            runtime.inline_config({"ANOMALY_CONFIG_B64": "not base64!!"})
        self.assertNotIn("not base64!!", str(ctx.exception))

    def test_resolve_config_treats_the_word_inline_as_that_variable(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = str(Path(folder) / "c.yaml")
            path = runtime.resolve_config("inline", destination=destination, environ={"ANOMALY_CONFIG_B64": encoded("b: 2\n")})
            self.assertEqual((path, Path(destination).read_text()), (destination, "b: 2\n"))

    def test_a_plain_path_is_used_as_it_is(self):
        self.assertEqual(runtime.resolve_config("config/config.yaml", client_factory=mock.Mock()), "config/config.yaml")


class CliUsesRuntimeTests(unittest.TestCase):
    def run_cli(self, env, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--config", "inline", "--dry-run", *args])
        return code, out.getvalue(), err.getvalue()

    def test_an_inline_config_reaches_the_config_loader(self):
        with mock.patch("anomaly_alerts.cli.pipeline.run") as run, \
                mock.patch("anomaly_alerts.cli.ProviderPool"), \
                mock.patch("anomaly_alerts.cli.StateStore"):
            run.return_value = mock.Mock(
                ok=True, fetched=1, anomalies=0, posted=0, in_cooldown=0, over_limit=0, fetch_errors=0, post_errors=0
            )
            code, _, _ = self.run_cli({"ANOMALY_CONFIG_B64": encoded()})
        self.assertEqual(code, 0)
        self.assertEqual([m.name for m in run.call_args.args[0].metrics], ["cpu"])

    def test_inline_without_the_variable_is_a_config_error_not_a_crash(self):
        code, _, err = self.run_cli({})
        self.assertEqual(code, 2)
        self.assertIn("ANOMALY_CONFIG_B64", err)

    def test_a_secret_that_cannot_be_read_is_a_config_error_naming_only_the_variable(self):
        env = {"ANOMALY_CONFIG_B64": encoded(), "SLACK_WEBHOOK_URL_SECRET_ID": "slack-webhook"}
        with mock.patch("anomaly_alerts.runtime._boto3_client", side_effect=RuntimeError("no boto3")):
            code, _, err = self.run_cli(env)
        self.assertEqual(code, 2)
        self.assertNotIn("hooks.slack.com", err)


if __name__ == "__main__":
    unittest.main()
