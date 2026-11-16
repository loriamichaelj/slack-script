terraform {
  required_version = ">= 1.10"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # The storage account is created by SEED and passed at init time. Access uses Entra ID.
  backend "azurerm" {
    key              = "dev.tfstate"
    use_azuread_auth = true
  }
}

# The subscription and tenant come from ARM_SUBSCRIPTION_ID and ARM_TENANT_ID (or the az
# login), so no account IDs are committed to this public repo. SEED registers the resource
# providers, because the deployer's rights stop at the dev resource group.
provider "azurerm" {
  features {}

  storage_use_azuread             = true
  resource_provider_registrations = "none"
}
