# GCP dev

Runs anomaly-alerts in `slack-anomaly-dev` as four Cloud Run jobs on Cloud Scheduler, reading metrics from the whole org through the project's metrics scope.

| Job | Schedule | Command |
| --- | --- | --- |
| `anomaly-run` | every 5 minutes | anomaly alerts |
| `routine-heartbeat` | every 6 hours | `routine --kind heartbeat` |
| `routine-digest` | 09:00 | `routine --kind digest` |
| `routine-cost` | 09:30 | `routine --kind cost` |

Times are in `time_zone` (default `America/New_York`). Every job mounts the `slack-anomaly-dev-anomaly-app` bucket at `/mnt/app`, which holds `config.yaml` (rendered from `config.yaml.tftpl`) and the cooldown state.

## How it gets deployed

- `terraform apply` (on merge, `DEV` environment) creates the jobs with a placeholder image.
- `deploy dev` then builds the image, pushes it to Artifact Registry, and points the jobs at it. It also runs on any app change. Terraform ignores the image, so the two never undo each other.

## First time: add the Slack webhooks

Terraform creates the two secrets but never their values, so no webhook URL ends up in state. Until each has a version, the jobs fail to start. After the first apply:

```bash
printf %s "https://hooks.slack.com/services/..." | gcloud secrets versions add slack-webhook --data-file=- --project slack-anomaly-dev
printf %s "https://hooks.slack.com/services/..." | gcloud secrets versions add slack-routine-webhook --data-file=- --project slack-anomaly-dev
```

Use the same URL for both to send everything to one channel.

## Prerequisites

- SEED applied (identities, state bucket, billing dataset).
- `terraform/gcp/org` applied, or the jobs only see this project's metrics.
- Billing export turned on, or the cost report shows "could not fetch costs".
