# Azure dev

Runs anomaly-alerts in `Azure subscription 1` (east us) as four Azure Container Apps jobs, each on a cron schedule. They run the same container image as the Cloud Run jobs on GCP and the Lambda on AWS.

| Job | Cron (UTC) | Runs at (New York) | Command |
| --- | --- | --- | --- |
| `anomaly-run` | every 5 minutes | every 5 minutes | anomaly alerts |
| `routine-heartbeat` | `4 4,5,10,11,16,17,22,23 * * *` | 00:04, 06:04, 12:04, 18:04 | `routine --kind heartbeat --local-hours 0,6,12,18` |
| `routine-digest` | `4 13,14 * * *` | 09:04 | `routine --kind digest --local-hours 9` |
| `routine-cost` | `34 13,14 * * *` | 09:34 | `routine --kind cost --local-hours 9` |

Container Apps cron is in UTC only, so each routine job is started at both UTC hours its New York hour can fall on, and `--local-hours` makes the wrong one exit at once without posting. That keeps the reports on the same New York time as AWS and GCP through daylight saving. The routine jobs share one Slack message with the other clouds (`slack.shared_message`, see [examples/slack-app.md](../../../examples/slack-app.md)), so they run a few minutes apart: AWS on the hour, GCP two minutes after, Azure four after. Each adds its own section, and a cloud that has not reported shows as waiting. If the bot token is missing or Slack refuses, the job posts its own message to the webhook instead. A failed run is not retried, because a retry could post the same alert twice: the next schedule picks up what was missed.

## What it creates

- a Container Apps environment on the Consumption plan, and the four jobs (0.25 vCPU, 0.5 GB each), which scale to zero between runs
- a storage account `slackanomalydevapp` with the cooldown state at `app/state/alerts.json`, reached with Entra tokens only
- a Log Analytics workspace for the jobs' logs, capped at 0.1 GB a day and kept for 30 days
- the data role the runtime identity needs on the state container

The jobs run as the `anomaly-runtime` managed identity from SEED, which reads Azure Monitor and Cost Management and the Key Vault secrets. Everything is created in `rg-slack-anomaly-dev`, which SEED made, so a teardown never deletes the group.

## How config and secrets reach the jobs

- **Config:** Terraform renders `config.yaml.tftpl` and sets it as `ANOMALY_CONFIG_B64` on every job, and the jobs run with `--config inline`. A config change is one apply, with no image deploy. Edit the template, not the setting.
- **Webhooks and bot token:** each job has three secrets that point at the Key Vault secrets `slack-webhook`, `slack-routine-webhook` and `slack-bot-token`, read with the managed identity. They become the variables `SLACK_WEBHOOK_URL`, `SLACK_ROUTINE_WEBHOOK_URL` and `SLACK_BOT_TOKEN`, so no URL appears in Terraform or in state.

## How it gets deployed

- `tf apply` (on merge, `DEV` environment) creates the jobs on a public placeholder image.
- `deploy azure dev` builds the `cli` target of the repo's Dockerfile with the Azure libraries, pushes it to GitHub's container registry as `ghcr.io/<owner>/<repo>/anomaly-alerts:sha-<commit>`, and points the four jobs at it. It also runs on any app change. Terraform ignores the image after creation, so the two never undo each other.

### The image must be public

Azure pulls the image without credentials, so the GitHub package has to be public, and a new package starts private. The deploy workflow checks this after each push and warns if it is private. To fix it once: open the package on GitHub (your profile, Packages, `slack-script/anomaly-alerts`), then Package settings, then Change visibility, then Public. The image holds only this open-source code, with no secrets: config and webhooks arrive at run time.

## Prerequisites

- SEED applied, including the vault and the runtime identity.
- The three secrets in the vault: `slack-webhook`, `slack-routine-webhook` and `slack-bot-token`. The steps are in the [SEED README](../seed/README.md#slack-webhooks) and [examples/slack-app.md](../../../examples/slack-app.md).

## Cost

The Container Apps free monthly grant covers this workload many times over. The storage account and the logs cost a few cents, and the log cap keeps a runaway log from costing more. There is no registry bill, because the image is in GitHub's. The config starts with one metric (a check that the 5 minute job is still running) and the daily cost report with a $5 budget. Add metrics deliberately.

## Tearing down

Destroy is its own manual workflow, `tf destroy`, and never runs on its own. Start it from the Actions tab, or:

```bash
gh workflow run tf-destroy.yml --ref dev -f target=azure/dev -f confirm=azure/dev
```

It deletes everything in this directory, including the storage account and its state. The seed's state account, identities and vault survive.
