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

# Reader cannot list a job's secrets, which the provider does on every refresh once a job exists.
# This role has that one action, on the dev group only. For these jobs the list holds secret
# names and Key Vault references, and no values.
resource "azurerm_role_definition" "jobs_plan_reader" {
  name        = "anomaly-jobs-plan-reader"
  scope       = azurerm_resource_group.dev.id
  description = "List the secrets of Container Apps jobs, so a read-only plan can refresh them."

  permissions {
    actions = ["Microsoft.App/jobs/listSecrets/action"]
  }

  assignable_scopes = [azurerm_resource_group.dev.id]
}

resource "azurerm_role_assignment" "planner_lists_job_secrets" {
  scope              = azurerm_resource_group.dev.id
  role_definition_id = azurerm_role_definition.jobs_plan_reader.role_definition_resource_id
  principal_id       = azuread_service_principal.github["tf-planner"].object_id
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

# The identity the: read metrics and costs, read the webhook secrets.
# DEV adds access to its app-state storage.
resource "azurerm_user_assigned_identity" "runtime" {
  name                = "anomaly-runtime"
  resource_group_name = azurerm_resource_group.seed.name
  location            = azurerm_resource_group.seed.location
  tags                = local.tags
}

# Creating or updating a job that runs as the runtime identity needs the right to assign that
# identity. This role grants only that, on this one identity, and nothing else.
resource "azurerm_role_assignment" "deployer_assigns_runtime" {
  scope                = azurerm_user_assigned_identity.runtime.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azuread_service_principal.github["dev-deployer"].object_id
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
