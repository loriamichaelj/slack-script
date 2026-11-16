# Holds the cooldown state, at app/state/alerts.json. Shared keys are off, so every request
# needs an Entra token.
# Network rules stay open: the jobs have no fixed address on the Consumption plan.
#trivy:ignore:AZU-0012
resource "azurerm_storage_account" "app" {
  # checkov:skip=CKV_AZURE_33: queue logging does not apply, nothing here uses queues
  # checkov:skip=CKV_AZURE_35: the jobs have no fixed address on this plan, so network rules cannot allow them; every request needs an Entra token instead
  # checkov:skip=CKV_AZURE_59: public network access stays on for the same reason; blob public access is off and shared keys are disabled
  # checkov:skip=CKV2_AZURE_1: Microsoft-managed encryption keys are enough for this data
  # checkov:skip=CKV2_AZURE_33: private endpoints cost money and the jobs could not reach them on this plan
  # checkov:skip=CKV2_AZURE_40: shared key access is disabled; this check is for the opposite setting
  # checkov:skip=CKV2_AZURE_41: no SAS tokens exist, because shared keys are off
  # checkov:skip=CKV_AZURE_206: locally redundant storage is enough for dev
  # checkov:skip=CKV_AZURE_190: access is restricted by Entra roles, not by blob public access settings
  # checkov:skip=CKV2_AZURE_38: soft delete is not needed, the state rebuilds itself
  name                = var.app_account_name
  resource_group_name = local.rg
  location            = local.location
  tags                = local.tags

  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
}

resource "azurerm_storage_container" "app" {
  # checkov:skip=CKV2_AZURE_21: read logging needs a Log Analytics diagnostic setting, which costs money; every access is already in the Entra sign-in logs
  name                  = "app"
  storage_account_id    = azurerm_storage_account.app.id
  container_access_type = "private"
}

# The jobs run as the runtime identity, which reads and writes the cooldown state.
resource "azurerm_role_assignment" "runtime_state" {
  scope                = azurerm_storage_container.app.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_user_assigned_identity.runtime.principal_id
}
