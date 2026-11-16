"""Azure Functions support: blob names, blob-backed cooldown state and config, and the timer triggers."""

import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from anomaly_alerts import azureblob, handler
from anomaly_alerts.config import _state_location
from anomaly_alerts.state import StateStore
from helpers import NOW

URL = "https://slackanomalydevapp.blob.core.windows.net/app/state/alerts.json"
FUNCTION_APP = Path(__file__).resolve().parent.parent / "serverless" / "azure" / "function_app.py"


class NotFound(Exception):
    """Stands in for azure.core.exceptions.ResourceNotFoundError, matched by name."""


NotFound.__name__ = "ResourceNotFoundError"


class BlobNameTests(unittest.TestCase):
    def test_blob_urls_are_recognised(self):
        self.assertTrue(azureblob.is_blob_url(URL))
        for other in ("s3://b/k", "https://example.com/a/b", "http://x.blob.core.windows.net/a/b", ".state/a.json", None):
            self.assertFalse(azureblob.is_blob_url(other), other)

    def test_url_is_split_into_account_container_and_blob(self):
        self.assertEqual(
            azureblob.parse(URL), ("https://slackanomalydevapp.blob.core.windows.net", "app", "state/alerts.json")
        )

    def test_a_url_without_a_blob_is_rejected(self):
        for bad in ("https://a.blob.core.windows.net/", "https://a.blob.core.windows.net/only-container", "https://x.com/a/b"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                azureblob.parse(bad)

    def test_not_found_is_matched_by_status_or_name(self):
        self.assertTrue(azureblob.is_not_found(NotFound()))
        error = Exception()
        error.status_code = 404
        self.assertTrue(azureblob.is_not_found(error))
        self.assertFalse(azureblob.is_not_found(Exception("boom")))

    def test_state_location_keeps_a_blob_url_as_a_string(self):
        self.assertEqual(_state_location(URL), URL)


class FakeBlob:
    def __init__(self, content=None):
        self.content, self.modified = content, None

    def download_blob(self):
        if self.content is None:
            raise NotFound()
        return types.SimpleNamespace(readall=lambda: self.content)

    def upload_blob(self, data, overwrite=False):
        assert overwrite
        self.content, self.modified = data, NOW

    def get_blob_properties(self):
        if self.content is None:
            raise NotFound()
        return types.SimpleNamespace(last_modified=self.modified)


class BlobStateTests(unittest.TestCase):
    def store(self, blob):
        s = StateStore(URL, 3600)
        s._backend._client = blob
        s.load()
        return s

    def test_round_trip_through_a_blob(self):
        blob = FakeBlob()
        s = self.store(blob)
        self.assertIsNone(s.last_saved())
        s.record("fp", "warning", NOW)
        s.save(NOW)
        again = self.store(blob)
        self.assertFalse(again.allow("fp", "warning", NOW + timedelta(minutes=5)))
        self.assertEqual(again.last_saved(), NOW)

    def test_a_missing_blob_starts_empty(self):
        self.assertTrue(self.store(FakeBlob()).allow("fp", "warning", NOW))

    def test_a_missing_blob_is_normal_and_logs_nothing(self):
        # The first run has no state yet. That is not a warning.
        with self.assertNoLogs("anomaly_alerts.state", level="WARNING"):
            s = self.store(FakeBlob())
            self.assertIsNone(s.last_saved())

    def test_an_unreadable_blob_does_not_stop_alerting(self):
        self.assertTrue(self.store(FakeBlob(b"not json")).allow("fp", "warning", NOW))

    def test_a_bad_blob_url_is_rejected(self):
        with self.assertRaises(ValueError):
            StateStore("https://a.blob.core.windows.net/only-container", 3600)


class BlobConfigTests(unittest.TestCase):
    def test_config_is_downloaded_from_a_blob(self):
        seen = []

        def factory(url):
            seen.append(url)
            return FakeBlob(b"slack: {}\n")

        with tempfile.TemporaryDirectory() as folder:
            destination = str(Path(folder) / "config.yaml")
            path = handler.resolve_config(
                "https://acct.blob.core.windows.net/app/config.yaml", destination=destination, blob_factory=factory
            )
            self.assertEqual(path, destination)
            self.assertEqual(Path(destination).read_bytes(), b"slack: {}\n")
        self.assertEqual(seen, ["https://acct.blob.core.windows.net/app/config.yaml"])

    def test_a_local_path_never_touches_blob_storage(self):
        factory = mock.Mock()
        self.assertEqual(handler.resolve_config("config/config.yaml", blob_factory=factory), "config/config.yaml")
        factory.assert_not_called()


class FakeFunctionApp:
    """Enough of azure.functions.FunctionApp to see what the entry point registers."""

    def __init__(self):
        self.functions = []

    def function_name(self, name):
        def decorate(fn):
            fn.registered_name = name
            return fn

        return decorate

    def timer_trigger(self, **settings):
        def decorate(fn):
            fn.trigger = settings
            self.functions.append(fn)
            return fn

        return decorate


class FunctionAppTests(unittest.TestCase):
    def load(self):
        fake = types.ModuleType("azure.functions")
        fake.FunctionApp = FakeFunctionApp
        fake.TimerRequest = object
        package = types.ModuleType("azure")
        package.functions = fake
        run_event = mock.Mock()
        with mock.patch.dict(sys.modules, {"azure": package, "azure.functions": fake}), \
                mock.patch("anomaly_alerts.handler.run_event", run_event):
            spec = importlib.util.spec_from_file_location("function_app_under_test", FUNCTION_APP)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module, run_event

    def test_one_timer_trigger_per_job(self):
        module, _ = self.load()
        schedules = {fn.registered_name: fn.trigger["schedule"] for fn in module.app.functions}
        self.assertEqual(schedules, {
            "anomaly_run": "0 */5 * * * *",
            "routine_heartbeat": "0 0 */6 * * *",
            "routine_digest": "0 0 14 * * *",
            "routine_cost": "0 30 14 * * *",
        })

    def test_triggers_do_not_run_on_startup_or_use_the_schedule_monitor(self):
        module, _ = self.load()
        for fn in module.app.functions:
            with self.subTest(job=fn.registered_name):
                self.assertFalse(fn.trigger["run_on_startup"])
                self.assertFalse(fn.trigger["use_monitor"])

    def test_each_trigger_runs_its_own_job(self):
        module, run_event = self.load()
        for fn in module.app.functions:
            fn(None)
        self.assertEqual(
            [call.args[0] for call in run_event.call_args_list],
            [
                {"command": "run"},
                {"command": "routine", "kind": "heartbeat"},
                {"command": "routine", "kind": "digest"},
                {"command": "routine", "kind": "cost"},
            ],
        )

    def test_the_schedules_match_the_events(self):
        # Guards against editing one table and forgetting the other.
        module, _ = self.load()
        self.assertEqual(set(module.JOBS), {fn.registered_name for fn in module.app.functions})
