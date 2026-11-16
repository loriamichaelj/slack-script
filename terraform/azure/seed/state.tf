# Terraform state for SEED and DEV, one container each. The account is not destroyed by
# the destroy workflows: they only run against DEV, and prevent_destroy guards a local destroy.
# Network rules stay open on purpose: GitHub-hosted runners have no fixed address, so a
# default deny would lock out CI. Shared keys are off, so every request needs an Entra token.
#trivy:ignore:AZU-0012
resource "azurerm_storage_account" "state" {
  # checkov:skip=CKV_AZURE_33: queue logging does not apply, the account holds blobs only
  # checkov:skip=CKV_AZURE_35: GitHub's runners have no fixed address, so network rules cannot allow them; every request needs an Entra token instead
  # checkov:skip=CKV_AZURE_59: public network access stays on for the same reason; blob public access is off and shared keys are disabled
  # checkov:skip=CKV2_AZURE_1: Microsoft-managed encryption keys are enough for state
  # checkov:skip=CKV2_AZURE_33: private endpoints cost money and the runners could not reach them
  # checkov:skip=CKV2_AZURE_40: shared key access is disabled; this check is for the opposite setting
  # checkov:skip=CKV2_AZURE_41: no SAS tokens exist, because shared keys are off
  # checkov:skip=CKV_AZURE_206: locally redundant storage is enough for dev state
  # checkov:skip=CKV_AZURE_190: access is restricted by Entra roles, not by blob public access settings
  name                = var.state_account_name
  resource_group_name = azurerm_resource_group.seed.name
  location            = azurerm_resource_group.seed.location
  tags                = local.tags

  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

locals {
  state_containers = {
    seed = "seed-tfstate"
    dev  = "dev-tfstate"
  }
}

resource "azurerm_storage_container" "state" {
  # checkov:skip=CKV2_AZURE_21: read logging needs a Log Analytics workspace, which costs money; every access is already recorded in the Entra sign-in logs
  for_each = local.state_containers

  name                  = each.value
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"

  lifecycle {
    prevent_destroy = true
  }
}

# Blob data roles, by container: seed-admin and dev-deployer read, write and lock their
# own state, and the planner reads both without being able to change or lock them.
resource "azurerm_role_assignment" "state_writer" {
  for_each = {
    seed = azuread_service_principal.github["seed-admin"].object_id
    dev  = azuread_service_principal.github["dev-deployer"].object_id
  }

  scope                = azurerm_storage_container.state[each.key].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "state_reader" {
  for_each = local.state_containers

  scope                = azurerm_storage_container.state[each.key].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azuread_service_principal.github["tf-planner"].object_id
}
