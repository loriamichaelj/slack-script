import unittest
from unittest import mock

from anomaly_alerts import handler


class HandlerTests(unittest.TestCase):
    def call(self, event, code=0):
        with mock.patch("anomaly_alerts.handler.cli.main", return_value=code) as main:
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


class ConfigStateTests(unittest.TestCase):
    def test_s3_location_is_kept_as_a_string(self):
        from anomaly_alerts.config import _state_location

        self.assertEqual(_state_location("s3://b/k.json"), "s3://b/k.json")
        self.assertEqual(str(_state_location(".state/a.json")), ".state/a.json")
