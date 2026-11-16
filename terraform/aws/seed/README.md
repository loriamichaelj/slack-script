# AWS seed

Creates what the DEV environment depends on, in account `370767313925` (us-east-1):

- the Terraform state buckets for SEED and DEV (versioned, encrypted, TLS-only)
- a GitHub OIDC provider (keyless, no access keys)
- roles: `seed-admin` (SEED), `dev-deployer` (DEV apply and CI destroy), `tf-planner` (CI plan, read-only), `anomaly-runtime` (the Lambda functions' identity)
- the `slack-webhook` and `slack-routine-webhook` secrets, without values (see below)

Every resource that supports tags gets `project`, `app`, `env`, `managed_by` and `repo` through the provider's `default_tags`.

## Who can use which role

GitHub issues each job a token whose subject names the repo by immutable ID and the environment:

```text
repo:loriamichaelj@165821667/slack-script@1437191668:environment:<NAME>
```

| GitHub environment | Role | Used for |
| --- | --- | --- |
| `SEED` | `seed-admin` | applying this directory |
| `DEV` | `dev-deployer` | applying `terraform/aws/dev` |
| `CI` | `tf-planner` | planning pull requests (read-only) |
| `CI` | `dev-deployer` | destroying `terraform/aws/dev` |

Each role's trust policy names its exact subjects, so only those environments can assume it. The environment's own protection rules (reviewer, `dev` branch only) decide whether a job can start.

`seed-admin` holds `AdministratorAccess` because this directory creates IAM. `dev-deployer` is limited to Lambda, EventBridge, logs, buckets named `slack-anomaly-dev-*`, and IAM roles and policies named `slack-anomaly-*`.

## First apply (bootstrap)

The state buckets are created by this same configuration, so the first apply uses local state and then moves it into the bucket it created. This runs on your machine, once.

```bash
cd terraform/aws/seed
export AWS_PROFILE=mikejloria                  # after: aws sso login --profile mikejloria

# 1. Use local state for the first apply.
printf 'terraform {\n  backend "local" {}\n}\n' > backend_override.tf
terraform init
terraform apply

# 2. Move the state into the bucket just created.
rm backend_override.tf
terraform init -migrate-state -backend-config="bucket=slack-anomaly-dev-seed-tfstate"
```

Answer `yes` to the migration prompt, then delete the local `terraform.tfstate` files. Later runs only need `terraform init -backend-config="bucket=slack-anomaly-dev-seed-tfstate"`.

## After the apply

Copy these outputs into GitHub as variables (none are secrets):

| Output | Variable | Environments |
| --- | --- | --- |
| `seed_admin_role_arn` | `AWS_ROLE_ARN` | SEED |
| `dev_deployer_role_arn` | `AWS_ROLE_ARN` | DEV and CI |
| `tf_planner_role_arn` | `AWS_PLAN_ROLE_ARN` | CI |

Then add each webhook value by hand, so it never enters Terraform state:

```bash
aws secretsmanager put-secret-value --secret-id slack-webhook --secret-string 'https://hooks.slack.com/...'
aws secretsmanager put-secret-value --secret-id slack-routine-webhook --secret-string 'https://hooks.slack.com/...'
```

## Cost

State buckets are pennies a month. Each secret costs $0.40 a month. The OIDC provider and roles are free.
