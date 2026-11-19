import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from anomaly_alerts import cli, config, routine
from anomaly_alerts.config import Config, SharedMessage, SlackConfig
from anomaly_alerts.providers import ProviderPool
from anomaly_alerts.slack import blocks, shared
from anomaly_alerts.slack.bot import EVENT_TYPE, Found, SlackBot
from anomaly_alerts.slack.client import SlackError
from helpers import make_series, make_spec

# 12:00 ET on 2026-11-19 is 17:00 UTC.
NOON = datetime(2026, 11, 19, 17, 0, tzinfo=UTC)
CLOUDS = ("aws", "azure", "gcp")
ZONE = "America/New_York"


def report(level="ok", label="OK", detail="", text="x"):
    body = [{"type": "section", "text": {"type": "mrkdwn", "text": "Checked *3* of *3* metrics"}}]
    return blocks.Report("Heartbeat", label, level, body, text, detail)


class FakeBot:
    """A channel in memory that behaves like the parts of Slack the shared message uses."""

    def __init__(self):
        self.messages = {}  # ts -> {"blocks": ..., "metadata": ...}
        self.next_ts = 1000.0
        self.calls = []
        self.drop_next_update = False  # a racing writer overwrote this one

    def find(self, kind, slot, since):
        self.calls.append("find")
        found = []
        for ts, m in self.messages.items():
            payload = m["metadata"]["event_payload"]
            if payload["kind"] == kind and payload["slot"] == slot:
                found.append(Found(ts, m["blocks"], payload["levels"]))
        return sorted(found, key=lambda f: float(f.ts))

    def post(self, message, metadata):
        self.calls.append("post")
        self.next_ts += 1
        ts = f"{self.next_ts:.6f}"
        self.messages[ts] = {"blocks": message["blocks"], "metadata": metadata, "text": message["text"]}
        return ts

    def update(self, ts, message, metadata):
        self.calls.append("update")
        if self.drop_next_update:
            self.drop_next_update = False
            return
        self.messages[ts] = {"blocks": message["blocks"], "metadata": metadata, "text": message["text"]}

    def delete(self, ts):
        self.calls.append("delete")
        del self.messages[ts]


def publish(bot, provider, rep, now=NOON, **kwargs):
    shared.publish(
        bot, rep, kind="heartbeat", provider=provider, now=now, expected=CLOUDS, time_zone=ZONE,
        sleep=lambda _: None, **kwargs,
    )


def text_of(message):
    return json.dumps(message["blocks"])


class SlotTests(unittest.TestCase):
    def test_heartbeats_share_a_slot_for_six_hours_in_local_time(self):
        # 05:00 UTC is 00:00 ET in winter and 01:00 ET in summer: the same slot for both clouds.
        winter = datetime(2026, 11, 19, 5, 0, tzinfo=UTC)
        summer = datetime(2026, 7, 19, 4, 0, tzinfo=UTC)
        self.assertEqual(shared.slot_key("heartbeat", winter, ZONE), "2026-11-19-00")
        self.assertEqual(shared.slot_key("heartbeat", winter + timedelta(minutes=4), ZONE), "2026-11-19-00")
        self.assertEqual(shared.slot_key("heartbeat", summer, ZONE), "2026-07-19-00")
        self.assertEqual(shared.slot_key("heartbeat", NOON, ZONE), "2026-11-19-12")

    def test_daily_reports_share_the_local_day(self):
        for kind in ("digest", "cost"):
            self.assertEqual(shared.slot_key(kind, datetime(2026, 11, 19, 14, 0, tzinfo=UTC), ZONE), "2026-11-19")

    def test_a_local_day_is_not_the_utc_day(self):
        self.assertEqual(shared.slot_key("cost", datetime(2026, 11, 20, 2, 0, tzinfo=UTC), ZONE), "2026-11-19")


