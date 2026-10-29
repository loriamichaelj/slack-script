import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from anomaly_alerts import config
from anomaly_alerts.cost import CostProviderPool
from anomaly_alerts.cost.gcp import GcpCostProvider
from anomaly_alerts.models import CostSpec, DailyCost

TABLE = "billing-proj.billing.gcp_billing_export_v1_ABC123"


class FakeJob:
    def __init__(self, rows):
        self.rows = rows

    def result(self):
        return iter(self.rows)


class FakeBigQuery:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def query(self, sql, job_config=None):
        self.queries.append((sql, job_config))
        return FakeJob(self.rows)


def row(day, service, amount, currency="USD"):
    return {"day": day, "service": service, "amount": amount, "currency": currency}


def spec(**selector):
    return CostSpec("gcp-dev", "gcp", {"billing_table": TABLE, **selector})


class GcpCostProviderTests(unittest.TestCase):
    def setUp(self):
        self.projects, self.configs = [], []

    def provider(self, fake):
        def factory(project):
            self.projects.append(project)
            return fake

        def job_config(start, end, project):
            self.configs.append((start, end, project))
            return "job-config"

        return GcpCostProvider(client_factory=factory, job_config=job_config)

    def fetch(self, rows, **selector):
        fake = FakeBigQuery(rows)
        data = self.provider(fake).fetch(spec(**selector), date(2026, 10, 1), date(2026, 10, 29))
        return data, fake

    def test_queries_the_export_table_with_parameters(self):
        _, fake = self.fetch([])
        [(sql, job_config)] = fake.queries
        self.assertIn(f"FROM `{TABLE}`", sql)
        self.assertIn("usage_start_time >= TIMESTAMP(@start)", sql)
        self.assertIn("usage_start_time < TIMESTAMP(@end)", sql)
        self.assertIn("UNNEST(credits)", sql)  # net of credits
        self.assertNotIn("@project", sql)
        self.assertEqual(job_config, "job-config")
        self.assertEqual(self.configs, [(date(2026, 10, 1), date(2026, 10, 29), None)])

    def test_runs_the_job_in_the_table_project(self):
        self.fetch([])
        self.assertEqual(self.projects, ["billing-proj"])

    def test_project_filter_is_a_parameter(self):
        data, fake = self.fetch([], project="slack-anomaly-dev")
        self.assertIn("AND project.id = @project", fake.queries[0][0])
        self.assertNotIn("slack-anomaly-dev", fake.queries[0][0])
        self.assertEqual(self.configs[0][2], "slack-anomaly-dev")
        self.assertEqual(data.scope, "slack-anomaly-dev")

    def test_parses_rows_and_currency(self):
        rows = [
            row(date(2026, 10, 27), "Compute Engine", 12.5, "EUR"),
            row(date(2026, 10, 28), "Cloud Run", 0.0, "EUR"),
            row(date(2026, 10, 28), None, 1.5, "EUR"),
        ]
        data, _ = self.fetch(rows)
        self.assertEqual((data.provider, data.scope, data.currency), ("gcp", TABLE, "EUR"))
        self.assertEqual(data.rows, [
            DailyCost(date(2026, 10, 27), "Compute Engine", 12.5),
            DailyCost(date(2026, 10, 28), "Cloud Run", 0.0),
            DailyCost(date(2026, 10, 28), "Other", 1.5),
        ])

    def test_malformed_table_is_rejected_before_querying(self):
        fake = FakeBigQuery([])
        bad = CostSpec("gcp-dev", "gcp", {"billing_table": "p.d.t` WHERE 1=1 --"})
        with self.assertRaises(ValueError):
            self.provider(fake).fetch(bad, date(2026, 10, 1), date(2026, 10, 29))
        self.assertEqual(fake.queries, [])

    def test_client_is_reused_per_project(self):
        fake = FakeBigQuery([])
        provider = self.provider(fake)
        provider.fetch(spec(), date(2026, 10, 1), date(2026, 10, 29))
        provider.fetch(spec(), date(2026, 10, 1), date(2026, 10, 29))
        self.assertEqual(self.projects, ["billing-proj"])

    def test_missing_bigquery_names_the_extra(self):
        with mock.patch.dict("sys.modules", {"google.cloud.bigquery": None, "google.cloud": None}):
            with self.assertRaises(RuntimeError) as ctx:
                GcpCostProvider().fetch(spec(), date(2026, 10, 1), date(2026, 10, 29))
        self.assertIn("anomaly-alerts[gcp]", str(ctx.exception))

    def test_pool_loads_the_gcp_adapter(self):
        self.assertIsInstance(CostProviderPool().get("gcp"), GcpCostProvider)


class BillingTableConfigTests(unittest.TestCase):
    YAML = """
metrics:
  - name: cpu
    provider: aws
    region: us-east-1
    namespace: AWS/EC2
    metric: CPUUtilization
cost:
  accounts:
    - {name: gcp-dev, provider: gcp, billing_table: "%s"}
"""

    def load(self, table):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "config.yaml"
        path.write_text(self.YAML % table)
        return config.load(path)

    def test_valid_table_is_accepted(self):
        self.assertEqual(self.load(TABLE).cost.accounts[0].selector["billing_table"], TABLE)

    def test_malformed_table_is_a_config_error(self):
        for bad in ("billing.table", "p.d.t;DROP", "p.d.t` OR 1=1"):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError) as ctx:
                self.load(bad)
            self.assertIn("project.dataset.table", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
