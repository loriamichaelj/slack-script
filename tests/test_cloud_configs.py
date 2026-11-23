"""The config each cloud's Terraform renders for its jobs must load, and say what we intend."""

import re
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from anomaly_alerts import config

TERRAFORM = Path(__file__).resolve().parent.parent / "terraform"

# What Terraform fills in, with stand-ins that have the right shape.
SHARED = {"slack_channel_id": "C0123456789", "time_zone": "America/New_York"}
VALUES = {
    "gcp": {
        "project_id": "my-project", "billing_table": "p.d.t", "second_billing_table": "p.d.t2",
        "mount_path": "/mnt/app", **SHARED,
    },
    "aws": {"bucket": "my-bucket", "region": "us-east-1", "function_name": "anomaly-alerts", **SHARED},
    "azure": {
        **SHARED,
        "state_url": "https://acct.blob.core.windows.net/app/state/alerts.json",
        "state_account_id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/acct",
        "subscription_scope": "/subscriptions/s",
        "jobs_scope": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/jobs",
        "audit_workspace_id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w",
        "budget": "5",
    },
}

EXPECTED_METRICS = {
    "gcp": {
        "org-error-logs", "org-api-errors", "cloud-run-job-failures", "anomaly-run-succeeded", "site-up",
        "audit-iam-changes", "audit-new-footprint", "audit-sa-key-created", "audit-logging-changed",
        "audit-made-public", "audit-kms-key-destroyed",
    },
    "aws": {
        "lambda-errors", "lambda-invocations", "lambda-duration", "aws-RootOrNoMfaSignIn", "aws-IamChanges",
        "aws-AccessKeyCreated", "aws-LoggingChanged", "aws-MadePublic", "aws-OutsideHomeRegion",
        "aws-KmsKeyDisabled",
    },
    "azure": {
        "state-account-transactions", "azure-role-changes", "azure-logging-changed", "azure-network-exposure",
        "azure-key-vault-changed", "azure-new-footprint", "azure-security-alerts", "azure-service-health",
        "azure-job-failures-anomaly-run", "azure-job-failures-routine-heartbeat",
        "azure-job-failures-routine-digest", "azure-job-failures-routine-cost",
    },
}

# The metric on each cloud that proves the 5 minute schedule is still running.
SCHEDULE_CHECK = {"gcp": "anomaly-run-succeeded", "aws": "lambda-invocations", "azure": "state-account-transactions"}


def load(cloud):
    text = (TERRAFORM / cloud / "dev" / "config.yaml.tftpl").read_text()
    text = re.sub(r"\$\{(\w+)\}", lambda m: VALUES[cloud][m.group(1)], text)  # a missing value raises
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "config.yaml"
        path.write_text(text)
        return config.load(path)


def azure_routine_jobs():
    """Each Azure routine job's cron hours (UTC) and the --local-hours it is started with."""
    text = (TERRAFORM / "azure" / "dev" / "jobs.tf").read_text()
    jobs = {}
    for name in ("heartbeat", "digest", "cost"):
        block = re.search(rf'"routine-{name}" = \{{(.*?)\n    \}}', text, re.S).group(1)
        cron = re.search(r'schedule = "(\S+) (\S+) \* \* \*"', block)
        hours = re.search(r'"--local-hours", "([\d,]+)"', block)
        jobs[name] = (int(cron.group(1)), {int(h) for h in cron.group(2).split(",")}, {int(h) for h in hours.group(1).split(",")})
    return jobs


