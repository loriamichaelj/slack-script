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


class FakeAws:
    """Secrets Manager and Systems Manager clients, each holding a few values."""

    def __init__(self, secrets=None, parameters=None, fail=False):
        self.secrets, self.parameters, self.fail, self.started, self.calls = secrets or {}, parameters or {}, fail, [], []

    def __call__(self, service):
        self.started.append(service)
        return {"secretsmanager": self.SecretsManager, "ssm": self.Ssm}[service](self)

    class SecretsManager:
        def __init__(self, outer):
            self.outer = outer

        def get_secret_value(self, SecretId):
            self.outer.calls.append(("secret", SecretId))
            if self.outer.fail:
                raise KeyError("https://hooks.slack.com/services/LEAK")
            return {"SecretString": self.outer.secrets[SecretId]}

    class Ssm:
        def __init__(self, outer):
            self.outer = outer

        def get_parameter(self, Name, WithDecryption):
            assert WithDecryption  # a SecureString comes back as ciphertext otherwise
            self.outer.calls.append(("ssm", Name))
            if self.outer.fail:
                raise KeyError("https://hooks.slack.com/services/LEAK")
            return {"Parameter": {"Value": self.outer.parameters[Name]}}


class SecretSourceTests(unittest.TestCase):
    def test_an_ssm_parameter_becomes_the_variable(self):
        env = {"SLACK_WEBHOOK_URL_SECRET_ID": "ssm:/anomaly-alerts/slack-webhook"}
        aws = FakeAws(parameters={"/anomaly-alerts/slack-webhook": "https://hooks.example/abc"})
        self.assertEqual(runtime.load_secrets(env, aws), ["SLACK_WEBHOOK_URL"])
        self.assertEqual(env["SLACK_WEBHOOK_URL"], "https://hooks.example/abc")
        self.assertEqual(aws.started, ["ssm"])  # no Secrets Manager client for an SSM value

    def test_a_secrets_manager_id_still_works(self):
        env = {"SLACK_WEBHOOK_URL_SECRET_ID": "slack-webhook"}
        aws = FakeAws(secrets={"slack-webhook": "from-secrets-manager"})
        runtime.load_secrets(env, aws)
        self.assertEqual((env["SLACK_WEBHOOK_URL"], aws.started), ("from-secrets-manager", ["secretsmanager"]))

    def test_both_sources_can_be_mixed_and_each_client_starts_once(self):
        env = {
            "A_SECRET_ID": "ssm:/p/a", "B_SECRET_ID": "ssm:/p/b", "C_SECRET_ID": "plain-secret",
        }
        aws = FakeAws(secrets={"plain-secret": "c"}, parameters={"/p/a": "a", "/p/b": "b"})
        runtime.load_secrets(env, aws)
        self.assertEqual((env["A"], env["B"], env["C"]), ("a", "b", "c"))
        self.assertEqual(sorted(aws.started), ["secretsmanager", "ssm"])

    def test_a_variable_already_set_is_never_looked_up(self):
        env = {"A_SECRET_ID": "ssm:/p/a", "A": "set-by-hand"}
        aws = FakeAws()
        self.assertEqual(runtime.load_secrets(env, aws), [])
        self.assertEqual(aws.started, [])

    def test_an_ssm_error_names_the_variable_and_never_leaks_the_cause(self):
        with self.assertRaises(RuntimeError) as ctx:
            runtime.load_secrets({"SLACK_WEBHOOK_URL_SECRET_ID": "ssm:/p/a"}, FakeAws(fail=True))
        self.assertIn("SLACK_WEBHOOK_URL", str(ctx.exception))
        self.assertNotIn("LEAK", str(ctx.exception))
        self.assertNotIn("hooks.slack.com", str(ctx.exception))

    def test_a_client_that_cannot_start_is_a_clear_error(self):
        def broken(service):
            raise ModuleNotFoundError("boto3")

        with self.assertRaises(RuntimeError) as ctx:
            runtime.load_secrets({"A_SECRET_ID": "ssm:/p/a"}, broken)
        self.assertIn("starting the AWS client", str(ctx.exception))


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
