# The subscription's Activity Log (every create, change and delete, plus security alerts and
# service health) goes to its own workspace, where the alert job counts the events that matter
# with KQL queries (see terraform/azure/dev/config.yaml.tftpl). Activity Log data is free to
# ingest and keep for 90 days, so this costs nothing at this volume.

data "azurerm_subscription" "current" {}

locals {
  tags = {
    project    = "anomaly-alerts"
    app        = "anomaly-alerts"
    env        = "org"
    managed_by = "terraform"
    repo       = var.github_repo
  }

  activity_log_categories = [
    "Administrative", "Security", "ServiceHealth", "Alert", "Recommendation", "Policy", "Autoscale", "ResourceHealth",
  ]
}

resource "azurerm_resource_group" "audit" {
  name     = var.resource_group
  location = var.location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "audit" {
  name                = var.workspace_name
  location            = azurerm_resource_group.audit.location
  resource_group_name = azurerm_resource_group.audit.name
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_days
  # Activity Log data is free, so this cap only stops something else from running up a bill.
  daily_quota_gb = 0.5
  tags           = local.tags
}

resource "azurerm_monitor_diagnostic_setting" "activity_log" {
  name                       = "platform-audit"
  target_resource_id         = data.azurerm_subscription.current.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.audit.id

  dynamic "enabled_log" {
    for_each = local.activity_log_categories
    content {
      category = enabled_log.value
    }
  }
}
