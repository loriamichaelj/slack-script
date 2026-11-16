data "azurerm_client_config" "current" {}
data "azurerm_subscription" "current" {}
data "azuread_client_config" "current" {}

locals {
  tags = merge({
    project    = "anomaly-alerts"
    app        = "anomaly-alerts"
    env        = "seed"
    managed_by = "terraform"
    repo       = var.github_repo
  }, var.tags)

  subscription_scope = data.azurerm_subscription.current.id

  # Subject prefix GitHub puts in every OIDC token for this repo, by immutable ID.
  subject_prefix = "repo:${var.github_owner}@${var.github_owner_id}/${var.github_repo}@${var.github_repo_id}"
}

# SEED holds the state, the vault and the runtime identity. DEV deploys into its own,
# empty group, so the deployer's rights can stop at that group and a DEV teardown
# never deletes the group itself.
resource "azurerm_resource_group" "seed" {
  name     = "rg-${var.name_prefix}-seed"
  location = var.location
  tags     = local.tags
}

resource "azurerm_resource_group" "dev" {
  name     = "rg-${var.name_prefix}-dev"
  location = var.location
  tags     = merge(local.tags, { env = "dev" })
}
