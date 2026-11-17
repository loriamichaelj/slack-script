variable "seed_resource_group" {
  description = "SEED's group, which holds the runtime identity and the Key Vault."
  type        = string
  default     = "rg-slack-anomaly-seed"
}

variable "resource_group" {
  description = "The empty group SEED created for this root to deploy into."
  type        = string
  default     = "rg-slack-anomaly-dev"
}

variable "runtime_identity" {
  type    = string
  default = "anomaly-runtime"
}

variable "key_vault_name" {
  type    = string
  default = "kv-slack-anomaly-dev"
}

variable "app_account_name" {
  description = "Storage account for the cooldown state (3 to 24 lowercase letters and digits, unique in Azure)."
  type        = string
  default     = "slackanomalydevapp"
}

variable "log_retention_days" {
  description = "How long the jobs' logs are kept (30 is the lowest Azure allows)."
  type        = number
  default     = 30
}

variable "daily_log_cap_gb" {
  description = "Most log data taken in per day. Keeps a runaway log from running up the bill."
  type        = number
  default     = 0.1
}

variable "budget" {
  description = "Monthly spend limit the cost report warns against, in USD."
  type        = number
  default     = 5
}