class ComposeTests(unittest.TestCase):
    def test_section_blocks_carry_the_cloud_in_their_ids(self):
        out = shared.section_blocks("aws", report(detail="2026-11-18"))
        self.assertEqual([b["block_id"] for b in out], ["aws:0", "aws:1"])
        self.assertIn(":large_green_circle: *AWS*: OK (2026-11-18)", out[0]["text"]["text"])

    def test_a_long_body_is_cut_to_fit_the_message(self):
        long = blocks.Report("Health digest", "OK", "ok", [report().body[0]] * 40, "x")
        out = shared.section_blocks("gcp", long)
        self.assertEqual(len(out), 15)
        self.assertIn("does not fit", json.dumps(out[-1]))

    def test_split_sections_ignores_head_and_foot(self):
        message, _ = shared.compose(
            "heartbeat", "s", NOON, {"aws": shared.section_blocks("aws", report())}, {"aws": "ok"}, CLOUDS
        )
        self.assertEqual(list(shared.split_sections(message["blocks"])), ["aws"])

    def test_overall_status_is_the_worst_cloud_and_waiting_clouds_are_named(self):
        sections = {
            "aws": shared.section_blocks("aws", report()),
            "gcp": shared.section_blocks("gcp", report("critical", "ALERTING")),
        }
        message, metadata = shared.compose("heartbeat", "s", NOON, sections, {"aws": "ok", "gcp": "critical"}, CLOUDS)
        text = text_of(message)
        self.assertIn("*Heartbeat: CRITICAL*", text)
        self.assertIn("Waiting for Azure", text)
        self.assertLess(text.index("*AWS*"), text.index("*GCP*"))
        self.assertEqual(message["text"], "Heartbeat CRITICAL: AWS, GCP")
        self.assertEqual(metadata["event_type"], EVENT_TYPE)
        self.assertEqual(metadata["event_payload"]["levels"], {"aws": "ok", "gcp": "critical"})

    def test_nothing_is_waiting_once_every_cloud_has_reported(self):
        sections = {p: shared.section_blocks(p, report()) for p in CLOUDS}
        message, _ = shared.compose("heartbeat", "s", NOON, sections, {}, CLOUDS)
        self.assertNotIn("Waiting", text_of(message))


