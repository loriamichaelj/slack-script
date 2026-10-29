import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock

from anomaly_alerts import cli, config, routine
from anomaly_alerts.config import Config, CostConfig, SlackConfig
from anomaly_alerts.cost import CostProviderPool
from anomaly_alerts.cost.report import CostSettings, fetch_window, report_day, summarize
from anomaly_alerts.models import CostData, CostSpec, DailyCost
from anomaly_alerts.slack import blocks
from anomaly_alerts.slack.client import SlackError
from helpers import make_spec

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
DAY = date(2026, 10, 28)
SETTINGS = CostSettings()


def spec(name="aws-main", provider="aws", **selector):
    return CostSpec(name, provider, selector)


def daily(amounts_by_service: dict, day=DAY, days_back=7):
    """Rows for day and the days_back days before it. Each service maps to (baseline, today)."""
    rows = []
    for service, (base, today) in amounts_by_service.items():
        rows.append(DailyCost(day, service, today))
        rows += [DailyCost(day - timedelta(days=i), service, base) for i in range(1, days_back + 1)]
    return rows


def data(rows, provider="aws", currency="USD"):
    return CostData(provider, "123456789012", currency, rows)


class FakeCost:
    def __init__(self, by_name):
        self.by_name = by_name
        self.calls = []

    def fetch(self, spec, start, end):
        self.calls.append((spec.name, start, end))
        result = self.by_name[spec.name]
        if isinstance(result, Exception):
            raise result
        return result


def all_text(payload):
    return json.dumps(payload)


class WindowTests(unittest.TestCase):
    def test_report_day_lags_today(self):
        self.assertEqual(report_day(NOW.date(), SETTINGS), DAY)
        self.assertEqual(report_day(NOW.date(), CostSettings(lag_days=2)), date(2026, 10, 27))

    def test_window_covers_the_baseline_and_month_to_date(self):
        self.assertEqual(fetch_window(DAY, SETTINGS), (date(2026, 10, 1), date(2026, 10, 29)))
        # Early in the month the baseline reaches back into the previous one.
        self.assertEqual(fetch_window(date(2026, 11, 2), SETTINGS), (date(2026, 10, 26), date(2026, 11, 3)))


class SummarizeTests(unittest.TestCase):
    def test_total_baseline_and_change(self):
        rows = daily({"EC2": (80.0, 120.0), "S3": (20.0, 30.0)})
        s = summarize(spec(), data(rows), DAY, SETTINGS)
        self.assertEqual((s.total, s.baseline), (150.0, 100.0))
        self.assertAlmostEqual(s.change_pct, 50.0)
        self.assertTrue(s.spike)
        self.assertEqual([(x.service, x.amount) for x in s.services], [("EC2", 120.0), ("S3", 30.0)])
        self.assertAlmostEqual(s.services[0].change_pct, 50.0)

    def test_month_to_date_stops_at_the_month_boundary(self):
        day = date(2026, 11, 2)
        rows = daily({"EC2": (10.0, 10.0)}, day=day)
        s = summarize(spec(), data(rows), day, SETTINGS)
        self.assertEqual(s.month_to_date, 20.0)  # Nov 1 and Nov 2 only

    def test_steady_spend_is_not_a_spike(self):
        s = summarize(spec(), data(daily({"EC2": (100.0, 110.0)})), DAY, SETTINGS)
        self.assertFalse(s.spike)

    def test_small_bill_does_not_spike_on_percentage_alone(self):
        s = summarize(spec(), data(daily({"S3": (0.10, 0.50)})), DAY, SETTINGS)
        self.assertAlmostEqual(s.change_pct, 400.0)
        self.assertFalse(s.spike)

    def test_missing_day_means_no_data_yet(self):
        rows = [r for r in daily({"EC2": (10.0, 10.0)}) if r.day != DAY]
        s = summarize(spec(), data(rows), DAY, SETTINGS)
        self.assertIsNone(s.total)
        self.assertIsNone(s.change_pct)
        self.assertFalse(s.spike)

    def test_no_history_has_no_baseline(self):
        s = summarize(spec(), data([DailyCost(DAY, "EC2", 5.0)]), DAY, SETTINGS)
        self.assertEqual(s.total, 5.0)
        self.assertIsNone(s.baseline)
        self.assertIsNone(s.change_pct)
        self.assertFalse(s.spike)

    def test_top_services_are_limited_and_sorted(self):
        rows = daily({f"svc{i}": (1.0, float(i)) for i in range(1, 9)})
        s = summarize(spec(), data(rows), DAY, CostSettings(top_services=3))
        self.assertEqual([x.service for x in s.services], ["svc8", "svc7", "svc6"])

    def test_rows_for_the_same_day_and_service_add_up(self):
        rows = [DailyCost(DAY, "EC2", 2.0), DailyCost(DAY, "EC2", 3.0)]
        s = summarize(spec(), data(rows), DAY, SETTINGS)
        self.assertEqual((s.total, s.services[0].amount), (5.0, 5.0))


