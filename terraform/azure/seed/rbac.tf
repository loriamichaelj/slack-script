# seed-admin manages this directory, which creates role assignments, so it needs Owner.
# Only the SEED environment (reviewer, dev branch) can sign in as it.
resource "azurerm_role_assignment" "seed_admin" {
  scope                = local.subscription_scope
  role_definition_name = "Owner"
  principal_id         = azuread_service_principal.github["seed-admin"].object_id
}

# tf-planner reads everything, and can change nothing.
resource "azurerm_role_assignment" "planner_reads" {
  scope                = local.subscription_scope
  role_definition_name = "Reader"
  principal_id         = azuread_service_principal.github["tf-planner"].object_id
}

# dev-deployer can read the subscription, but only change things inside the dev group,
# where it also assigns roles to what DEV creates (the Function's access to storage).
resource "azurerm_role_assignment" "deployer_reads" {
  scope                = local.subscription_scope
  role_definition_name = "Reader"
  principal_id         = azuread_service_principal.github["dev-deployer"].object_id
}

resource "azurerm_role_assignment" "deployer_dev" {
  for_each = toset(["Contributor", "Role Based Access Control Administrator"])

  scope                = azurerm_resource_group.dev.id
  role_definition_name = each.value
  principal_id         = azuread_service_principal.github["dev-deployer"].object_id
}

# The identity the Function runs as: read metrics and costs, read the webhook secrets.
# DEV adds access to its app-state storage.
resource "azurerm_user_assigned_identity" "runtime" {
  name                = "anomaly-runtime"
  resource_group_name = azurerm_resource_group.seed.name
  location            = azurerm_resource_group.seed.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "runtime_subscription" {
  for_each = toset(["Monitoring Reader", "Cost Management Reader"])

  scope                = local.subscription_scope
  role_definition_name = each.value
  principal_id         = azurerm_user_assigned_identity.runtime.principal_id
}

resource "azurerm_role_assignment" "runtime_secrets" {
  scope                = azurerm_key_vault.webhooks.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.runtime.principal_id
}