class PublishTests(unittest.TestCase):
    def test_the_first_cloud_posts_and_the_others_fill_in_the_same_message(self):
        bot = FakeBot()
        for provider in CLOUDS:
            publish(bot, provider, report())
        self.assertEqual(len(bot.messages), 1)
        text = text_of(next(iter(bot.messages.values())))
        for label in ("AWS", "Azure", "GCP"):
            self.assertIn(f"*{label}*", text)
        self.assertNotIn("Waiting", text)
        self.assertEqual(bot.calls.count("post"), 1)
        self.assertEqual(bot.calls.count("update"), 2)

    def test_a_later_run_replaces_only_its_own_section(self):
        bot = FakeBot()
        publish(bot, "aws", report("ok", "OK"))
        publish(bot, "gcp", report("warning", "DEGRADED"))
        publish(bot, "aws", report("critical", "ALERTING"))
        (message,) = bot.messages.values()
        text = json.dumps(message["blocks"])
        self.assertIn("ALERTING", text)
        self.assertNotIn("*AWS*: OK", text)
        self.assertIn("*GCP*: DEGRADED", text)
        self.assertEqual(message["metadata"]["event_payload"]["levels"], {"aws": "critical", "gcp": "warning"})

    def test_a_different_slot_is_a_different_message(self):
        bot = FakeBot()
        publish(bot, "aws", report())
        publish(bot, "aws", report(), now=NOON + timedelta(hours=6))
        self.assertEqual(len(bot.messages), 2)

    def test_two_messages_posted_at_once_are_merged_into_the_older_one(self):
        bot = FakeBot()
        for provider in ("aws", "gcp"):  # both found nothing and posted
            message, metadata = shared.compose(
                "heartbeat", shared.slot_key("heartbeat", NOON, ZONE), NOON,
                {provider: shared.section_blocks(provider, report())}, {provider: "ok"}, CLOUDS,
            )
            bot.post(message, metadata)
        first = min(bot.messages)
        publish(bot, "azure", report())
        self.assertEqual(list(bot.messages), [first])
        text = text_of({"blocks": bot.messages[first]["blocks"]})
        for label in ("AWS", "Azure", "GCP"):
            self.assertIn(f"*{label}*", text)

    def test_a_section_lost_to_a_racing_writer_is_written_again(self):
        bot = FakeBot()
        publish(bot, "aws", report())
        bot.drop_next_update = True
        publish(bot, "gcp", report())
        (message,) = bot.messages.values()
        self.assertIn("*GCP*", text_of(message))
        self.assertEqual(bot.calls.count("update"), 2 + 0)  # the dropped write, then the repeat

    def test_gives_up_when_the_section_never_sticks(self):
        bot = FakeBot()
        publish(bot, "aws", report())
        bot.update = lambda *a, **k: None
        with self.assertRaises(SlackError):
            publish(bot, "gcp", report())


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SlackBotTests(unittest.TestCase):
    def bot(self, replies):
        self.requests = []
        queue = list(replies)

        def opener(request, timeout):
            self.requests.append(request)
            reply = queue.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return FakeResponse(reply)

        return SlackBot("xoxb-secret", "C1", opener=opener, sleep=lambda _: None)

    def test_find_returns_only_this_slots_messages_oldest_first(self):
        def message(ts, kind="heartbeat", slot="s", event=EVENT_TYPE):
            return {
                "ts": ts, "blocks": [{"block_id": "aws:0"}],
                "metadata": {"event_type": event, "event_payload": {"kind": kind, "slot": slot, "levels": {"aws": "ok"}}},
            }

        reply = {"ok": True, "messages": [
            message("3.0"), message("2.0"), message("2.5", slot="other"),
            message("2.6", kind="cost"), message("2.7", event="other"), {"ts": "1.0", "text": "hello"},
        ]}
        found = self.bot([reply]).find("heartbeat", "s", 0)
        self.assertEqual([f.ts for f in found], ["2.0", "3.0"])
        self.assertEqual(found[0].levels, {"aws": "ok"})
        request = self.requests[0]
        self.assertTrue(request.full_url.endswith("/conversations.history"))
        self.assertIn(b"include_all_metadata=true", request.data)
        self.assertEqual(request.get_header("Authorization"), "Bearer xoxb-secret")

    def test_post_update_and_delete_send_json_to_the_channel(self):
        bot = self.bot([{"ok": True, "ts": "9.0"}, {"ok": True}, {"ok": True}])
        self.assertEqual(bot.post({"text": "t", "blocks": []}, {"event_type": "e"}), "9.0")
        bot.update("9.0", {"text": "t", "blocks": []}, {"event_type": "e"})
        bot.delete("9.0")
        bodies = [json.loads(r.data) for r in self.requests]
        self.assertEqual([b["channel"] for b in bodies], ["C1"] * 3)
        self.assertEqual(bodies[1]["ts"], "9.0")
        self.assertEqual(bodies[0]["metadata"], {"event_type": "e"})
        self.assertEqual(
            [r.full_url.rsplit("/", 1)[1] for r in self.requests], ["chat.postMessage", "chat.update", "chat.delete"]
        )

    def test_a_slack_error_names_only_slacks_code(self):
        bot = self.bot([{"ok": False, "error": "channel_not_found"}])
        with self.assertRaises(SlackError) as ctx:
            bot.delete("1.0")
        self.assertEqual(str(ctx.exception), "Slack chat.delete failed: channel_not_found")
        self.assertNotIn("xoxb", str(ctx.exception))

    def test_a_rate_limit_is_retried(self):
        limited = urllib.error.HTTPError("u", 429, "x", {"Retry-After": "1"}, None)
        bot = self.bot([limited, {"ok": True}])
        bot.delete("1.0")
        self.assertEqual(len(self.requests), 2)

    def test_a_client_error_is_not_retried_and_hides_the_token(self):
        bot = self.bot([urllib.error.HTTPError("https://slack.com/api/x?token=xoxb-secret", 403, "x", {}, None)])
        with self.assertRaises(SlackError) as ctx:
            bot.delete("1.0")
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("xoxb", str(ctx.exception))


class SharedConfigTests(unittest.TestCase):
    def load(self, slack_yaml):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "config.yaml"
        path.write_text(
            f"slack:\n{slack_yaml}\nmetrics:\n  - {{name: cpu, provider: aws, region: r, namespace: n, metric: m}}\n"
        )
        return config.load(path)

    def rejects(self, slack_yaml, fragment):
        with self.assertRaises(config.ConfigError) as ctx:
            self.load(slack_yaml)
        self.assertIn(fragment, str(ctx.exception))

    def test_it_is_off_by_default(self):
        self.assertIsNone(self.load("  cooldown_minutes: 5").slack.shared_message)

    def test_a_full_section_is_read(self):
        cfg = self.load(
            "  shared_message:\n    cloud: azure\n    clouds: [aws, azure, gcp]\n    channel: C0CC5RTC4R0\n"
            "    bot_token_env: TOKEN\n    time_zone: America/Chicago"
        )
        self.assertEqual(
            cfg.slack.shared_message,
            SharedMessage("azure", ("aws", "azure", "gcp"), "C0CC5RTC4R0", "TOKEN", "America/Chicago"),
        )

    def test_defaults(self):
        shared_message = self.load("  shared_message: {cloud: gcp, channel: C1}").slack.shared_message
        self.assertEqual(
            (shared_message.clouds, shared_message.bot_token_env, shared_message.time_zone),
            (("gcp",), "SLACK_BOT_TOKEN", "America/New_York"),
        )

    def test_bad_values_are_rejected(self):
        self.rejects("  shared_message: {cloud: oracle, channel: C1}", "cloud must be one of")
        self.rejects("  shared_message: {cloud: aws}", "channel is required")
        self.rejects("  shared_message: {cloud: aws, channel: C1, clouds: [gcp]}", "including aws")
        self.rejects("  shared_message: {cloud: aws, channel: C1, clouds: [aws, aws]}", "each cloud once")
        self.rejects("  shared_message: {cloud: aws, channel: C1, time_zone: Mars/Base}", "not a known time zone")
        self.rejects("  shared_message: {cloud: aws, channel: C1, extra: 1}", "unknown key")
        self.rejects("  shared_message: [aws]", "must be a mapping")


