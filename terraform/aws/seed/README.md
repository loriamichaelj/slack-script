# AWS seed

Creates what the DEV environment depends on, in account `370767313925` (us-east-1):

- the Terraform state buckets for SEED and DEV (versioned, encrypted, TLS-only)
- a GitHub OIDC provider (keyless, no access keys)
- roles: `seed-admin` (SEED), `dev-deployer` (DEV apply and CI destroy), `tf-planner` (CI plan, read-only), `anomaly-runtime` (the Lambda functions' identity)
- the `anomaly-alerts` ECR repository for the Lambda container image, with a lifecycle rule that keeps the last 5 images
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

The `tf plan` and `tf apply` workflows take over from here. They sign in through the OIDC provider as the roles `tf-planner` and `seed-admin`, and build each role's ARN from its name, so no access keys or role ARNs are stored in GitHub. Set one repository variable to turn them on (the workflows skip AWS steps until it is set):

```bash
gh variable set AWS_ACCOUNT_ID --body 370767313925
```

After that, any change to `terraform/aws/seed` goes through a pull request (plan, in the `CI` environment) and a merge to `dev` (apply, in the `SEED` environment, which needs a reviewer).

Then add each webhook value by hand, so it never enters Terraform state. They live in free SSM Parameter Store SecureStrings under `/anomaly-alerts`, which the runtime role may read. Terraform does not manage them, because it would read the value back into its state file. Run this from your own terminal, so the URL never appears anywhere else:

```bash
read -rs URL   # paste the incoming webhook URL, press Enter
aws ssm put-parameter --name /anomaly-alerts/slack-webhook --type SecureString --value "$URL" --overwrite
read -rs URL
aws ssm put-parameter --name /anomaly-alerts/slack-routine-webhook --type SecureString --value "$URL" --overwrite
unset URL
```

The Slack bot token for the shared routine message (see [examples/slack-app.md](../../../examples/slack-app.md)) goes in the same place. The runtime role already reads everything under `/anomaly-alerts`:

```bash
read -rs TOKEN   # paste the bot token (starts with xoxb-), press Enter
aws ssm put-parameter --name /anomaly-alerts/slack-bot-token --type SecureString --value "$TOKEN" --overwrite
unset TOKEN
```

The older Secrets Manager secrets below are what the Lambda reads until it is switched to these, and then they can be deleted. Each one costs $0.40 a month.

To add a value to a Secrets Manager secret instead:

```bash
aws secretsmanager put-secret-value --secret-id slack-webhook --secret-string 'https://hooks.slack.com/...'
aws secretsmanager put-secret-value --secret-id slack-routine-webhook --secret-string 'https://hooks.slack.com/...'
```

## Cost

State buckets are pennies a month. The ECR repository costs a few cents for the images it keeps. Each secret costs $0.40 a month. The OIDC provider and roles are free.
