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

variable "slack_channel_id" {
  description = "Slack channel the routine reports share one message in (the channel ID, not its name)."
  type        = string
  default     = "C0CC5RTC4R0"
}

variable "time_zone" {
  description = "Time zone the routine reports are scheduled in. The jobs run at every UTC hour it can be, and skip the rest."
  type        = string
  default     = "America/New_York"
}

variable "budget" {
  description = "Monthly spend limit the cost report warns against, in USD."
  type        = number
  default     = 5
}

variable "audit_workspace" {
  description = "Log Analytics workspace that holds the subscription's Activity Log (terraform/azure/org)."
  type        = string
  default     = "log-platform-audit"
}

variable "audit_resource_group" {
  description = "Resource group of audit_workspace."
  type        = string
  default     = "rg-platform-audit"
}
