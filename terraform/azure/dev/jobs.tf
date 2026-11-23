# One Container Apps job per command, each on its own cron schedule, like the Cloud Run jobs
# on GCP. All four run the same image, from GitHub's container registry. They start on a
# public placeholder, and the deploy-azure-dev workflow points them at each commit's image.
# Terraform ignores the image after creation, so deploys and applies never undo each other.
locals {
  # Cron is in UTC only, but the routine reports are scheduled in New York time like the other
  # clouds. So each routine job runs at both UTC hours its local hour can fall on (a New York
  # hour is 4 or 5 hours from UTC, depending on daylight saving), and --local-hours skips the one
  # that is not the right local hour. The minutes are four after AWS, so the clouds fill in
  # their shared message in turn.
  jobs = {
    "anomaly-run" = {
      schedule = "*/5 * * * *"
      args     = ["--config", "inline"]
    }
    "routine-heartbeat" = {
      schedule = "4 4,5,10,11,16,17,22,23 * * *" # local 0, 6, 12 and 18
      args     = ["routine", "--kind", "heartbeat", "--config", "inline", "--local-hours", "0,6,12,18"]
    }
    "routine-digest" = {
      schedule = "4 13,14 * * *" # local 9
      args     = ["routine", "--kind", "digest", "--config", "inline", "--local-hours", "9"]
    }
    "routine-cost" = {
      schedule = "34 13,14 * * *" # local 9, half past
      args     = ["routine", "--kind", "cost", "--config", "inline", "--local-hours", "9"]
    }
  }

  # The webhook URLs are read from Key Vault by the jobs' managed identity, so they never
  # appear in Terraform or in state. The versionless address always means the latest value.
  webhook_secrets = {
    "slack-webhook"         = "SLACK_WEBHOOK_URL"
    "slack-routine-webhook" = "SLACK_ROUTINE_WEBHOOK_URL"
    "slack-bot-token"       = "SLACK_BOT_TOKEN"
  }

  config_b64 = base64encode(templatefile("${path.module}/config.yaml.tftpl", {
    state_url          = "${azurerm_storage_account.app.primary_blob_endpoint}${azurerm_storage_container.app.name}/state/alerts.json"
    state_account_id   = azurerm_storage_account.app.id
    subscription_scope = data.azurerm_subscription.current.id
    # Built from names, not from the jobs, which read this config: that would be a cycle.
    jobs_scope = "${data.azurerm_resource_group.dev.id}/providers/Microsoft.App/jobs"
    # The workspace terraform/azure/org sends the Activity Log to, by resource ID. It is built,
    # not looked up, so this root applies whether or not that one has been applied yet; until
    # it is, the audit metrics show as fetch errors in the heartbeat.
    audit_workspace_id = "${data.azurerm_subscription.current.id}/resourceGroups/${var.audit_resource_group}/providers/Microsoft.OperationalInsights/workspaces/${var.audit_workspace}"
    budget             = var.budget
    slack_channel_id   = var.slack_channel_id
    time_zone          = var.time_zone
  }))
}

resource "azurerm_container_app_environment" "app" {
  # checkov:skip=CKV_AZURE_232: zone redundancy costs more, and a missed 5 minute run is picked up by the next one
  # checkov:skip=CKV_AZURE_233: an internal-only environment needs a network, which costs money and is not needed
  name                       = "cae-slack-anomaly-dev"
  resource_group_name        = local.rg
  location                   = local.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.app.id
  tags                       = local.tags

  # Azure adds this profile to every environment. Saying so here keeps plans free of a
  # difference that would show up for whoever runs them.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

resource "azurerm_container_app_job" "app" {
  # checkov:skip=CKV_AZURE_237: no public ingress exists, because a job has no endpoint
  for_each = local.jobs

  name                         = each.key
  resource_group_name          = local.rg
  location                     = local.location
  container_app_environment_id = azurerm_container_app_environment.app.id
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  # A retry could post the same alert twice. The next run picks up what was missed.
  replica_timeout_in_seconds = 300
  replica_retry_limit        = 0

  schedule_trigger_config {
    cron_expression          = each.value.schedule
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.runtime.id]
  }

  dynamic "secret" {
    for_each = local.webhook_secrets
    content {
      name                = secret.key
      identity            = data.azurerm_user_assigned_identity.runtime.id
      key_vault_secret_id = "${data.azurerm_key_vault.webhooks.vault_uri}secrets/${secret.key}"
    }
  }

  template {
    container {
      name   = "anomaly-alerts"
      image  = "mcr.microsoft.com/k8se/quickstart-jobs:latest"
      cpu    = 0.25
      memory = "0.5Gi"
      args   = each.value.args

      # The runtime identity, for the blob state and the Azure Monitor and cost APIs.
      env {
        name  = "AZURE_CLIENT_ID"
        value = data.azurerm_user_assigned_identity.runtime.client_id
      }

      env {
        name  = "ANOMALY_CONFIG_B64"
        value = local.config_b64
      }

      dynamic "env" {
        for_each = local.webhook_secrets
        content {
          name        = env.value
          secret_name = env.key
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}
