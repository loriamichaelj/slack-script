# Run on GCP with Cloud Scheduler

Run the tool as a Cloud Run job and start it from Cloud Scheduler.

## Image and job

```bash
gcloud run jobs deploy anomaly-alerts \
  --source . \
  --region us-central1 \
  --service-account anomaly-alerts@my-project.iam.gserviceaccount.com \
  --set-secrets SLACK_WEBHOOK_URL=slack-webhook:latest \
  --args="--config,config/config.yaml"
```

Use the same Dockerfile as in [eventbridge.md](eventbridge.md), installing `.[gcp]` instead of `.[aws]`.

## Schedule

```bash
gcloud scheduler jobs create http anomaly-alerts \
  --location us-central1 \
  --schedule "*/5 * * * *" \
  --uri "https://run.googleapis.com/v2/projects/my-project/locations/us-central1/jobs/anomaly-alerts:run" \
  --http-method POST \
  --oauth-service-account-email scheduler@my-project.iam.gserviceaccount.com
```

The scheduler service account needs `roles/run.invoker` on the job.

## Permissions and secrets

- Job service account: `roles/monitoring.viewer`, plus `roles/secretmanager.secretAccessor` on the webhook secret. For the cost report, add `roles/bigquery.jobUser` on the billing project and `roles/bigquery.dataViewer` on the billing export dataset.
- Credentials come from Application Default Credentials, so no key files are needed.

## State

A Cloud Run job has no persistent disk, so the cooldown resets every run. Mount a Cloud Storage bucket (Cloud Storage FUSE volume) and point `state.path` at it:

```yaml
state:
  path: /mnt/state/alerts.json
```

## Routine reports

Deploy one more Cloud Run job per report from the same source, changing only the arguments, and schedule each the same way:

```bash
gcloud run jobs deploy anomaly-alerts-digest \
  --source . \
  --region us-central1 \
  --service-account anomaly-alerts@my-project.iam.gserviceaccount.com \
  --set-secrets SLACK_ROUTINE_WEBHOOK_URL=slack-routine-webhook:latest \
  --args="routine,--kind,digest,--config,config/config.yaml"
```

Suggested schedules: heartbeat `0 */6 * * *`, digest `0 9 * * *`, cost `30 9 * * *`. The GCP billing export lags, so set `cost.lag_days: 2` if the cost report often shows "no cost data yet".

## Azure

On Azure, the equivalent is a Container Apps job with a cron trigger and a managed identity holding the Monitoring Reader role. Add one job per routine report with its own cron expression, and give the identity Cost Management Reader on the subscription for the cost report.
