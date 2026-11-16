output "tenant_id" {
  description = "Repository variable AZURE_TENANT_ID."
  value       = data.azurerm_client_config.current.tenant_id
}

output "subscription_id" {
  description = "Repository variable AZURE_SUBSCRIPTION_ID."
  value       = data.azurerm_subscription.current.subscription_id
}

output "client_ids" {
  description = "Repository variables AZURE_CLIENT_ID_<IDENTITY>, one per identity (dashes become underscores)."
  value       = { for name, app in azuread_application.github : name => app.client_id }
}

output "state" {
  description = "Backend settings for terraform init."
  value = {
    resource_group_name  = azurerm_resource_group.seed.name
    storage_account_name = azurerm_storage_account.state.name
    containers           = local.state_containers
  }
}

output "dev_resource_group" {
  description = "The empty group the DEV root deploys into."
  value       = azurerm_resource_group.dev.name
}

output "runtime_identity" {
  description = "The identity the Function runs as."
  value = {
    id           = azurerm_user_assigned_identity.runtime.id
    client_id    = azurerm_user_assigned_identity.runtime.client_id
    principal_id = azurerm_user_assigned_identity.runtime.principal_id
  }
}

output "key_vault" {
  description = "Vault holding the slack-webhook and slack-routine-webhook secrets."
  value       = { name = azurerm_key_vault.webhooks.name, uri = azurerm_key_vault.webhooks.vault_uri }
}
