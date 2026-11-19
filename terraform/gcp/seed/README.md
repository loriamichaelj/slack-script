# GCP seed

Creates what the DEV environment depends on, in project `slack-anomaly-dev`:

- the Terraform state buckets for SEED and DEV
- a Workload Identity pool and GitHub provider (keyless OIDC, no service account keys)
- service accounts: `seed-admin` (SEED), `dev-deployer` (DEV apply and CI destroy), `tf-planner` (CI plan, read-only), `anomaly-runtime` (the Cloud Run job's identity)
- the Google APIs the project needs
- the `billing_export` BigQuery dataset for the cost report, readable by `anomaly-runtime`
- the `slack-webhook` and `slack-routine-webhook` secrets, without values (see below)

Every resource that supports labels gets `project`, `app`, `env`, `managed_by` and `repo` through the provider's `default_labels`. Service accounts and the Workload Identity pool do not support labels.

## Who can use which account

GitHub issues each job a token whose subject names the repo by immutable ID and the environment:

```text
repo:loriamichaelj@165821667/slack-script@1437191668:environment:<NAME>
```

| GitHub environment | Service account | Used for |
| --- | --- | --- |
| `SEED` | `seed-admin` | applying this directory |
| `DEV` | `dev-deployer` | applying `terraform/gcp/dev` |
| `CI` | `tf-planner` | planning pull requests (read-only) |
| `CI` | `dev-deployer` | destroying `terraform/gcp/dev` |

The provider only accepts tokens from owner ID `165821667` and repo ID `1437191668`. Each environment's own protection rules (reviewer, `dev` branch only) decide whether a job can start.

Known trade-off: `dev-deployer` holds project-level `roles/storage.admin` so it can create the DEV app-state bucket, which also lets it reach the SEED state bucket. The SEED state holds no secrets (account emails, pool names), but a deployer could alter it.

## First apply (bootstrap)

The state buckets are created by this same configuration, so the first apply uses local state and then moves it into the bucket it created. This runs on your machine, once.

```bash
cd terraform/gcp/seed
gcloud auth application-default login          # as an account that can administer the project

# 1. Use local state for the first apply.
printf 'terraform {\n  backend "local" {}\n}\n' > backend_override.tf
terraform init
terraform apply

# 2. Move the state into the bucket just created.
rm backend_override.tf
terraform init -migrate-state -backend-config="bucket=slack-anomaly-dev-seed-tfstate"
```

Answer `yes` to the migration prompt, then delete the local `terraform.tfstate` files. `backend_override.tf` is git-ignored. Later runs only need `terraform init -backend-config="bucket=slack-anomaly-dev-seed-tfstate"`.

## After the apply

Set one repository variable, from the `workload_identity_provider` output. The `tf-*` and `deploy-*` workflows skip GCP steps until it is set:

```bash
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --body "$(terraform output -raw workload_identity_provider)"
```

The workflows build each service account's address from its name (`tf-planner`, `seed-admin`, `dev-deployer`) and the project, so no per-environment variables are needed. The older `GCP_SERVICE_ACCOUNT` and `GCP_PLAN_SERVICE_ACCOUNT` variables are unused and can be deleted.

## Slack webhooks

The two secrets live here so a DEV teardown keeps them. Terraform never stores their values; add each once from your own terminal, never pasting the URL anywhere else:

```bash
read -rs URL   # paste the incoming webhook URL, press Enter
printf %s "$URL" | gcloud secrets versions add slack-webhook --data-file=- --project slack-anomaly-dev
printf %s "$URL" | gcloud secrets versions add slack-routine-webhook --data-file=- --project slack-anomaly-dev
unset URL
```

Use the same URL for both to send everything to one channel. The DEV jobs cannot be created until both have a version.

## Slack bot token

The `slack-bot-token` secret is for the shared routine message (see [examples/slack-app.md](../../../examples/slack-app.md)). Add the token once from your own terminal:

```bash
read -rs TOKEN   # paste the bot token (starts with xoxb-), press Enter
printf %s "$TOKEN" | gcloud secrets versions add slack-bot-token --data-file=- --project slack-anomaly-dev
unset TOKEN
```

## Billing export and org metrics

Two one-time steps after the first apply:

1. **Billing export.** The billing account's Standard usage cost export already goes to `tensile-runway-511902-q9.shiptrack_billing_export`, and a billing account has only one such export, so the cost report reads that table (read access comes from `../org`). The `billing_export` dataset here stays empty unless the export is moved.
2. **Org metrics.** Apply [`../org`](../org/README.md) so the job can read metrics from every project in the org.

## Protection against deletion

Both state buckets and the billing dataset have `prevent_destroy`. The buckets also have versioning and public access prevention. To tear everything down locally, remove `prevent_destroy` and set `force_destroy = true` on the buckets first.
