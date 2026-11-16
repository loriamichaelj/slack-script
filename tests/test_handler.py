import unittest
from unittest import mock

from anomaly_alerts import handler


class FakeSecrets:
    def __init__(self, values, fail=False):
        self.values, self.fail, self.calls = values, fail, []

    def get_secret_value(self, SecretId):
        self.calls.append(SecretId)
        if self.fail:
            raise KeyError("https://hooks.slack.com/services/SECRET")  # must never reach the message
        return {"SecretString": self.values[SecretId]}


class FakeS3:
    def __init__(self):
        self.downloads = []

    def download_file(self, bucket, key, destination):
        self.downloads.append((bucket, key, destination))


class HandlerTests(unittest.TestCase):
    def call(self, event, code=0, env=None):
        with mock.patch("anomaly_alerts.handler.cli.main", return_value=code) as main, \
                mock.patch.dict("os.environ", env or {}, clear=True):
            result = handler.lambda_handler(event, None)
        return main.call_args.args[0], result

    def test_default_is_an_alert_run(self):
        argv, _ = self.call({})
        self.assertEqual(argv[:2], ["run", "--config"])

    def test_routine_kind_is_passed(self):
        argv, _ = self.call({"command": "routine", "kind": "cost", "dry_run": True})
        self.assertEqual(argv[0], "routine")
        self.assertIn("cost", argv)
        self.assertIn("--dry-run", argv)

    def test_failure_raises_so_lambda_records_it(self):
        with self.assertRaises(RuntimeError):
            self.call({}, code=1)

    def test_config_path_comes_from_the_environment(self):
        argv, _ = self.call({}, env={"ANOMALY_CONFIG": "/var/task/config.yaml"})
        self.assertEqual(argv[2], "/var/task/config.yaml")


class LoggingTests(unittest.TestCase):
    def setUp(self):
        import logging

        root = logging.getLogger()
        self.addCleanup(root.setLevel, root.level)
        root.setLevel(logging.WARNING)  # what Lambda starts with

    def level(self):
        import logging

        return logging.getLogger().level

    def test_info_by_default(self):
        import logging

        handler.configure_logging({})
        self.assertEqual(self.level(), logging.INFO)

    def test_level_comes_from_the_environment(self):
        import logging

        handler.configure_logging({"LOG_LEVEL": "debug"})
        self.assertEqual(self.level(), logging.DEBUG)

    def test_unknown_level_falls_back_to_info(self):
        import logging

        handler.configure_logging({"LOG_LEVEL": "loud"})
        self.assertEqual(self.level(), logging.INFO)


class SecretTests(unittest.TestCase):
    def test_secret_ids_become_variables(self):
        env = {"SLACK_WEBHOOK_URL_SECRET_ID": "slack-webhook", "OTHER": "x"}
        client = FakeSecrets({"slack-webhook": "https://hooks.example/abc"})
        names = handler.load_secrets(env, lambda service: client)
        self.assertEqual(names, ["SLACK_WEBHOOK_URL"])
        self.assertEqual(env["SLACK_WEBHOOK_URL"], "https://hooks.example/abc")

    def test_variable_already_set_is_left_alone_and_no_call_is_made(self):
        env = {"SLACK_WEBHOOK_URL_SECRET_ID": "slack-webhook", "SLACK_WEBHOOK_URL": "set-by-hand"}
        factory = mock.Mock()
        self.assertEqual(handler.load_secrets(env, factory), [])
        factory.assert_not_called()
        self.assertEqual(env["SLACK_WEBHOOK_URL"], "set-by-hand")

    def test_no_secret_ids_means_no_client(self):
        factory = mock.Mock()
        self.assertEqual(handler.load_secrets({"PATH": "/bin"}, factory), [])
        factory.assert_not_called()

    def test_error_names_the_variable_but_never_leaks_the_cause(self):
        env = {"SLACK_WEBHOOK_URL_SECRET_ID": "slack-webhook"}
        with self.assertRaises(RuntimeError) as ctx:
            handler.load_secrets(env, lambda service: FakeSecrets({}, fail=True))
        self.assertIn("SLACK_WEBHOOK_URL", str(ctx.exception))
        self.assertNotIn("hooks.slack.com", str(ctx.exception))


class ConfigTests(unittest.TestCase):
    def test_local_path_is_untouched(self):
        factory = mock.Mock()
        self.assertEqual(handler.resolve_config("config/config.yaml", factory), "config/config.yaml")
        factory.assert_not_called()

    def test_s3_config_is_downloaded(self):
        s3 = FakeS3()
        path = handler.resolve_config("s3://bkt/conf/config.yaml", lambda service: s3, "/tmp/x.yaml")
        self.assertEqual(path, "/tmp/x.yaml")
        self.assertEqual(s3.downloads, [("bkt", "conf/config.yaml", "/tmp/x.yaml")])

    def test_bad_s3_uri_is_rejected(self):
        with self.assertRaises(ValueError):
            handler.resolve_config("s3://only-bucket", lambda service: FakeS3())


class ConfigStateTests(unittest.TestCase):
    def test_s3_location_is_kept_as_a_string(self):
        from anomaly_alerts.config import _state_location

        self.assertEqual(_state_location("s3://b/k.json"), "s3://b/k.json")
        self.assertEqual(str(_state_location(".state/a.json")), ".state/a.json")