def make_config(accounts, settings=SETTINGS):
    return Config(SlackConfig("X"), Path("unused.json"), None, [make_spec()], CostConfig(settings, accounts))


class RunCostTests(unittest.TestCase):
    def setUp(self):
        self.posted = []

    def run_cost(self, by_name, accounts, post=None, overrides=None, **kwargs):
        pool = CostProviderPool(overrides if overrides is not None else {"aws": FakeCost(by_name)})
        return routine.run_cost(make_config(accounts), pool, post or self.posted.append, NOW, **kwargs)

    def test_quiet_day_posts_ok(self):
        result = self.run_cost({"aws-main": data(daily({"EC2": (100.0, 100.0)}))}, [spec()])
        self.assertEqual((result.checked, result.total, result.anomalies, result.fetch_errors), (1, 1, 0, 0))
        payload = self.posted[0]
        self.assertEqual(payload["text"], "Cost report for 2026-10-28 OK: 1 account")
        self.assertEqual(payload["attachments"][0]["color"], blocks.COLORS["ok"])
        text = all_text(payload)
        self.assertIn("*100.00 USD* vs 100.00 USD daily average (+0%)", text)
        self.assertIn("month to date 800.00 USD", text)  # the fake data covers 8 days
        self.assertIn("EC2: 100.00 USD (+0%)", text)

    def test_fetches_the_report_window(self):
        fake = FakeCost({"aws-main": data([])})
        self.run_cost(None, [spec()], overrides={"aws": fake})
        self.assertEqual(fake.calls, [("aws-main", date(2026, 10, 1), date(2026, 10, 29))])

    def test_spike_is_flagged_and_listed_first(self):
        accounts = [spec("aaa"), spec("zzz")]
        by_name = {
            "aaa": data(daily({"EC2": (100.0, 100.0)})),
            "zzz": data(daily({"EC2": (100.0, 200.0)})),
        }
        result = self.run_cost(by_name, accounts)
        self.assertEqual(result.anomalies, 1)
        payload = self.posted[0]
        self.assertEqual(payload["text"], "Cost report for 2026-10-28 SPIKE: 2 accounts, 1 spike")
        text = all_text(payload)
        self.assertLess(text.index("*zzz*"), text.index("*aaa*"))
        self.assertIn(":chart_with_upwards_trend: *zzz*", text)
        self.assertIn("Total: *300.00 USD*", text)

    def test_mixed_currencies_have_no_grand_total(self):
        accounts = [spec("us"), spec("eu")]
        by_name = {
            "us": data(daily({"EC2": (1.0, 1.0)})),
            "eu": data(daily({"VM": (1.0, 1.0)}), currency="EUR"),
        }
        self.run_cost(by_name, accounts)
        self.assertNotIn("Total:", all_text(self.posted[0]))

    def test_fetch_error_names_the_account_without_error_text(self):
        accounts = [spec("good"), spec("bad")]
        by_name = {
            "good": data(daily({"EC2": (1.0, 1.0)})),
            "bad": RuntimeError("AccessDenied for arn:aws:iam::123456789012:role/secret-name"),
        }
        result = self.run_cost(by_name, accounts)
        self.assertEqual((result.checked, result.fetch_errors), (1, 1))
        self.assertTrue(result.ok)
        payload = self.posted[0]
        self.assertEqual(payload["text"], "Cost report for 2026-10-28 DEGRADED: 2 accounts, 1 fetch error")
        text = all_text(payload)
        self.assertIn(":warning: *bad* (AWS): could not fetch costs", text)
        self.assertNotIn("AccessDenied", text)
        self.assertNotIn("secret-name", text)

    def test_cloud_without_an_adapter_counts_as_a_fetch_error(self):
        result = self.run_cost(None, [spec("gcp-dev", "gcp", billing_table="t")], overrides={})
        self.assertEqual(result.fetch_errors, 1)
        self.assertIn("could not fetch costs", all_text(self.posted[0]))

    def test_no_data_yet_is_shown(self):
        rows = [r for r in daily({"EC2": (1.0, 1.0)}) if r.day != DAY]
        self.run_cost({"aws-main": data(rows)}, [spec()])
        self.assertIn("no cost data for 2026-10-28 yet", all_text(self.posted[0]))

    def test_only_limits_to_one_cloud(self):
        accounts = [spec(), spec("azure-prod", "azure", scope="/subscriptions/x")]
        result = self.run_cost({"aws-main": data([])}, accounts, only="aws")
        self.assertEqual(result.total, 1)

    def test_failed_post_fails_the_run(self):
        def boom(payload):
            raise SlackError("Slack returned HTTP 500")

        result = self.run_cost({"aws-main": data([])}, [spec()], post=boom)
        self.assertFalse(result.ok)

    def test_missing_cost_section_is_rejected(self):
        cfg = Config(SlackConfig("X"), Path("unused.json"), None, [make_spec()])
        with self.assertRaises(ValueError):
            routine.run_cost(cfg, CostProviderPool({}), self.posted.append, NOW)

    def test_names_and_services_are_escaped(self):
        rows = daily({"<svc>": (1.0, 1.0)})
        self.run_cost({"a<b>&c": data(rows)}, [spec("a<b>&c")])
        text = all_text(self.posted[0])
        self.assertIn("a&lt;b&gt;&amp;c", text)
        self.assertIn("&lt;svc&gt;", text)


