# Multi-Cloud Anomaly Alerts

Watches metrics on AWS, Azure and GCP and posts a Slack alert when one looks wrong. It runs on a schedule, makes one pass, and exits.

## Quick start

```bash
pip install -e ".[all]"                          # or .[aws], .[azure], .[gcp]
cp config/config.example.yaml config/config.yaml # list your metrics
cp .env.example .env                             # set SLACK_WEBHOOK_URL
anomaly-alerts --config config/config.yaml --dry-run
```

Remove `--dry-run` to post to Slack.

## Commands

| Command | Does |
| --- | --- |
| `anomaly-alerts --config FILE` | Alert on anomalies |
| `anomaly-alerts routine --config FILE` | Post a heartbeat: metrics checked, anomalies, failures |
| `... routine --kind digest` | Post every metric's latest value against its baseline |
| `... routine --kind cost` | Post yesterday's spend per account (AWS now; Azure and GCP coming) |

Options: `--dry-run` prints instead of posting, `--only aws|azure|gcp` runs one cloud, `--verbose` adds debug logs.

Exit codes: `0` ok, `1` a fetch or post failed, `2` bad config.

## How it works

Fetch each metric, then detect anomalies (`mad` by default, or `zscore`, `ewma`, `iqr`). Skip repeats during a cooldown, add recommended steps from `config/actions.yaml`, and post to Slack.

Credentials come from each cloud SDK's usual login, and read-only access is enough. The cost report on AWS also needs `ce:GetCostAndUsage`.

## Scheduling

[cron](examples/cron.md) · [AWS EventBridge](examples/eventbridge.md) · [GCP Cloud Scheduler and Azure](examples/cloud-scheduler.md)