QUIET_72 = [10 + (i % 5) for i in range(72)]


class RoutineDeliveryTests(unittest.TestCase):
    def run_heartbeat(self, publish, post):
        cfg = Config(SlackConfig("X"), Path("unused.json"), None, [make_spec()])
        pool = ProviderPool({"aws": mock.Mock(fetch=lambda spec, start, end: make_series(QUIET_72))})
        return routine.run_heartbeat(cfg, pool, post, NOON, publish=publish)

    def test_a_published_report_is_not_also_posted_on_its_own(self):
        published, posted = [], []
        result = self.run_heartbeat(lambda r, now: published.append(r), posted.append)
        self.assertEqual((len(published), len(posted), result.posted, result.ok), (1, 0, 1, True))
        self.assertEqual(published[0].name, "Heartbeat")

    def test_a_failed_publish_falls_back_to_the_webhook(self):
        def broken(report, now):
            raise SlackError("Slack chat.update failed: channel_not_found")

        posted = []
        result = self.run_heartbeat(broken, posted.append)
        self.assertEqual((len(posted), result.posted, result.post_errors), (1, 1, 0))
        self.assertIn("Heartbeat OK", posted[0]["text"])

    def test_the_run_fails_when_the_webhook_fallback_fails_too(self):
        def broken(*args):
            raise SlackError("down")

        result = self.run_heartbeat(broken, broken)
        self.assertEqual((result.posted, result.post_errors, result.ok), (0, 1, False))


class SharedCliTests(unittest.TestCase):
    YAML = """
slack:
  shared_message: {cloud: aws, clouds: [aws, azure, gcp], channel: C1}
metrics:
  - {name: cpu, provider: aws, region: us-east-1, namespace: AWS/EC2, metric: CPUUtilization}
"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "config.yaml"
        self.path.write_text(self.YAML)

    def run_cli(self, env, *argv):
        out = io.StringIO()
        pool = ProviderPool({"aws": mock.Mock(fetch=lambda spec, start, end: make_series(QUIET_72))})
        with mock.patch.object(cli, "ProviderPool", return_value=pool), \
                mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_dry_run_prints_this_clouds_part_of_the_shared_message(self):
        code, out = self.run_cli({}, "routine", "--config", str(self.path), "--dry-run")
        self.assertEqual(code, 0)
        message = json.loads(out)
        self.assertEqual(message["text"], "Heartbeat OK: AWS")
        self.assertIn("Waiting for Azure, GCP", text_of(message))

    def test_without_the_bot_token_the_report_goes_to_the_webhook(self):
        with mock.patch.object(cli.client, "post") as webhook:
            code, _ = self.run_cli({"SLACK_WEBHOOK_URL": "https://hooks.example/x"}, "routine", "--config", str(self.path))
        self.assertEqual(code, 0)
        self.assertIn("Heartbeat OK", webhook.call_args.args[1]["text"])

    def test_with_the_bot_token_the_shared_message_is_used(self):
        env = {"SLACK_WEBHOOK_URL": "https://hooks.example/x", "SLACK_BOT_TOKEN": "xoxb-token"}
        with mock.patch.object(cli.shared, "publish") as publish, mock.patch.object(cli.client, "post") as webhook:
            code, _ = self.run_cli(env, "routine", "--config", str(self.path))
        self.assertEqual(code, 0)
        webhook.assert_not_called()
        kwargs = publish.call_args.kwargs
        self.assertEqual((kwargs["kind"], kwargs["provider"], kwargs["expected"]), ("heartbeat", "aws", ("aws", "azure", "gcp")))


if __name__ == "__main__":
    unittest.main()
