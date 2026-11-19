# GCP dev

Runs anomaly-alerts in `slack-anomaly-dev` as four Cloud Run jobs on Cloud Scheduler, reading metrics from the whole org through the project's metrics scope.

| Job | Schedule | Command |
| --- | --- | --- |
| `anomaly-run` | every 5 minutes | anomaly alerts |
| `routine-heartbeat` | 00:02, 06:02, 12:02, 18:02 | `routine --kind heartbeat` |
| `routine-digest` | 09:02 | `routine --kind digest` |
| `routine-cost` | 09:32 | `routine --kind cost` |

Times are in `time_zone` (default `America/New_York`). The routine jobs share one Slack message with the other clouds (`slack.shared_message`, see [examples/slack-app.md](../../../examples/slack-app.md)), so they run a few minutes apart: AWS on the hour, GCP two minutes after, Azure four after. Each adds its own section, and a cloud that has not reported shows as waiting. If the bot token is missing or Slack refuses, the job posts its own message to the webhook instead.

Every job mounts the `slack-anomaly-dev-anomaly-app` bucket at `/mnt/app`, which holds `config.yaml` (rendered from `config.yaml.tftpl`) and the cooldown state.

## How it gets deployed

- `tf apply` (on merge, `DEV` environment) creates the jobs with a placeholder image.
- `deploy gcp dev` then builds the image, pushes it to Artifact Registry, and points the jobs at it. It also runs on any app change. Terraform ignores the image, so the two never undo each other.

## Slack webhooks

The jobs read the `slack-webhook`, `slack-routine-webhook` and `slack-bot-token` secrets, which SEED creates so they survive a DEV teardown. Cloud Run refuses to create a job whose secret has no version, so add every value first; the steps are in the [SEED README](../seed/README.md#slack-webhooks) and [examples/slack-app.md](../../../examples/slack-app.md).

## Prerequisites

- SEED applied (identities, state bucket, billing dataset, webhook secrets with values).
- `terraform/gcp/org` applied, or the jobs only see this project's metrics.
- The billing account's Standard usage cost export (it goes to `tensile-runway-511902-q9.shiptrack_billing_export`), with read access for `anomaly-runtime` from `terraform/gcp/org`.

## Tearing down

Destroy is its own manual workflow, `tf destroy`, and never runs on its own. Start it from the Actions tab, or:

```bash
gh workflow run tf-destroy.yml --ref dev -f target=gcp/dev -f confirm=gcp/dev
```

It runs only from `dev`, only when `confirm` matches, and waits for approval in the `CI` environment. The summary shows the destroy plan before anything is removed. It deletes everything in this directory. The webhook secrets and their values live in SEED, so they survive and the next apply works straight away. SEED and the org metrics scope are never touched.
