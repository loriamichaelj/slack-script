variable "location" {
  type    = string
  default = "eastus"
}

variable "name_prefix" {
  description = "Prefix for resource group names: rg-<prefix>-seed and rg-<prefix>-dev."
  type        = string
  default     = "slack-anomaly"
}

variable "state_account_name" {
  description = "Storage account for Terraform state (3 to 24 lowercase letters and digits, unique in Azure)."
  type        = string
  default     = "slackanomalydevtfstate"
}

variable "key_vault_name" {
  description = "Key Vault for the Slack webhook secrets (3 to 24 characters, unique in Azure)."
  type        = string
  default     = "kv-slack-anomaly-dev"
}

variable "github_owner" {
  type    = string
  default = "loriamichaelj"
}

variable "github_repo" {
  type    = string
  default = "slack-script"
}

# GitHub's immutable subject claim embeds these IDs, and trusting the IDs
# stops a deleted and re-created repo of the same name from impersonating this one.
variable "github_owner_id" {
  type    = string
  default = "165821667"
}

variable "github_repo_id" {
  type    = string
  default = "1437191668"
}

variable "tags" {
  description = "Extra tags merged into the defaults applied to every resource."
  type        = map(string)
  default     = {}
}
