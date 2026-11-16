# AWS dev

Runs anomaly-alerts in account `370767313925` (us-east-1) as one Lambda function started by four EventBridge Scheduler schedules.

| Schedule | When | Event sent to the Lambda |
| --- | --- | --- |
| `anomaly-run` | every 5 minutes | `{"command": "run"}` |
| `routine-heartbeat` | every 6 hours | `{"command": "routine", "kind": "heartbeat"}` |
| `routine-digest` | 09:00 | `{"command": "routine", "kind": "digest"}` |
| `routine-cost` | 09:30 | `{"command": "routine", "kind": "cost"}` |

Times are in `time_zone` (default `America/New_York`). A failed run is not retried, because a retry could post the same alert twice: the next schedule picks up what was missed.

## What it creates

- the `anomaly-alerts` Lambda (Python 3.12, 256 MB, 5 minute timeout) and its log group (14 days)
- the app bucket `slack-anomaly-dev-anomaly-app`, with `config.yaml` (rendered from `config.yaml.tftpl`) and the cooldown state at `state/alerts.json`
- the four schedules, and the `slack-anomaly-scheduler` role they start the Lambda as (it may only invoke that function)

The Lambda runs as `anomaly-runtime`, and the webhook secrets come from SEED. The function reads the config from S3 and the webhook URLs from Secrets Manager at the start of each run, so editing the template changes metrics without a code deploy.

## How it gets deployed

- `tf apply` (on merge, `DEV` environment) creates the function with a placeholder handler.
- `deploy aws dev` then builds the zip (`scripts/build-lambda.sh`) and uploads it. It also runs on any app change. Terraform ignores the code after creation, so the two never undo each other.

## Prerequisites

- SEED applied, including the app-bucket access on `anomaly-runtime` and the scheduler role permission on `dev-deployer`.
- Both webhook secrets have a value. Add them from your own terminal so the URLs never pass through anything else:

```bash
read -rs URL   # paste the incoming webhook URL, press Enter
aws secretsmanager put-secret-value --secret-id slack-webhook --secret-string "$URL"
read -rs URL
aws secretsmanager put-secret-value --secret-id slack-routine-webhook --secret-string "$URL"
unset URL
```

## Cost

Lambda, EventBridge Scheduler and the bucket fit well inside the free tier. The real cost is metric reads: about $0.09 a month for each metric at the 5 minute schedule, plus $0.30 a month for the daily cost report. The config starts with one metric (the function's own errors), so expect under $1 a month. Add metrics deliberately.

## Tearing down

Destroy is its own manual workflow, `tf destroy`, and never runs on its own. Start it from the Actions tab, or:

```bash
gh workflow run tf-destroy.yml --ref dev -f target=aws/dev -f confirm=aws/dev
```

It deletes everything in this directory, including the bucket and its state object. The state buckets, roles and webhook secrets live in SEED and survive.
