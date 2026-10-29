# Multi-Cloud Anomaly Alerts

A Python tool that pulls metrics from AWS CloudWatch, Azure Monitor and GCP Cloud Monitoring and flags anomalies using simple statistical methods. Each anomaly is posted to Slack as a rich alert with the observed value, the baseline, and recommended next steps. It runs as a short-lived job on any scheduler and is configured with a single YAML file.

## Quick start

```bash
pip install -e ".[all]"                # or .[aws], .[azure], .[gcp]
cp config/config.example.yaml config/config.yaml
cp .env.example .env                   # set SLACK_WEBHOOK_URL
anomaly-alerts --config config/config.yaml --dry-run
```

Options: `--dry-run` prints payloads without posting, `--only aws|azure|gcp` runs one cloud, `--verbose` turns on debug logging. Exit codes: `0` ok, `1` a fetch or post failed, `2` bad config.

Routine reports post on a schedule whether or not anything is wrong. `anomaly-alerts routine --config config/config.yaml` posts a heartbeat: how many metrics were fetched, how many anomalies exist right now, and which metrics could not be fetched. `--kind digest` posts a health digest instead: one line per metric with its latest value against the baseline, worst first, including metrics still building history. Give it its own Slack channel with `routine_webhook_env`; without one it uses the main webhook. Schedule it separately from the anomaly run, for example once a day.

Detectors: `mad` (default), `zscore`, `ewma`, `iqr`. Recommended actions live in `config/actions.yaml`.

Scheduler setups: [cron](examples/cron.md), [AWS EventBridge](examples/eventbridge.md), [GCP Cloud Scheduler and Azure](examples/cloud-scheduler.md).

## Architecture

The tool is a short-lived batch job. It has no server, no database and no long-running agent: a scheduler starts it, it does one pass over the configured metrics, posts any new alerts to Slack, and exits. The only thing it keeps between runs is a small JSON file that records which alerts were already sent.

Only the provider adapters know which cloud a metric came from. Each one turns its SDK response into the same `Series` (timestamped values, oldest first), and every stage after that works on `Series` alone. Adding a cloud means adding one adapter.

```mermaid
flowchart LR
    subgraph Providers
        A[AWS CloudWatch]
        B[Azure Monitor]
        C[GCP Monitoring]
    end
    A --> D[Normalize and detect]
    B --> D
    C --> D
    D --> E[Dedup and cooldown]
    E --> F[Recommended actions]
    F --> G[Slack alert]

    classDef step fill:#e8f0fe,stroke:#4a6fa5,stroke-width:1.5px,color:#111111
    classDef out fill:#fff4d6,stroke:#b58900,stroke-width:2px,color:#111111
    class A,B,C,D,E,F step
    class G out
    style Providers fill:#f6f8fa,stroke:#57606a,color:#111111
```

### How a run works

1. **Load config.** The YAML file lists the metrics to watch. The Slack webhook URL is read from an environment variable and is never stored in the file.
2. **Fetch.** For each metric, the matching provider (`boto3`, `azure-monitor-query` or `google-cloud-monitoring`) pulls the lookback window using the runner's own cloud credentials. The newest period is skipped because cloud metrics arrive late. A failed fetch is logged and does not stop the other metrics.
3. **Detect.** The chosen detector scores the latest points against a baseline built from earlier points. Four are available: modified z-score (`mad`, the default), `zscore`, `ewma` and `iqr`.
4. **Guard.** A score only counts as an anomaly if it passes every guard: enough baseline history, a sustained breach across consecutive points, a deviation larger than the metric's `min_abs_change`, and a direction the metric alerts on (spike, drop or both). A flat baseline falls back to a percentage-change rule.
5. **Dedup.** Each anomaly has a fingerprint (cloud, account, resource, metric, direction). A fingerprint stays silent during the cooldown, unless the alert escalated from warning to critical.
6. **Enrich.** A rule table in `config/actions.yaml` matches the metric category and direction to ordered next steps. With no match, the alert gets a generic step.
7. **Post.** One Slack Block Kit message per anomaly, critical first, up to `max_alerts_per_run`. Anything beyond the cap becomes a single "N more suppressed" notice.

Severity is `warning` when the score passes the detector threshold, and `critical` at twice the threshold or when the breach lasts twice the minimum window.

### Components

| Module | Responsibility |
| --- | --- |
| `cli.py` | Parse arguments, wire the pieces together, set the exit code |
| `config.py` | Load and validate the YAML config |
| `models.py` | `MetricSpec`, `Series`, `Anomaly` |
| `providers/` | One adapter per cloud behind a shared `fetch` interface |
| `detectors/` | The four detectors and the shared guards |
| `state.py` | Dedup and cooldown file |
| `actions.py` | Match an anomaly to recommended steps |
| `slack/` | Block Kit builder and webhook client |
| `pipeline.py` | Runs the stages above in order |
