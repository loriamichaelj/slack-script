# GCP seed

Creates what the DEV environment depends on, in project `slack-anomaly-dev`:

- the Terraform state buckets for SEED and DEV
- a Workload Identity pool and GitHub provider (keyless OIDC, no service account keys)
- service accounts: `seed-admin` (SEED), `dev-deployer` (DEV apply and CI destroy), `anomaly-runtime` (the Cloud Run job's identity)
- the Google APIs the project needs

Every resource that supports labels gets `app`, `env`, `managed_by` and `repo` through the provider's `default_labels`. Service accounts and the Workload Identity pool do not support labels.

## Who can use which account

GitHub issues each job a token whose subject names the repo by immutable ID and the environment:

```text
repo:loriamichaelj@165821667/slack-script@1437191668:environment:<NAME>
```

| GitHub environment | Service account | Used for |
| --- | --- | --- |
| `SEED` | `seed-admin` | applying this directory |
| `DEV` | `dev-deployer` | applying `terraform/gcp/dev` |
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

Copy these outputs into GitHub as environment variables (none are secrets):

| Output | Variable | Environments |
| --- | --- | --- |
| `workload_identity_provider` | `GCP_WORKLOAD_IDENTITY_PROVIDER` | SEED, DEV, CI |
| `seed_admin_service_account` | `GCP_SERVICE_ACCOUNT` | SEED |
| `dev_deployer_service_account` | `GCP_SERVICE_ACCOUNT` | DEV, CI |

## Protection against deletion

Both state buckets have `prevent_destroy`, versioning, and public access prevention. To tear everything down locally, remove `prevent_destroy` and set `force_destroy = true` on the buckets first.
