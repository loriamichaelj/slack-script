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

## Slack webhooks

The jobs read the `slack-webhook` and `slack-routine-webhook` secrets, which SEED creates so they survive a DEV teardown. Cloud Run refuses to create a job whose secret has no version, so add both values first; the steps are in the [SEED README](../seed/README.md#slack-webhooks).

## Prerequisites

- SEED applied (identities, state bucket, billing dataset, webhook secrets with values).
- `terraform/gcp/org` applied, or the jobs only see this project's metrics.
- The billing account's Standard usage cost export (it goes to `tensile-runway-511902-q9.shiptrack_billing_export`), with read access for `anomaly-runtime` from `terraform/gcp/org`.

## Tearing down

Destroy is its own manual workflow, `terraform destroy`, and never runs on its own. Start it from the Actions tab, or:

```bash
gh workflow run terraform-destroy.yml --ref dev -f root=dev -f confirm=dev
```

It runs only from `dev`, only when `confirm` matches, and waits for approval in the `CI` environment. The summary shows the destroy plan before anything is removed. It deletes everything in this directory. The webhook secrets and their values live in SEED, so they survive and the next apply works straight away. SEED and the org metrics scope are never touched.
