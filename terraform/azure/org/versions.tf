terraform {
  required_version = ">= 1.10"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # Shares the SEED state container under its own key. Pass the storage account and container
  # at init time (see README.md). Access uses Entra ID, never storage keys.
  backend "azurerm" {
    key              = "org.tfstate"
    use_azuread_auth = true
  }
}

# The subscription and tenant come from ARM_SUBSCRIPTION_ID and ARM_TENANT_ID (or the az
# login), so no account IDs are committed to this public repo.
provider "azurerm" {
  features {}

  storage_use_azuread             = true
  resource_provider_registrations = "none"
}
