data "azurerm_subscription" "current" {}

# Everything SEED owns is looked up by name.
data "azurerm_resource_group" "dev" {
  name = var.resource_group
}

data "azurerm_user_assigned_identity" "runtime" {
  name                = var.runtime_identity
  resource_group_name = var.seed_resource_group
}

data "azurerm_key_vault" "webhooks" {
  name                = var.key_vault_name
  resource_group_name = var.seed_resource_group
}

locals {
  tags = {
    project    = "anomaly-alerts"
    app        = "anomaly-alerts"
    env        = "dev"
    managed_by = "terraform"
    repo       = "slack-script"
  }

  rg       = data.azurerm_resource_group.dev.name
  location = data.azurerm_resource_group.dev.location
}
