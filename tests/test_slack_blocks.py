import email.message
import json
import unittest
import urllib.error

from anomaly_alerts.models import Anomaly, Detection
from anomaly_alerts.slack import blocks
from anomaly_alerts.slack.client import SlackError, post
from helpers import NOW, make_series, make_spec


def make_anomaly(severity="critical", runbook="https://wiki.example.com/rb", name="alb-5xx", console=True):
    detection = Detection("spike", severity, 41.2, 412.0, 6.0, 1.0, 3)
    series = make_series([1, 2, 3, 9], metric="HTTPCode_Target_5XX_Count")
    if not console:
        series.console_url = None
    return Anomaly(
        spec=make_spec(name=name, runbook=runbook),
        series=series,
        detection=detection,
        window_start=NOW,
        window_end=NOW,
        recent=[1.0, 2.0, 3.0, 9.0],
    )


class BlockTests(unittest.TestCase):
    def texts(self, payload):
        out = []
        for block in payload["attachments"][0]["blocks"]:
            if "text" in block:
                out.append(block["text"]["text"])
            for element in block.get("elements", []):
                out.append(element.get("text", ""))
                if isinstance(out[-1], dict):
                    out[-1] = out[-1]["text"]
        return "\n".join(out)

    def test_payload_has_fallback_text_colour_and_content(self):
        payload = blocks.build_payload(make_anomaly(), ["Check deploys", "Check logs"])
        self.assertIn("[CRITICAL]", payload["text"])
        self.assertEqual(payload["attachments"][0]["color"], blocks.COLORS["critical"])
        text = self.texts(payload)
        self.assertIn("*[CRITICAL]* AWS | alb-5xx | HTTPCode_Target_5XX_Count", text)
        self.assertIn("Observed *412*", text)
        self.assertIn("baseline median *6*", text)
        self.assertIn("modified z = +41.2", text)
        self.assertIn("1. Check deploys", text)
        self.assertIn("2. Check logs", text)

    def test_warning_uses_its_own_colour(self):
        payload = blocks.build_payload(make_anomaly("warning"), ["x"])
        self.assertEqual(payload["attachments"][0]["color"], blocks.COLORS["warning"])

    def test_buttons_for_console_and_runbook(self):
        payload = blocks.build_payload(make_anomaly(), ["x"])
        actions = payload["attachments"][0]["blocks"][-1]
        self.assertEqual(actions["type"], "actions")
        self.assertEqual([b["url"] for b in actions["elements"]],
                         ["https://console.example.com/metric", "https://wiki.example.com/rb"])

    def test_no_buttons_when_there_are_no_links(self):
        payload = blocks.build_payload(make_anomaly(runbook=None, console=False), ["x"])
        self.assertNotEqual(payload["attachments"][0]["blocks"][-1]["type"], "actions")

    def test_user_text_is_escaped(self):
        payload = blocks.build_payload(make_anomaly(name="a<b>&c"), ["use <b>bold</b>"])
        text = self.texts(payload)
        self.assertIn("a&lt;b&gt;&amp;c", text)
        self.assertIn("use &lt;b&gt;bold&lt;/b&gt;", text)

    def test_blocks_stay_within_slack_limits(self):
        payload = blocks.build_payload(make_anomaly(), ["x"] * 5)
        self.assertLessEqual(len(payload["attachments"][0]["blocks"]), 50)
        for block in payload["attachments"][0]["blocks"]:
            if block["type"] == "section":
                self.assertLessEqual(len(block["text"]["text"]), 3000)

    def test_sparkline(self):
        self.assertEqual(blocks.sparkline([1, 1, 1]), "▁▁▁")
        line = blocks.sparkline([0, 1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual((line[0], line[-1]), ("▁", "█"))
        self.assertEqual(blocks.sparkline([]), "")

    def test_number_formatting(self):
        cases = {0: "0", 6.0: "6", 6.5: "6.5", 12.345: "12.35", 0.00123: "0.00123", 1234567.0: "1,234,567"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(blocks.fmt(value), expected)

    def test_overflow_notice(self):
        self.assertIn("3 more anomalies suppressed", blocks.build_overflow_payload(3, 10)["text"])
        self.assertIn("1 more anomaly suppressed", blocks.build_overflow_payload(1, 10)["text"])


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"ok"


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://hooks.example/secret", code, "err", headers, None)


class ClientTests(unittest.TestCase):
    def opener(self, *outcomes):
        calls = []

        def fake(request, timeout):
            calls.append((request, timeout))
            outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        fake.calls = calls
        return fake

    def test_success_posts_json(self):
        opener = self.opener(FakeResponse())
        post("https://hooks.example/x", {"text": "hi"}, opener=opener, sleep=lambda s: None)
        request, timeout = opener.calls[0]
        self.assertEqual(json.loads(request.data), {"text": "hi"})
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(timeout, 10.0)

    def test_429_waits_for_retry_after_then_succeeds(self):
        opener = self.opener(http_error(429, retry_after=7), FakeResponse())
        waits = []
        post("https://hooks.example/x", {}, opener=opener, sleep=waits.append)
        self.assertEqual(waits, [7.0])
        self.assertEqual(len(opener.calls), 2)

    def test_retry_after_is_capped(self):
        opener = self.opener(http_error(429, retry_after=9999), FakeResponse())
        waits = []
        post("https://hooks.example/x", {}, opener=opener, sleep=waits.append)
        self.assertEqual(waits, [30.0])

    def test_client_errors_are_not_retried(self):
        opener = self.opener(http_error(404))
        with self.assertRaises(SlackError):
            post("https://hooks.example/x", {}, opener=opener, sleep=lambda s: None)
        self.assertEqual(len(opener.calls), 1)

    def test_gives_up_after_retries_without_leaking_the_url(self):
        opener = self.opener(http_error(503))
        with self.assertRaises(SlackError) as ctx:
            post("https://hooks.example/secret-token", {}, retries=2, opener=opener, sleep=lambda s: None)
        self.assertEqual(len(opener.calls), 3)
        self.assertNotIn("secret", str(ctx.exception))

    def test_network_errors_are_retried(self):
        opener = self.opener(urllib.error.URLError("timed out"), FakeResponse())
        post("https://hooks.example/x", {}, opener=opener, sleep=lambda s: None)
        self.assertEqual(len(opener.calls), 2)


if __name__ == "__main__":
    unittest.main()
