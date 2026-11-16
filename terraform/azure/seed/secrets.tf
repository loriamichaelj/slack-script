# Slack webhooks live here so tearing down DEV keeps them. Terraform creates the vault
# but never the secrets, so no webhook URL lands in state. Add each by hand (see
# README.md); the runtime identity may read them.
#trivy:ignore:AZU-0013
resource "azurerm_key_vault" "webhooks" {
  # checkov:skip=CKV_AZURE_109: the Function has no fixed address and is not a trusted service, so a firewall would block it
  # checkov:skip=CKV_AZURE_189: the vault is reached over the public endpoint by the Function and by you, and every request needs an Entra token
  # checkov:skip=CKV2_AZURE_32: a private endpoint costs money and the Function runs outside the network
  name                = var.key_vault_name
  resource_group_name = azurerm_resource_group.seed.name
  location            = azurerm_resource_group.seed.location
  tags                = local.tags

  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 7

  lifecycle {
    prevent_destroy = true
  }
}
