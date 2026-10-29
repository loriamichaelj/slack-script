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

## How a run works

1. Read the config. The Slack webhook URL comes from an environment variable, never the file.
2. Fetch each metric. If one fails, it is logged and the rest carry on.
3. Compare the newest points to earlier ones using a detector: `mad` (default), `zscore`, `ewma` or `iqr`.
4. Call it an anomaly only if there is enough history, it lasts several points, the change is big enough, and it goes in a direction the metric cares about.
5. Skip alerts already sent within the cooldown, unless they got worse.
6. Add recommended next steps from `config/actions.yaml`.
7. Post to Slack, most severe first, up to a limit per run.

Credentials come from each cloud SDK's usual login, and read-only access is enough. The cost report on AWS also needs `ce:GetCostAndUsage`.

## Scheduling

[cron](examples/cron.md) · [AWS EventBridge](examples/eventbridge.md) · [GCP Cloud Scheduler and Azure](examples/cloud-scheduler.md)
