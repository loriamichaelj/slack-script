variable "project_id" {
  description = "Project that runs the jobs. Its metrics scope covers the org (terraform/gcp/org)."
  type        = string
  default     = "slack-anomaly-dev"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "time_zone" {
  description = "Time zone for the routine report schedules."
  type        = string
  default     = "America/New_York"
}

variable "billing_table" {
  description = "Cloud Billing export table read by the cost report."
  type        = string
  default     = "slack-anomaly-dev.billing_export.gcp_billing_export_v1_01B37B_E44281_12EC5F"
}
