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
        out = [b["text"]["text"] for b in payload.get("blocks", [])]
        for block in payload["attachments"][0]["blocks"]:
            if "text" in block:
                out.append(block["text"]["text"])
            out += [f["text"] for f in block.get("fields", [])]
            for element in block.get("elements", []):
                text = element.get("text", "")
                out.append(text["text"] if isinstance(text, dict) else text)
        return "\n".join(out)

    def test_header_says_how_bad_and_what(self):
        payload = blocks.build_payload(make_anomaly(), ["x"])
        header = payload["blocks"][0]
        self.assertEqual(header["type"], "header")
        self.assertEqual(header["text"]["text"], ":red_circle: CRITICAL · alb-5xx")
        self.assertEqual(payload["attachments"][0]["color"], blocks.COLORS["critical"])
        self.assertIn("[CRITICAL]", payload["text"])

    def test_numbers_are_a_grid_in_plain_words(self):
        text = self.texts(blocks.build_payload(make_anomaly(), ["Check deploys", "Check logs"]))
        self.assertIn("AWS · HTTPCode_Target_5XX_Count · prod-api · us-east-1", text)
        self.assertIn("*Now*\n↑ 412", text)
        self.assertIn("*Usual (median)*\n6", text)
        self.assertIn("*Change*\n69× usual", text)
        self.assertIn("*Lasting*\n15 min (3 periods)", text)
        self.assertIn("*Started*\n<!date^", text)
        self.assertIn("*What to check*\n1. Check deploys\n2. Check logs", text)
        self.assertIn("modified z +41.2, threshold 3.5", text)  # the statistics stay, in small print

    def test_change_reads_as_a_multiple_or_a_percentage(self):
        self.assertEqual(blocks.change_text(412, 6, "spike", False), "69× usual")
        self.assertEqual(blocks.change_text(15, 6, "spike", False), "2.5× usual")
        self.assertEqual(blocks.change_text(9, 6, "spike", False), "+50% vs usual")
        self.assertEqual(blocks.change_text(2, 10, "drop", False), "-80% vs usual")
        self.assertEqual(blocks.change_text(3, 0, "spike", False), "+3 from 0")
        self.assertEqual(blocks.change_text(0.2, 0.5, "drop", True), "0.3 below the limit")

    def test_times_show_in_the_readers_time_zone(self):
        self.assertEqual(blocks.when(NOW), "<!date^1793188800^{date_short_pretty} at {time}|2026-10-28 12:00 UTC>")
        self.assertEqual([blocks.duration(s) for s in (300, 3600, 5400)], ["5 min", "1 h", "1 h 30 min"])

    def test_warning_uses_its_own_colour_and_icon(self):
        payload = blocks.build_payload(make_anomaly("warning"), ["x"])
        self.assertEqual(payload["attachments"][0]["color"], blocks.COLORS["warning"])
        self.assertTrue(payload["blocks"][0]["text"]["text"].startswith(":large_orange_circle: WARNING"))

    def test_buttons_for_console_and_runbook(self):
        payload = blocks.build_payload(make_anomaly(), ["x"])
        actions = [b for b in payload["attachments"][0]["blocks"] if b["type"] == "actions"][0]
        self.assertEqual([b["url"] for b in actions["elements"]],
                         ["https://console.example.com/metric", "https://wiki.example.com/rb"])

    def test_no_buttons_when_there_are_no_links(self):
        payload = blocks.build_payload(make_anomaly(runbook=None, console=False), ["x"])
        self.assertNotIn("actions", [b["type"] for b in payload["attachments"][0]["blocks"]])

    def test_user_text_is_escaped(self):
        payload = blocks.build_payload(make_anomaly(name="a<b>&c"), ["use <b>bold</b>"])
        text = self.texts(payload)
        self.assertIn("use &lt;b&gt;bold&lt;/b&gt;", text)
        self.assertIn("a<b>&c", payload["blocks"][0]["text"]["text"])  # plain text needs no escaping

    def test_blocks_stay_within_slack_limits(self):
        payload = blocks.build_payload(make_anomaly(name="n" * 300), ["x"] * 5)
        self.assertLessEqual(len(payload["blocks"][0]["text"]["text"]), 150)
        self.assertLessEqual(len(payload["attachments"][0]["blocks"]), 50)
        for block in payload["attachments"][0]["blocks"]:
            if block["type"] == "section":
                self.assertLessEqual(len(block.get("fields", [])), 10)
                for text in [block.get("text", {}).get("text", "")] + [f["text"] for f in block.get("fields", [])]:
                    self.assertLessEqual(len(text), 2000)

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


class ThreadMessageTests(unittest.TestCase):
    def test_resolved_message_keeps_the_alert_and_turns_green(self):
        from datetime import timedelta
        from anomaly_alerts.slack import threads
        posted = blocks.build_payload(make_anomaly(), ["x"])
        resolved = threads.resolved_payload(posted, NOW, NOW + timedelta(minutes=95))
        self.assertEqual(resolved["blocks"][0]["text"]["text"], ":white_check_mark: RESOLVED · alb-5xx")
        self.assertEqual(resolved["attachments"][0]["color"], blocks.COLORS["ok"])
        self.assertIn("after 1 h 35 min", resolved["attachments"][0]["blocks"][0]["elements"][0]["text"])
        self.assertTrue(resolved["text"].startswith("[RESOLVED] AWS alb-5xx"))
        self.assertEqual(posted["blocks"][0]["text"]["text"], ":red_circle: CRITICAL · alb-5xx")  # untouched

    def test_follow_up_says_how_long_and_where_it_is_now(self):
        from datetime import timedelta
        from anomaly_alerts.slack import threads
        msg = threads.follow_up_text(make_anomaly(), NOW, NOW + timedelta(hours=2), escalated=False)
        self.assertIn(":repeat: *Still firing* after 2 h: ↑ 412 (69× usual)", msg["text"])
        up = threads.follow_up_text(make_anomaly(), NOW, NOW + timedelta(hours=1), escalated=True)
        self.assertTrue(up["text"].startswith(":red_circle: *Now CRITICAL* after 1 h"))
        self.assertTrue(threads.escalated("warning", "critical"))
        self.assertFalse(threads.escalated("critical", "critical"))


class BotReplyTests(unittest.TestCase):
    def test_reply_posts_in_the_thread(self):
        from anomaly_alerts.slack.bot import SlackBot
        sent = []

        class Resp:
            status = 200
            def __init__(self, body): self.body = body
            def read(self): return self.body
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(request, timeout):
            sent.append(json.loads(request.data))
            return Resp(b'{"ok": true, "ts": "2.0"}')

        ts = SlackBot("xoxb-test", "C1", opener=opener).reply("1.0", {"text": "hi"}, broadcast=True)
        self.assertEqual(ts, "2.0")
        self.assertEqual((sent[0]["thread_ts"], sent[0]["reply_broadcast"], sent[0]["channel"]), ("1.0", True, "C1"))