class CostConfigTests(unittest.TestCase):
    YAML = """
metrics:
  - name: cpu
    provider: aws
    region: us-east-1
    namespace: AWS/EC2
    metric: CPUUtilization
%s
"""

    def load(self, cost_yaml):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "config.yaml"
        path.write_text(self.YAML % cost_yaml)
        return config.load(path)

    def assert_error(self, cost_yaml, fragment):
        with self.assertRaises(config.ConfigError) as ctx:
            self.load(cost_yaml)
        self.assertIn(fragment, str(ctx.exception))

    def test_cost_section_is_optional(self):
        self.assertIsNone(self.load("").cost)

    def test_accounts_and_settings_are_read(self):
        cfg = self.load("""
cost:
  baseline_days: 14
  accounts:
    - {name: aws-main, provider: aws}
    - {name: azure-prod, provider: azure, scope: /subscriptions/x}
    - {name: gcp-dev, provider: gcp, billing_table: p.d.t, project: dev}
""")
        self.assertEqual(cfg.cost.settings.baseline_days, 14)
        self.assertEqual(cfg.cost.settings.alert_pct, 25.0)
        self.assertEqual(
            [(a.name, a.provider, a.selector) for a in cfg.cost.accounts],
            [
                ("aws-main", "aws", {}),
                ("azure-prod", "azure", {"scope": "/subscriptions/x"}),
                ("gcp-dev", "gcp", {"billing_table": "p.d.t", "project": "dev"}),
            ],
        )

    def test_missing_required_selector(self):
        self.assert_error("cost: {accounts: [{name: a, provider: azure}]}", "missing required key(s) ['scope']")

    def test_unknown_selector(self):
        self.assert_error("cost: {accounts: [{name: a, provider: aws, region: x}]}", "unknown key(s) ['region']")

    def test_unknown_provider(self):
        self.assert_error("cost: {accounts: [{name: a, provider: oci}]}", "provider must be one of")

    def test_accounts_are_required(self):
        self.assert_error("cost: {baseline_days: 7}", "accounts must list at least one account")

    def test_duplicate_account_names(self):
        self.assert_error(
            "cost: {accounts: [{name: a, provider: aws}, {name: a, provider: aws}]}", "duplicate account name"
        )

    def test_unknown_setting(self):
        self.assert_error("cost: {window: 3, accounts: [{name: a, provider: aws}]}", "unknown key(s) ['window']")

    def test_out_of_range_setting(self):
        self.assert_error("cost: {baseline_days: 90, accounts: [{name: a, provider: aws}]}", "at most 28")


class CostCliTests(unittest.TestCase):
    YAML = """
metrics:
  - name: cpu
    provider: aws
    region: us-east-1
    namespace: AWS/EC2
    metric: CPUUtilization
"""

    def write(self, extra=""):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "config.yaml"
        path.write_text(self.YAML + extra)
        return str(path)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        pool = CostProviderPool({"aws": FakeCost({"aws-main": data(daily({"EC2": (1.0, 1.0)}))})})
        with mock.patch.object(cli, "CostProviderPool", return_value=pool), \
                mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_cost_dry_run_prints_the_report(self):
        path = self.write("cost: {accounts: [{name: aws-main, provider: aws}]}\n")
        code, out, _ = self.run_cli("routine", "--config", path, "--kind", "cost", "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["text"].startswith("Cost report for "))

    def test_cost_without_a_cost_section_is_a_config_error(self):
        code, _, err = self.run_cli("routine", "--config", self.write(), "--kind", "cost", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("needs a cost section", err)


if __name__ == "__main__":
    unittest.main()
