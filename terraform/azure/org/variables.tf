variable "location" {
  description = "Region of the audit workspace."
  type        = string
  default     = "eastus"
}

variable "resource_group" {
  description = "Resource group for the audit workspace."
  type        = string
  default     = "rg-platform-audit"
}

variable "workspace_name" {
  description = "Log Analytics workspace that receives the subscription's Activity Log. terraform/azure/dev looks it up by this name."
  type        = string
  default     = "log-platform-audit"
}

variable "retention_days" {
  description = "Days the workspace keeps data. Activity Log data is free to ingest and to keep for 90 days."
  type        = number
  default     = 90
}

variable "github_repo" {
  description = "Repository name, for the repo tag."
  type        = string
  default     = "slack-script"
}
