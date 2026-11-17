"""The config each cloud's Terraform renders for its jobs must load, and say what we intend."""

import re
import tempfile
import unittest
from pathlib import Path

from anomaly_alerts import config

TERRAFORM = Path(__file__).resolve().parent.parent / "terraform"

# What Terraform fills in, with stand-ins that have the right shape.
VALUES = {
    "gcp": {"project_id": "my-project", "billing_table": "p.d.t", "mount_path": "/mnt/app"},
    "aws": {"bucket": "my-bucket", "region": "us-east-1", "function_name": "anomaly-alerts"},
    "azure": {
        "state_url": "https://acct.blob.core.windows.net/app/state/alerts.json",
        "state_account_id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/acct",
        "subscription_scope": "/subscriptions/s",
        "budget": "5",
    },
}

EXPECTED_METRICS = {
    "gcp": {"org-error-logs", "org-api-errors", "cloud-run-job-failures", "anomaly-run-succeeded"},
    "aws": {"lambda-errors", "lambda-invocations", "lambda-duration"},
    "azure": {"state-account-transactions"},
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


class CloudConfigTests(unittest.TestCase):
    def test_each_template_loads_with_the_expected_metrics(self):
        for cloud, names in EXPECTED_METRICS.items():
            with self.subTest(cloud=cloud):
                self.assertEqual({m.name for m in load(cloud).metrics}, names)

    def test_each_cloud_has_a_five_dollar_monthly_budget(self):
        for cloud in EXPECTED_METRICS:
            with self.subTest(cloud=cloud):
                budgets = [a.budget for a in load(cloud).cost.accounts]
                self.assertEqual(budgets, [5.0])

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

    def test_the_duration_metric_only_cares_about_a_real_slowdown(self):
        spec = next(m for m in load("aws").metrics if m.name == "lambda-duration")
        self.assertEqual(spec.direction, "spike")
        self.assertGreaterEqual(spec.min_abs_change, 30000)  # milliseconds; cold starts are about 4000


if __name__ == "__main__":
    unittest.main()
