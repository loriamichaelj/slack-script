# Azure subscription Activity Log

Sends the subscription's Activity Log to the `log-platform-audit` workspace, so the alert job can watch the whole subscription, not only its own jobs. The log records every create, change and delete, plus Defender security alerts and service health notices.

`terraform/azure/dev` looks the workspace up by name and gives its ID to the alert job, which counts the events that matter with KQL queries: role assignments changed, logging changed, network exposure, Key Vault changes, resource groups created or deleted, security alerts and service health. The runtime identity already has Monitoring Reader on the subscription, which covers the queries.

Activity Log data is free to ingest and keep for 90 days, so this costs nothing at this volume. A daily cap of 0.5 GB stops anything else from running up a bill.

Entra ID sign-in and audit logs are not included: exporting them needs an Entra ID P1 license.

Apply this from your machine, not from GitHub: it changes subscription-wide logging, which the GitHub identities are not allowed to do. Apply it before `terraform/azure/dev`, which reads the workspace.

The state goes in the SEED container, so you need blob data access to it. If `terraform init` fails with `AuthorizationPermissionMismatch`, grant it to yourself first (it takes a minute to apply):

```bash
account=$(az storage account show -n slackanomalydevtfstate -g rg-slack-anomaly-seed --query id -o tsv)
az role assignment create --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Storage Blob Data Contributor" --scope "$account/blobServices/default/containers/seed-tfstate"
```

Then:

```bash
cd terraform/azure/org
az login
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
terraform init \
  -backend-config="resource_group_name=rg-slack-anomaly-seed" \
  -backend-config="storage_account_name=slackanomalydevtfstate" \
  -backend-config="container_name=seed-tfstate"
terraform apply
```
