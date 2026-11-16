# Where the jobs' logs and failures are kept, so they can be searched. Ingestion is capped
# per day, and the first 5 GB a month is free.
resource "azurerm_log_analytics_workspace" "app" {
  # checkov:skip=CKV_AZURE_267: the workspace is reached over the public endpoint, and every request needs an Entra token
  name                = "log-slack-anomaly-dev"
  resource_group_name = local.rg
  location            = local.location
  tags                = local.tags

  sku               = "PerGB2018"
  retention_in_days = var.log_retention_days
  daily_quota_gb    = var.daily_log_cap_gb
}
