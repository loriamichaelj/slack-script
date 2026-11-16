terraform {
  required_version = ">= 1.10"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
  }

  # The storage account is created by this root and passed at init time. Access uses
  # Entra ID, never storage keys. See README.md for the first-apply steps.
  backend "azurerm" {
    key              = "seed.tfstate"
    use_azuread_auth = true
  }
}

# The subscription and tenant come from ARM_SUBSCRIPTION_ID and ARM_TENANT_ID (or the az
# login), so no account IDs are committed to this public repo.
provider "azurerm" {
  features {}

  storage_use_azuread = true

  # The seed has the rights to register providers; DEV does not, so they are listed here.
  resource_provider_registrations = "none"
  resource_providers_to_register = [
    "Microsoft.App",
    "Microsoft.Authorization",
    "Microsoft.CostManagement",
    "Microsoft.Insights",
    "Microsoft.KeyVault",
    "Microsoft.ManagedIdentity",
    "Microsoft.OperationalInsights",
    "Microsoft.Storage",
  ]
}

provider "azuread" {}