class CloudConfigTests(unittest.TestCase):
    def test_every_cloud_fills_in_the_shared_message_as_itself(self):
        for cloud in EXPECTED_METRICS:
            with self.subTest(cloud=cloud):
                shared = load(cloud).slack.shared_message
                self.assertEqual(shared.cloud, cloud)
                self.assertEqual(shared.clouds, ("aws", "azure", "gcp"))
                self.assertEqual((shared.channel, shared.time_zone), ("C0123456789", "America/New_York"))

    def test_audit_metrics_are_read_once_per_period_and_look_back_two(self):
        for cloud in EXPECTED_METRICS:
            with self.subTest(cloud=cloud):
                audit = [m for m in load(cloud).metrics if m.category == "security"]
                self.assertTrue(audit)
                for m in audit:
                    self.assertEqual((m.every_seconds, m.within, m.period_seconds), (1800, 2, 1800), m.name)

    def test_every_cloud_threads_its_alerts_in_the_shared_channel(self):
        for cloud in EXPECTED_METRICS:
            with self.subTest(cloud=cloud):
                threads = load(cloud).slack.alert_threads
                self.assertEqual((threads.channel, threads.bot_token_env), ("C0123456789", "SLACK_BOT_TOKEN"))

    def test_azure_runs_at_every_utc_hour_its_local_hours_can_be_in_winter_and_summer(self):
        zone = ZoneInfo("America/New_York")
        for name, (_, utc_hours, local_hours) in azure_routine_jobs().items():
            for month in (1, 7):  # standard time and daylight saving time
                with self.subTest(job=name, month=month):
                    reached = {datetime(2026, month, 15, h, tzinfo=UTC).astimezone(zone).hour for h in utc_hours}
                    self.assertTrue(local_hours <= reached, f"{name}: {sorted(local_hours - reached)} never runs")

    def test_the_clouds_report_a_few_minutes_apart_so_they_fill_in_one_message_in_turn(self):
        azure = {name: minute for name, (minute, _, _) in azure_routine_jobs().items()}
        self.assertEqual(azure, {"heartbeat": 4, "digest": 4, "cost": 34})
        gcp = (TERRAFORM / "gcp" / "dev" / "jobs.tf").read_text()
        self.assertEqual(re.findall(r'schedule = "(\d+) (?:\*/6|9) \* \* \*"', gcp), ["2", "2", "32"])  # heartbeat, digest, cost
        aws = (TERRAFORM / "aws" / "dev" / "schedules.tf").read_text()
        self.assertIn('"cron(0 0/6 * * ? *)"', aws)
        self.assertIn('"cron(30 9 * * ? *)"', aws)


    def test_each_template_loads_with_the_expected_metrics(self):
        for cloud, names in EXPECTED_METRICS.items():
            with self.subTest(cloud=cloud):
                self.assertEqual({m.name for m in load(cloud).metrics}, names)

    def test_every_billing_account_has_a_five_dollar_monthly_budget(self):
        accounts = {"gcp": 2, "aws": 1, "azure": 1}  # GCP has two billing accounts
        for cloud in EXPECTED_METRICS:
            with self.subTest(cloud=cloud):
                budgets = [a.budget for a in load(cloud).cost.accounts]
                self.assertEqual(budgets, [5.0] * accounts[cloud])

    def test_the_azure_budget_variable_defaults_to_five(self):
        text = (TERRAFORM / "azure" / "dev" / "variables.tf").read_text()
        match = re.search(r'variable "budget" \{.*?default\s*=\s*(\d+)', text, re.S)
        self.assertEqual(match.group(1), "5")

    def test_the_schedule_check_fires_on_a_stopped_schedule_and_not_before(self):
        for cloud, name in SCHEDULE_CHECK.items():
            spec = next(m for m in load(cloud).metrics if m.name == name)
            with self.subTest(cloud=cloud):
                self.assertEqual(spec.direction, "drop")
                self.assertEqual(spec.fill_missing, "zero")  # a missing period means it did not run
                self.assertGreaterEqual(spec.min_abs_change, 1)
                self.assertEqual(spec.sustained_points, 3)  # so one or two missed runs stay quiet

    def test_the_schedule_check_counts_one_run_per_period(self):
        schedules = {"gcp": 600, "aws": 300, "azure": 300}  # how often each alert job runs
        for cloud, name in SCHEDULE_CHECK.items():
            cfg = load(cloud)
            spec = next(m for m in cfg.metrics if m.name == name)
            with self.subTest(cloud=cloud):
                self.assertEqual(cfg.run_every_seconds, schedules[cloud])
                if cloud == "gcp":
                    self.assertEqual(spec.period_seconds, schedules[cloud])
        jobs = (TERRAFORM / "gcp" / "dev" / "jobs.tf").read_text()
        self.assertIn('schedule = "*/10 * * * *"', jobs)

    def test_the_gcp_alert_job_gets_the_bot_token_for_threads(self):
        jobs = (TERRAFORM / "gcp" / "dev" / "jobs.tf").read_text()
        block = re.search(r'"anomaly-run" = \{(.*?)\n    \}', jobs, re.S).group(1)
        self.assertIn('SLACK_BOT_TOKEN   = "slack-bot-token"', block)

    def test_the_duration_metric_only_cares_about_a_real_slowdown(self):
        spec = next(m for m in load("aws").metrics if m.name == "lambda-duration")
        self.assertEqual(spec.direction, "spike")
        self.assertGreaterEqual(spec.min_abs_change, 30000)  # milliseconds; cold starts are about 4000


if __name__ == "__main__":
    unittest.main()
