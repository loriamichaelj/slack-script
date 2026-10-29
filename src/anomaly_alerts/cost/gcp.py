"""GCP spend from the Cloud Billing export to BigQuery, grouped by service.

The export must be turned on in the console first, and it takes about a day to fill.
Costs are net of credits (free tier, discounts) and dated by usage start, in UTC.
"""

from __future__ import annotations

import re
from datetime import date

from ..models import CostData, CostSpec, DailyCost

# Table names cannot be query parameters, so they are checked before use.
TABLE_PATTERN = re.compile(r"^[A-Za-z0-9-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
MAX_BYTES_BILLED = 10 * 1024**3  # stop a mistaken query from scanning a huge table

_QUERY = """
SELECT
  DATE(usage_start_time) AS day,
  service.description AS service,
  currency,
  SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) AS c), 0)) AS amount
FROM `{table}`
WHERE usage_start_time >= TIMESTAMP(@start)
  AND usage_start_time < TIMESTAMP(@end)
  -- Prune partitions; rows can land up to a few days after their usage.
  AND DATE(_PARTITIONTIME) >= DATE_SUB(@start, INTERVAL 1 DAY)
  {project_filter}
GROUP BY day, service, currency
"""


def _default_factory(project: str):
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is not installed; run: pip install 'anomaly-alerts[gcp]'"
        ) from exc
    return bigquery.Client(project=project)


def _job_config(start: date, end: date, project: str | None):
    from google.cloud import bigquery

    params = [
        bigquery.ScalarQueryParameter("start", "DATE", start),
        bigquery.ScalarQueryParameter("end", "DATE", end),
    ]
    if project:
        params.append(bigquery.ScalarQueryParameter("project", "STRING", project))
    return bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=MAX_BYTES_BILLED)


class GcpCostProvider:
    def __init__(self, client_factory=_default_factory, job_config=_job_config):
        self._factory = client_factory
        self._job_config = job_config
        self._clients: dict[str, object] = {}

    def _client(self, project: str):
        if project not in self._clients:
            self._clients[project] = self._factory(project)
        return self._clients[project]

    def fetch(self, spec: CostSpec, start: date, end: date) -> CostData:
        table = str(spec.selector["billing_table"])
        if not TABLE_PATTERN.match(table):
            raise ValueError("billing_table must look like project.dataset.table")
        project = spec.selector.get("project")
        sql = _QUERY.format(
            table=table, project_filter="AND project.id = @project" if project else ""
        )
        # Run the query in job_project when set, so the reader needs only read access to
        # an export table that lives in another project. Otherwise use the table's project.
        client = self._client(str(spec.selector.get("job_project") or table.split(".")[0]))
        result = client.query(sql, job_config=self._job_config(start, end, project)).result()

        rows: list[DailyCost] = []
        currency = "USD"
        for row in result:
            currency = row["currency"] or currency
            rows.append(DailyCost(row["day"], row["service"] or "Other", float(row["amount"])))
        return CostData(provider="gcp", scope=project or table, currency=currency, rows=rows)
