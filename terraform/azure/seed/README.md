# Azure seed

Creates what the DEV environment depends on, in the `Azure subscription 1` subscription (east us):

- a storage account with two containers for the Terraform state of SEED and DEV (versioned, TLS 1.2, no shared keys: every request needs an Entra token)
- Entra app registrations with federated credentials for GitHub (keyless OIDC, no client secrets): `tf-planner`, `seed-admin` and `dev-deployer`
- the resource groups `rg-slack-anomaly-seed` (state, vault, runtime identity) and `rg-slack-anomaly-dev` (empty, for DEV to deploy into)
- the `anomaly-runtime` managed identity that the Function runs as
- a Key Vault for the Slack webhook secrets, with no secrets in it (see below)
- the resource providers the app needs, registered once here because DEV cannot do it

Every resource that supports tags gets `project`, `app`, `env`, `managed_by` and `repo`. No tenant or subscription IDs are stored in the repo: they come from `ARM_TENANT_ID` and `ARM_SUBSCRIPTION_ID` (or your `az login`) and from GitHub variables.

## Who can use which identity

GitHub issues each job a token whose subject names the repo by immutable ID and the environment:

```text
repo:loriamichaelj@165821667/slack-script@1437191668:environment:<NAME>
```

| GitHub environment | Identity | Rights | Used for |
| --- | --- | --- | --- |
| `SEED` | `seed-admin` | Owner on the subscription | applying this directory |
| `DEV` | `dev-deployer` | Contributor and RBAC Administrator on `rg-slack-anomaly-dev` only, and Managed Identity Operator on the one runtime identity | applying `terraform/azure/dev` |
| `CI` | `tf-planner` | Reader on the subscription, read of the directory's apps, blob reader on the state, and listing job secrets in the dev group | planning pull requests |
| `CI` | `dev-deployer` | as above | destroying `terraform/azure/dev` |

Azure roles attach to a principal, so each identity is its own app registration, and each trusts only its own environments. `seed-admin` has Owner because this directory creates role assignments.

## First apply (bootstrap)

The state account is created by this same configuration, so the first apply uses local state and then moves it into the account it created. This runs on your machine, once, signed in with `az login` as an Owner of the subscription who can also create app registrations.

```bash
cd terraform/azure/seed
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
export ARM_TENANT_ID=$(az account show --query tenantId -o tsv)

# 1. Use local state for the first apply.
printf 'terraform {\n  backend "local" {}\n}\n' > backend_override.tf
terraform init
terraform apply

# 2. Let yourself write to the state container, then move the state in.
account=$(az storage account show -n slackanomalydevtfstate -g rg-slack-anomaly-seed --query id -o tsv)
az role assignment create --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Storage Blob Data Contributor" --scope "$account/blobServices/default/containers/seed-tfstate"
# Role assignments take a minute to apply.

rm backend_override.tf
terraform init -migrate-state \
  -backend-config="resource_group_name=rg-slack-anomaly-seed" \
  -backend-config="storage_account_name=slackanomalydevtfstate" \
  -backend-config="container_name=seed-tfstate"
```

Answer `yes` to the migration prompt, then delete the local `terraform.tfstate` files. You can remove your own blob role afterwards: the workflows use `seed-admin`.

## After the apply

The workflows sign in with OIDC, so they need the IDs of the three identities. Set these repository variables (none are secrets):

| Output | Variable |
| --- | --- |
| `tenant_id` | `AZURE_TENANT_ID` |
| `subscription_id` | `AZURE_SUBSCRIPTION_ID` |
| `client_ids["tf-planner"]` | `AZURE_CLIENT_ID_TF_PLANNER` |
| `client_ids["seed-admin"]` | `AZURE_CLIENT_ID_SEED_ADMIN` |
| `client_ids["dev-deployer"]` | `AZURE_CLIENT_ID_DEV_DEPLOYER` |

## Slack webhooks

The vault exists but holds no secrets, so no webhook URL ever lands in Terraform state. Give yourself the Secrets Officer role once, then add each value from your own terminal. This copies the AWS ones without printing them:

```bash
az role assignment create --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Key Vault Secrets Officer" --scope "$(az keyvault show -n kv-slack-anomaly-dev -g rg-slack-anomaly-seed --query id -o tsv)"

for s in slack-webhook slack-routine-webhook; do
  aws secretsmanager get-secret-value --secret-id "$s" --query SecretString --output text \
    | az keyvault secret set --vault-name kv-slack-anomaly-dev --name "$s" --file /dev/stdin --encoding utf-8 --query id -o tsv
done
```

The Slack bot token for the shared routine message (see [examples/slack-app.md](../../../examples/slack-app.md)) goes in the same vault. The runtime identity already reads every secret in it. With the Secrets Officer role from above:

```bash
read -rs TOKEN   # paste the bot token (starts with xoxb-), press Enter
printf %s "$TOKEN" | az keyvault secret set --vault-name kv-slack-anomaly-dev --name slack-bot-token --file /dev/stdin --encoding utf-8 --query id -o tsv
unset TOKEN
```

## Cost

The state account and the vault cost a few cents a month. The identities, resource groups and role assignments are free.
